#!/usr/bin/env python3

import sys
import argparse

from .generate import generate_tiles
from .logger import logger
from .generate_list_of_empties import generate_empties_file
from .create_archives import create_archive_commands
from .create_download_list import create_download_list


def _generate_empties(ns: argparse.Namespace):
    generate_empties_file(ns.min_level, ns.max_level, ns.output_file, ns.landmass_file)


def _generate_tiles(ns: argparse.Namespace):
    if ns.max_level < 7:
        logger.error('Maximum tile level must be at least 7. Otherwise, the intermediate tile chunks get too large.')
        sys.exit(1)

    generate_tiles(ns.min_level, ns.max_level, ns.output_directory)


def _generate_archive(ns: argparse.Namespace):
    create_archive_commands(ns.max_level)


def _generate_download(ns: argparse.Namespace):
    if ns.inside_max_level < ns.outside_max_level:
        logger.error('Inside maximum tile level must be larger or equal to outside maximum level.')
        sys.exit(1)

    create_download_list(ns.darus_url, ns.dataset_id, ns.polygon_file, ns.inside_max_level, ns.outside_max_level, use_api_token=ns.use_api_token)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()

    parser.description = 'Generate WebMercator "slippy" tiles with hillshading, based on the NASA SRTM altitude data.'

    parser.add_argument('--verbose', '-v', help='Show verbose logging.', action='store_true', default=False)

    sub = parser.add_subparsers(title='action')

    # action: generate a list of empty tiles, based on a GeoJSON file of landmasses
    generate_empties_parser = sub.add_parser('generate-empties', help='Generate the file of empty tiles.')
    generate_empties_parser.add_argument('--min-level', type=int, default=0, help='Minimum tile level. Default: 0')
    generate_empties_parser.add_argument('--max-level', type=int, default=12, help='Maximum tile level. Default: 12')
    generate_empties_parser.add_argument('--output-file', type=argparse.FileType('wb'), default='empties.txt.gz', help='GZIP-ed text file to which to write the list of empty tiles. Default: empties.txt.gz')
    generate_empties_parser.add_argument('landmass_file', type=argparse.FileType('r'), help='GeoJSON file containing Polygons and MultiPolygons of the landmasses. Recommendation: use the converted NaturalEarth data found here: https://github.com/martynafford/natural-earth-geojson/blob/master/10m/physical/ne_10m_land.7z')
    generate_empties_parser.set_defaults(func=_generate_empties)


    # action: generate non-empty tiles
    generate_tiles_parser = sub.add_parser('generate-tiles', help='Generate non-empty tiles.')
    generate_tiles_parser.add_argument('--min-level', type=int, default=0, help='Minimum tile level. Default: 0')
    generate_tiles_parser.add_argument('--max-level', type=int, default=12, help='Maximum tile level. Default: 12')
    generate_tiles_parser.add_argument('--output-directory', type=str, default='tiles', help='Directory to create tile hierarchy in. Default: ./tiles/')
    generate_tiles_parser.set_defaults(func=_generate_tiles)


    # action: generate archive and upload commands
    generate_archive_parser = sub.add_parser('generate-archive', help='Generate archive and upload commands.')
    generate_archive_parser.add_argument('--max-level', type=int, default=12, help='Maximum tile level. Default: 12')
    generate_archive_parser.set_defaults(func=_generate_archive)


    # action: generate download commands
    generate_download_parser = sub.add_parser('generate-download', help='Generate commands to download the tiles, or a subset thereof, for use.')
    generate_download_parser.add_argument('--darus-url', type=str, default='https://darus.uni-stuttgart.de', help='DaRUS base URL')
    generate_download_parser.add_argument('--dataset-id', type=str, default='doi:10.18419/darus-3837', help='Dataset ID (persistentId)')
    generate_download_parser.add_argument('--polygon-file', help='GeoJSON polygon file within which to subdivide tiles. If not passed, everything is assumed to be inside the polygon (i.e., a full tile set is generated).', default=None, type=argparse.FileType('r'))
    generate_download_parser.add_argument('--inside-max-level', type=int, default=12, help='Maximum tile level inside the GeoJSON feature(s), if passed. Default: 0')
    generate_download_parser.add_argument('--outside-max-level', type=int, default=5, help='Maximum tile level outside the GeoJSON feature(s), if passed. Default: 5')
    generate_download_parser.add_argument('--use-api-token', action='store_true', default=False, help='Use a DaRUS API token for access to the repository. This should only be necessary during testing. If DARUS_API_TOKEN is present in the shell environment, its value is used.')
    generate_download_parser.set_defaults(func=_generate_download)


    ns = parser.parse_args()
    if ns.verbose:
        import logging
        logger.setLevel(logging.DEBUG)

    if 'func' in ns:
        ns.func(ns)
    else:
        parser.print_usage()
        sys.exit(1)




    # generate upload and archive commands
  #  create_archive_commands()