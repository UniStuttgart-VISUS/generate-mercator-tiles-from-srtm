import sys
from typing import Callable, Sequence, NamedTuple, Tuple
import json
from pathlib import Path

from .webmercatorcell import WebMercatorCell, generate_webmercator_grid
from .logger import logger
from .mercator import invert_mercator
from .prune_empties import load_empties, prune_empties


class ZipPackage(NamedTuple):
    key: Tuple[int, int, int]
    filename: str
    description: str
    tiles: Sequence[WebMercatorCell]


def create_packages(max_level: int, prune_empty_nodes: bool = True) -> Sequence[ZipPackage]:
    packages: Sequence[ZipPackage] = []

    root = generate_webmercator_grid(max_level)

    # get empty cell set
    if prune_empty_nodes:
        prune_empties(root)

    all_cells = root.flatten()

    # first file contains all tiles up until level 5
    packages.append(ZipPackage(
        (0, 0, 0),
        'tiles__0_to_5',
        'All non-empty tiles of levels 0 to 5.',
        list(filter(lambda v: v.level <= 5, all_cells)),
    ))

    # other levels are split up into blocks
    # the blocks are the cells of the level minus 6 (e.g., for tile level 8, the 16 blocks from level 2 are used)
    for i in range(6, max_level + 1):
        block_level = i - 6
        blocks = list(filter(lambda v: v.level == block_level, all_cells))
        logger.info('Splitting cells of level %d into %d blocks of level %d.', i, len(blocks), block_level)
        for block in blocks:
            key = (i, block.i, block.j)
            filename = F'tiles__{i}__{block.level}_{block.i}_{block.j}'
            lat0, lng0 = invert_mercator(block.x0, block.y0)
            lat1, lng1 = invert_mercator(block.x1, block.y1)
            description = F'All non-empty tiles of level {i} that lie within the block {block.i}/{block.j} of level {block.level}. This block covers the area between latitudes {lat0:.6f} and {lat1:.6f} and longitudes {lng0:.6f} and {lng1:.6f}.'
            cells = list(filter(lambda v: v.level == i, block.flatten()))

            packages.append(ZipPackage(key, filename, description, cells))

    packages.sort(key = lambda package: package.key)

    return packages


def create_archive_commands(
    max_level: int = 12,
):
    p = Path('archive/')
    if p.exists():
        logger.error('Archive path already exists.')
        sys.exit(1)

    packages = create_packages(max_level)

    manifest_file_content = []
    archive_command_file_content = [
        'archive_dir=$(pwd)/archive',
        'tile_dir=$(pwd)/tiles',
        'cd $tile_dir'
    ]
    upload_command_file_content = [
        'export API_TOKEN=XXXX  # TODO: insert DaRUS token here',
        'export SERVER_URL="https://darus.uni-stuttgart.de/"',
        'export PERSISTENT_ID="doi:10.18419/darus-3837"'
    ]

    p.mkdir(exist_ok=True)

    for i, package in enumerate(packages):
        fname = F'{package.filename}.zip'

        manifest_file_content.append(F'{fname}:')

        with open(F'archive/{package.filename}.contents', 'w') as f:
            for cell in sorted(package.tiles, key=lambda v: (v.level, v.i, v.j)):
                cell_file_name = F'{cell.level}/{cell.i}/{cell.j}.png'
                print(cell_file_name, file=f)
                manifest_file_content.append(F'  {cell_file_name}')

        metadata = dict(
            description=package.description,
            directoryLabel='tiles',
            categories=['Data'],
            restrict='false',
            tabIngest='false',
        )
        with open(F'archive/{package.filename}.metadata', 'w') as f:
            json.dump(metadata, f)

        archive_command_file_content.append(F'zip -q /tmp/{package.filename}.zip -@ < $archive_dir/{package.filename}.contents')
        archive_command_file_content.append(F'( cd /tmp; zip -q $archive_dir/{package.filename}.zip.zip {package.filename}.zip )')
        archive_command_file_content.append(F'rm /tmp/{package.filename}.zip')

        upload_command_file_content.append(F'curl -H X-Dataverse-key:$API_TOKEN -X POST -F "file=@archive/{package.filename}.zip.zip;type=application/zip" -F "jsonData=@archive/{package.filename}.metadata" "$SERVER_URL/api/datasets/:persistentId/add?persistentId=$PERSISTENT_ID" > archive/{package.filename}.upload.log')

        if i < len(packages) - 1:
            manifest_file_content.append('')

    with open('manifest.txt', 'w') as f:
        [ print(l, file=f) for l in manifest_file_content ]

    with open('archive_commands', 'w') as f:
        [ print(l, file=f) for l in archive_command_file_content ]

    with open('upload_commands', 'w') as f:
        [ print(l, file=f) for l in upload_command_file_content ]