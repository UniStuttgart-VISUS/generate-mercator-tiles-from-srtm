from typing import List, Sequence, Generator
import io
import gzip

from geojson import FeatureCollection, Feature, load, dump, Polygon
from turfpy.transformation import intersect

from .webmercatorcell import WebMercatorCell, generate_webmercator_grid
from .mercator import proj_mercator, invert_mercator
from .logger import logger


def generate_empties_file(
    min_level: int,
    max_level: int,
    output_file: io.BufferedWriter,
    geojson_file: io.TextIOWrapper,
):
    tiles = generate_list_of_empty_tiles(geojson_file, min_level, max_level)
    tiles = sorted(tiles, key=lambda tile: (tile.level, tile.i, tile.j))

    with gzip.open(output_file, 'w') as f:
        for tile in tiles:
            f.write(F'{tile.level}/{tile.i}/{tile.j}.png\n'.encode())


def generate_list_of_empty_tiles(
    geojson_file: io.TextIOWrapper,
    min_level: int = 0,
    max_level: int = 12,
) -> Sequence[WebMercatorCell]:
    empties = set()

    j = load(geojson_file)
    polygons = FeatureCollection(list(filter(lambda feature: 'Polygon' in feature['geometry']['type'], j['features'])))

    logger.info('Loaded %d Polygon and MultiPolygon features to compare against.', len(polygons['features']))

    root = generate_webmercator_grid(max_level)
    all_cells = list(filter(lambda v: v.level >= min_level, root.flatten()))

    logger.info('Generated %d WebMercator cells between levels %d and %d.', len(all_cells), min_level, max_level)

    # clip intersection polygons for sub-areas, then check all cells of the highest level first
    # cells of level N-1 are empty if all their direct children (level N) are empty

    intermediate_cells = list(filter(lambda v: v.level == max(min_level, max_level - 7), all_cells))
    for intermediate_cell_index, intermediate_cell in enumerate(intermediate_cells):
        # reduce polygons
        lat0, lng0 = invert_mercator(intermediate_cell.x0, intermediate_cell.y0)
        lat1, lng1 = invert_mercator(intermediate_cell.x1, intermediate_cell.y1)

        polygon = Feature(geometry=Polygon([[
            (lng0, lat0),
            (lng1, lat0),
            (lng1, lat1),
            (lng0, lat1),
            (lng0, lat0),
        ]]))
        p2 = []
        for p in polygons['features']:
            v = intersect([p, polygon])
            if v is not None:
                p2.append(v)

        polygons_clipped = FeatureCollection(p2)

        highest_level_cells = list(filter(lambda v: v.level == max_level, intermediate_cell.flatten()))
        empty_count = 0
        for cell in highest_level_cells:
            lat0, lng0 = invert_mercator(cell.x0, cell.y0)
            lat1, lng1 = invert_mercator(cell.x1, cell.y1)

            polygon = Feature(geometry=Polygon([[
                (lng0, lat0),
                (lng1, lat0),
                (lng1, lat1),
                (lng0, lat1),
                (lng0, lat0),
            ]]))

            # lat0 > lat1
            if lat0 < -60:
                does_intersect = False
            elif lat1 > 60:
                does_intersect = False
            else:
                does_intersect = any(map(lambda f: intersect([f, polygon]) is not None, polygons_clipped['features']))

            if not does_intersect:
                empties.add(cell)
                empty_count += 1

        logger.info('Found %d (of %d) empty cells of level %d in partition cell (%s, %d/%d).', empty_count, len(highest_level_cells), max_level, intermediate_cell, intermediate_cell_index + 1, len(intermediate_cells))


    # go up the hierarchy
    for level in range(max_level - 1, min_level - 1, -1):
        cells_of_level = list(filter(lambda v: v.level == level, all_cells))
        empty_count = 0

        for cell in cells_of_level:

            if cell.cell_0 in empties and cell.cell_1 in empties and cell.cell_2 in empties and cell.cell_3 in empties:
                empty_count += 1
                empties.add(cell)

        logger.info('Found %d (of %d) empty cells of level %d.', empty_count, len(cells_of_level), level)

    return list(empties)
