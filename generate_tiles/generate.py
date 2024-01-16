from itertools import repeat
import math
import sys
import os.path
from pathlib import Path
from typing import Callable, Sequence, Tuple
from multiprocessing.pool import Pool

import numpy as np
from PIL import Image

from .logger import logger
from .webmercatorcell import WebMercatorCell, generate_webmercator_grid
from .mercator import proj_mercator, invert_mercator
from .imagetools import read_cell, equirectangular_image_to_mercator, to_hillshade
from .constants import IN_IMAGE_MODE, INTERMEDIATE_DTYPE, DIM, INTERMEDIATE_IMAGE_MODE
from .utils import LinearInterpolator
from .prune_empties import EmptyChecker, prune_empties



def _get_latlng_extent(node: WebMercatorCell) -> Tuple[Sequence[Tuple[int, int]], int, int, int, int]:
    indices = node.get_srtm_tile_indices(mercator_margin=1.1 * 8/256)

    lng_min = min([v[0] for v in indices])
    lng_max = max([v[0] for v in indices])
    lat_min = min([v[1] for v in indices])
    lat_max = max([v[1] for v in indices])

    return indices, lng_min, lng_max, lat_min, lat_max


def _load_and_join_tiles(
        node: WebMercatorCell,
        indices: Sequence[Tuple[int, int]],
        delta_lng: int,
        delta_lat: int,
        lat_max: int,
        lng_min: int,
        per_tile_size: int = DIM,
) -> np.ndarray:
    overlap_size = 1 if per_tile_size == DIM else 0

    logger.debug('Loading Mercator tile data for %d/%d of level %d (%d x %d SRTM tiles) with a per-tile size of %d x %d.', node.i, node.j, node.level, delta_lng, delta_lat, per_tile_size, per_tile_size)

    px_width = (per_tile_size - overlap_size) * delta_lng + overlap_size
    px_height = (per_tile_size - overlap_size) * delta_lat + overlap_size
    data = np.ndarray((px_height, px_width), INTERMEDIATE_DTYPE)

    for lng, lat in indices:
        logger.debug('Loading SRTM tile at latitude %d, longitude %d.', lat, lng)
        x0 = (per_tile_size - overlap_size) * (lat_max - lat)
        y0 = (per_tile_size - overlap_size) * (lng - lng_min)

        tiledata = read_cell(lat, lng)

        if per_tile_size != DIM:
            # resize
            img = Image.fromarray(tiledata[:-1,:-1], mode=INTERMEDIATE_IMAGE_MODE)
            img2 = img.resize((per_tile_size, per_tile_size), resample=Image.Resampling.BILINEAR)
            tiledata = np.asarray(img2, INTERMEDIATE_DTYPE)

        data[x0:x0+per_tile_size, y0:y0+per_tile_size] = tiledata

    return data


def _project_to_mercator(
        data: np.ndarray,
        lng_min: int,
        lng_max: int,
        lat_min: int,
        lat_max: int,
        delta_lng: int,
        delta_lat: int,
        tile_scale: int = DIM - 1,
) -> Tuple[np.ndarray, Callable[[float], float], Callable[[float], float]]:
    data_merc = equirectangular_image_to_mercator(data, lat_min, lng_min, dlat=delta_lat, dlng=delta_lng, tile_scale=tile_scale)

    merc_height, merc_width = data_merc.shape
    merc_extent_x0, merc_extent_y0 = proj_mercator(lat_min, lng_min)
    merc_extent_x1, merc_extent_y1 = proj_mercator(lat_max+1, lng_max+1)

    x_to_px = LinearInterpolator(merc_extent_x0, merc_extent_x1, 0, merc_width)
    y_to_px = LinearInterpolator(merc_extent_y1, merc_extent_y0, 0, merc_height)

    return data_merc, x_to_px, y_to_px


def _save_tile(node: WebMercatorCell, tile_directory: str, img: Image.Image) -> str:
    dirname = os.path.join(tile_directory, str(node.level), str(node.i))
    Path(dirname).mkdir(parents=True, exist_ok=True)

    with open(os.path.join(dirname, F'{node.j}.png'), 'wb') as f:
        img.save(f, 'png')

    return dirname


def _generate_tile_from_data(
        node: WebMercatorCell,
        data: np.ndarray,
        xscale: Callable[[float], float],
        yscale: Callable[[float], float],
        tile_directory: str,
) -> None:
    # calculate box of tile
    px_x0 = xscale(node.x0)
    px_x1 = xscale(node.x1)

    px_y0 = yscale(node.y0)
    px_y1 = yscale(node.y1)

    # add margin so that the hillshade gradient operator's boundary conditions don't affect the resulting tile
    px_dx = px_x1 - px_x0
    margin = 1/32 * px_dx  # 8 px each side -> 1/16th of 256px
    ix0 = round(px_x0 - margin)
    ix1 = round(px_x1 + margin + 1)
    iy0 = round(px_y0 - margin)
    iy1 = round(px_y1 + margin + 1)

    data_cropped = data[iy0:iy1, ix0:ix1].copy()

    cropped = Image.fromarray(data_cropped, mode=INTERMEDIATE_IMAGE_MODE)
    cropped_resized = cropped.resize((256 + 16, 256 + 16), resample=Image.Resampling.BILINEAR)

    # apply shading
    img_with_margin = to_hillshade(np.array(cropped_resized))

    img = img_with_margin.crop((8, 8, 256+8, 256+8))

    dirname = _save_tile(node, tile_directory, img)

    heights = cropped_resized.convert(mode='I') \
        .resize((128,128), box=(8, 8, 255+8, 255+8), resample=Image.Resampling.BILINEAR)

    with open(os.path.join(dirname, F'{node.j}.hgt.pgm'), 'wb') as f:
        heights.save(f, 'PPM')


def _get_heightdata(tile_directory: str, level: int, i: int, j: int) -> np.ndarray:
    maxindex = 2**level
    if i < 0:
        i = maxindex + i
    elif i >= maxindex:
        i = i - maxindex

    fname = os.path.join(tile_directory, str(level), str(i), F'{j}.hgt.pgm')
    if not os.path.exists(fname):
        logger.debug('Height data for node %d/%d of level %d does not exist.', i, j, level)
        return np.zeros((128, 128), INTERMEDIATE_DTYPE)

    with open(fname, 'rb') as f:
        img = Image.open(f, 'r').convert(mode='I;16B')
        return np.asfarray(img, dtype=INTERMEDIATE_DTYPE)


def generate_mercator_tile_grid(node: WebMercatorCell, tile_directory: str, checker: EmptyChecker, level: int = 12):
    if checker(node):
        logger.info('Node %s is fully empty and can be skipped.', node)
        return

    indices, lng_min, lng_max, lat_min, lat_max = _get_latlng_extent(node)

    delta_lng = lng_max + 1 - lng_min
    delta_lat = lat_max + 1 - lat_min

    # on a 32GB RAM machine, two threads can feasibly create tiles of level 7
    # this way. if the max_level is lower than that, the tiles need to be
    # downsized during creation already, otherwise too much RAM (up to hundreds
    # of GB) will be needed
    per_tile_size = DIM
    #if node.level < 7:
    #    factor = math.pow(2, 7 - node.level)
    #    per_tile_size = int((DIM-1) / factor)
    #    logger.info('Maximum tile level is %d. To reduce memory usage, SRTM tiles will be scaled down by a factor of %d on import (per-tile size: %d x %dpx).', node.level, factor, per_tile_size, per_tile_size)
    #
    data = _load_and_join_tiles(
        node,
        indices,
        delta_lng,
        delta_lat,
        lat_max,
        lng_min,
        per_tile_size=per_tile_size
    )

    data_merc, _x_to_px, _y_to_px = _project_to_mercator(data, lng_min, lng_max, lat_min, lat_max, delta_lng, delta_lat)

    node_list = list(filter(lambda v: v.level == level and not checker(v), node.flatten()))
    logger.info('Generating %d tiles of level %d for node %d/%d of level %d.',
                len(node_list),
                level,
                node.i, node.j,
                node.level,
                )

    for childnode in node_list:
        _generate_tile_from_data(childnode, data_merc, _x_to_px, _y_to_px, tile_directory)


def _generate_merged_cell_from_subcells(cell: WebMercatorCell, tile_directory: str, level: int):
    lvl = level + 1
    i0 = 2 * cell.i
    j0 = 2 * cell.j

    margin=8
    data = np.ndarray((256+2*margin, 256+2*margin), dtype=INTERMEDIATE_DTYPE)
    data.fill(0)

    # core data
    data[margin:128+margin,margin:128+margin] = _get_heightdata(tile_directory, lvl, i0, j0)
    data[margin:128+margin,128+margin:256+margin] = _get_heightdata(tile_directory, lvl, i0+1, j0)
    data[128+margin:256+margin,margin:128+margin] = _get_heightdata(tile_directory, lvl, i0, j0+1)
    data[128+margin:256+margin,128+margin:256+margin] = _get_heightdata(tile_directory, lvl, i0+1, j0+1)

    # margins
    data[:margin,:margin] = _get_heightdata(tile_directory, lvl, i0-1, j0-1)[-margin:,-margin:]
    data[:margin,margin:128+margin] = _get_heightdata(tile_directory, lvl, i0, j0-1)[-margin:,:]
    data[:margin,128+margin:256+margin] = _get_heightdata(tile_directory, lvl, i0+1, j0-1)[-margin:,:]
    data[:margin,256+margin:] = _get_heightdata(tile_directory, lvl, i0+2, j0-1)[-margin:,:margin]

    data[margin:128+margin,:margin] = _get_heightdata(tile_directory, lvl, i0-1, j0)[:,-margin:]
    data[margin:128+margin,256+margin:] = _get_heightdata(tile_directory, lvl, i0+2, j0)[:,:margin]

    data[128+margin:256+margin,:margin] = _get_heightdata(tile_directory, lvl, i0-1, j0+1)[:,-margin:]
    data[128+margin:256+margin,256+margin:] = _get_heightdata(tile_directory, lvl, i0+2, j0+1)[:,:margin]

    data[256+margin:,:margin] = _get_heightdata(tile_directory, lvl, i0-1, j0+2)[:margin,-margin:]
    data[256+margin:,margin:128+margin] = _get_heightdata(tile_directory, lvl, i0, j0+2)[:margin,:]
    data[256+margin:,128+margin:256+margin] = _get_heightdata(tile_directory, lvl, i0+1, j0+2)[:margin,:]
    data[256+margin:,256+margin:] = _get_heightdata(tile_directory, lvl, i0+2, j0+2)[:margin,:margin]

    hillshade_with_margin = to_hillshade(data)
    crop_box = (margin, margin, 256+margin, 256+margin)
    hillshade = hillshade_with_margin.crop(crop_box)

    dirname = _save_tile(cell, tile_directory, hillshade)
    if True:
        heights = Image.fromarray(data, mode=INTERMEDIATE_IMAGE_MODE) \
            .crop(crop_box) \
            .resize((128,128), resample=Image.Resampling.BILINEAR) \
            .convert(mode='I')

        with open(os.path.join(dirname, F'{cell.j}.hgt.pgm'), 'wb') as f:
            heights.save(f, 'PPM')


def hierarchically_merge_lower_level_cells(all_cells: Sequence[WebMercatorCell], tile_directory: str, maxlevel: int = 11, minlevel: int = 0, pool: Pool | None = None):
    for level in range(maxlevel, minlevel - 1, -1):
        cells = list(filter(lambda v: v.level == level, all_cells))

        logger.info('Generating %d high-level cells of level %d from the height data of level %d.', len(cells), level, level+1)

        if pool:
            pool.starmap(_generate_merged_cell_from_subcells, zip(cells, repeat(tile_directory), repeat(level)))
        else:
            for cell in cells:
                _generate_merged_cell_from_subcells(cell, tile_directory, level)


def generate_tiles(
    min_level: int,
    max_level: int,
    tile_directory: str,
):
    p = Path(tile_directory)
    if p.exists():
        logger.error('Tile directory "%s" already exists, aborting.', p)
        sys.exit(1)
    p.mkdir(exist_ok=False, parents=True)

    root = generate_webmercator_grid(max_level)
    all_cells = list(filter(lambda cell: cell.level >= min_level, root.flatten()))
    logger.info('Generated %d cells between levels %d and %d.', len(all_cells), min_level, max_level)
    checker = prune_empties(root)
    all_cells = list(filter(lambda cell: cell.level >= min_level, root.flatten()))
    logger.info('Pruned down to %d cells.', len(all_cells))

    pool = Pool(2)
    maxlevel_count = sum(v.level == max_level for v in all_cells)

    # on a 32GB RAM machine, two threads can feasibly create higher-level tiles
    # from a composite image of level 7 before too much RAM is used

    blocklevel = max(min_level, 7, max_level - 5)  # have blocks of a size of 1024 (32x32) ideally
    blocklevel_cells = list(filter(lambda n: n.level == blocklevel, root.flatten()))
    logger.info('Generating %d cells of level %d in %d blocks of level %d.', maxlevel_count, max_level, len(blocklevel_cells), blocklevel)

    pool.starmap(generate_mercator_tile_grid, zip(blocklevel_cells, repeat(tile_directory), repeat(checker), repeat(max_level)))
    hierarchically_merge_lower_level_cells(all_cells, tile_directory=tile_directory, minlevel=min_level, maxlevel=max_level - 1, pool=Pool(6))