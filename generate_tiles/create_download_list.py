import os.path
import sys
import argparse
import os
from typing import Sequence

from geojson import Feature, FeatureCollection, Polygon, MultiPolygon, load
from requests import Session

from .webmercatorcell import WebMercatorCell, generate_webmercator_grid
from .logger import logger
from .generate_within_polygon import generate_within_polygon_checker
from .create_archives import create_packages
from .prune_empties import load_empties
from . import __version__

def _get_features(f: argparse.FileType) -> Sequence[Feature]:
    features = []
    fc = load(f)

    if type(fc) is Feature and type(fc['geometry']) in (Polygon, MultiPolygon):
        features.append(fc)
    elif type(fc) is FeatureCollection:
        for feature in fc['features']:
            assert type(feature) is Feature
            assert type(feature['geometry']) in (Polygon, MultiPolygon)

            features.append(feature)
    else:
        raise ValueError(fc['type'])

    return features


def create_download_list(
    darus_url: str,
    darus_id: str,
    polygon_file: argparse.FileType | None,
    inside_maxlevel: int,
    outside_maxlevel: int,
    use_api_token: bool = False,
):
    if polygon_file is not None:
        try:
            features = _get_features(polygon_file)

        except:
            logger.error('Polygon file must be a Feature with a Polygon geometry, or a FeatureCollection of such Features.')
            sys.exit(1)

        intersects_with_some = generate_within_polygon_checker(features)
        checker = lambda cell: cell.level <= outside_maxlevel or intersects_with_some(cell)

    else:
        checker = lambda _cell: True

    root = generate_webmercator_grid(outside_maxlevel)
    root.conditional_recursive_subdivide(checker, inside_maxlevel)
    all_tiles = root.flatten()

    if polygon_file:
        logger.info('Generated grid of %d tiles up to level %d, restricted to level %d outside of given polygon file.', len(all_tiles), inside_maxlevel, outside_maxlevel)
    else:
        logger.info('Generated grid of %d tiles up to level %d.', len(all_tiles), inside_maxlevel)

    # generate tree with the archives
    logger.info('Creating look-up table to determine what ZIP files to download.')
    packages = create_packages(inside_maxlevel, prune_empty_nodes=False)
    empty_checker = load_empties()

    # determine list of archives to download
    package_tilelists = dict()
    required_tile_set = { (tile.level, tile.i, tile.j) for tile in all_tiles }
    required_empty_tiles = list()

    download_tile_count = 0
    for package in packages:
        tiles = list()
        for tile in package.tiles:
            if (tile.level, tile.i, tile.j) in required_tile_set:
                if empty_checker(tile):
                    required_empty_tiles.append(tile)
                else:
                    tiles.append(tile)

        if len(tiles):
            download_tile_count += len(tiles)
            package_tilelists[package.filename] = tiles

    logger.info('Identified %d tiles to be downloaded across %d ZIP files. %d empty tiles can be symlinked.', download_tile_count, len(package_tilelists), len(required_empty_tiles))


    # load manifest from DaRUS
    logger.info('Querying dataset metadata from DaRUS...')
    session = Session()
    session.headers.update({
        'User-Agent': F'hillshaded-webmercator-tile-downloader, version {__version__}; https://github.com/UniStuttgart-VISUS/generate-mercator-tiles-from-srtm'
    })

    if use_api_token:
        logger.info('Using DaRUS API token for access.')
        session.headers.update({
            'X-Dataverse-key': os.environ.get('DARUS_API_TOKEN', 'invalid'),
        })

    request = session.get(
        F'{darus_url}/api/datasets/:persistentId/',
        params={
            'persistentId': darus_id,
        }
    )

    data = request.json()['data']

    dataset_version = data['latestVersion'].get('versionNumber')
    dataset_version_minor = data['latestVersion'].get('versionMinorNumber')
    dataset_version_str = ':draft' if data['latestVersion'].get('versionState') == 'DRAFT' else F'{dataset_version}.{dataset_version_minor}'
    dataset_title = next(filter(lambda v: v['typeName'] == 'title', data['latestVersion']['metadataBlocks']['citation']['fields']))['value']
    file_data = data['latestVersion']['files']

    logger.info('Got a manifest with %d files for version %s of dataset "%s".', len(file_data), dataset_version_str, dataset_title)

    # parse file list, create look-up
    data_ids = dict()
    for file in file_data:
        directory = file.get('directoryLabel', '')
        path = os.path.join(directory, file['label'])
        dataId = file['dataFile']['id']

        data_ids[path] = dataId


    # collect required files
    required_files = list()
    for fname in package_tilelists.keys():
        full_path = os.path.join('tiles', F'{fname}.zip')
        required_files.append((F'{fname}.zip', data_ids[full_path]))

    required_files.append(('empty.png', data_ids['tiles/empty.png']))


    # create download commands
    if use_api_token:
        api_key_command=F"api_token={os.environ.get('DARUS_API_TOKEN', 'XXXXX  # change this')}\n"
        api_key='-H X-Dataverse-key:$api_token'
    else:
        api_key_command=''
        api_key=''

    with open('download_commands', 'w') as f:
        if use_api_token:
            f.write(api_key_command)
        f.write('download_dir=$(pwd)/download   # change this if you want the downloads to go somewhere else\nmkdir -p $download_dir\n\n')


        for filename, data_id in required_files:
            f.write(F'curl {api_key} --output "$download_dir/{filename}" --location "{darus_url}/api/access/datafile/{data_id}" | tee "$download_dir/{filename}.log"\n')


    # create extraction commands
    with open('extraction_commands', 'w') as f:
        f.write('download_dir=$(pwd)/download   # change this if you want the downloads to go somewhere else\n')
        f.write('extraction_dir=$(pwd)/tiles    # change this if you want the extracted tiles to go somewhere else\n\n')

        for package_filename, tiles in package_tilelists.items():
            f.write(F'cat > $download_dir/{package_filename}.files <<EOF\n')
            for tile in tiles:
                f.write(F'{tile.level}/{tile.i}/{tile.j}.png\n')
            f.write('EOF\n')
            f.write(F'xargs -a $download_dir/{package_filename}.files unzip -d $extraction_dir $download_dir/{package_filename}.zip\n\n')


    # create softlink commands for empty tiles
    softlink_dirs = set()
    softlink_commands = list()

    for empty_tile in required_empty_tiles:
        dir = F'{empty_tile.level}/{empty_tile.i}'
        softlink_dirs.add(dir)
        softlink_commands.append(F'ln -s $download_dir/empty.png $extraction_dir/{dir}/{empty_tile.j}.png\n')

    with open('softlink_commands', 'w') as f:
        f.write('download_dir=$(pwd)/download   # change this if you want the downloads to go somewhere else\n')
        f.write('extraction_dir=$(pwd)/tiles    # change this if you want the extracted tiles to go somewhere else\n\n')

        for d in sorted(softlink_dirs):
            f.write(F'mkdir -p $extraction_dir/{d}\n')

        f.write('\n')

        for cmd in softlink_commands:
            f.write(cmd)


    # create Leaflet layer code
    with open('leaflet_code.js', 'w') as f:
        f.write('// change the tile URL as required\n')
        f.write('const tileUrl = `/tiles/{z}/{x}/{y}.png`;\n\n')

        if polygon_file is not None:
            f.write('''// `layerGroup` with two members. The lower one is always shown, the higher one only above the given zoom level.
const lowTileLayer = L.tileLayer(tileUrl, {
  attribution: 'Map data &copy; 2024 <a href="https://darus.uni-stuttgart.de/dataset.xhtml?persistentId=doi:10.18419/darus-3837" target="_blank">Max Franke</a>',
  maxNativeZoom: %d,
});
const highTileLayer = L.tileLayer(tileUrl, {
  minZoom: %d,
  maxNativeZoom: %d,
});

const tileLayer = L.layerGroup([lowTileLayer, highTileLayer]);
''' % (outside_maxlevel, outside_maxlevel+1, inside_maxlevel))
        else:
            f.write('''// tiles have the same level everywhere
const tileLayer = L.tileLayer(tileUrl, {
  attribution: 'Map data &copy; 2024 <a href="https://darus.uni-stuttgart.de/dataset.xhtml?persistentId=doi:10.18419/darus-3837" target="_blank">Max Franke</a>',
  minNativeZoom: 12,
  maxNativeZoom: %d,
});
''' % (inside_maxlevel, ))


