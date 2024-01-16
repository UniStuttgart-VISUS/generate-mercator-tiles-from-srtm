import math
from functools import lru_cache
import os.path
import zipfile

import numpy as np
import earthpy.spatial as es
from PIL import Image

from .mercator import proj_mercator, invert_mercator
from .constants import IN_DTYPE, INTERMEDIATE_DTYPE, INTERMEDIATE_NAN, DIM, HILLSHADE_AZIMUTH, OUT_DTYPE
from .logger import logger


def equirectangular_image_to_mercator(
        data: np.ndarray,
        lat: float,
        lng: float,
        dlat: float=1,
        dlng: float=1,
        tile_scale: int = DIM-1,
        ) -> np.ndarray:
    '''
    Project an equirectangular 2D array to Mercator. The top left corner is at
    (lat + dlat, lng), the bottom right corner is at (lat, lng + dlng).
    '''

    x0, y0 = proj_mercator(lat, lng)
    x1, y1 = proj_mercator(lat + dlat, lng + dlng)

    dx = x1 - x0
    dy = y1 - y0

    dxd = data.shape[1]
    pixel_ratio = dxd / dx

    width = dxd
    height = math.floor(dy * pixel_ratio)

    #np.seterr(all='raise')

    # row 0 is at the top
    data_out = np.ndarray((height, width), INTERMEDIATE_DTYPE)
    for row in range(height):
        row_y0 = y1 - row/height * dy
        row_y1 = y1 - (row+1)/height * dy

        lat_row_0, _ = invert_mercator(0, row_y0)
        lat_row_1, _ = invert_mercator(0, row_y1)

        delta_from_top_eqrect_0 = lat + dlat - lat_row_0
        delta_from_top_eqrect_1 = lat + dlat - lat_row_1

        index_0 = max(0, math.floor(delta_from_top_eqrect_0 * tile_scale))
        index_1 = math.ceil(delta_from_top_eqrect_1 * tile_scale)

        if index_0 < 0 or index_1 >= data.shape[0]:
            pass
            #logger.warning('index_0 = %d, index_1 = %d, data.shape = %s, lat_row_0 = %f, lat_row_1 = %f, lat0 = %f, lng0 = %f, lat1 = %f, lng1 = %f',
            #               index_0, index_1, data.shape,
            #               lat_row_0, lat_row_1, lat, lng, lat+dlat, lng+dlng)
        data_row = data[index_0:index_1+1,:].mean(axis=0)
        data_out[row,:] = data_row

    return data_out


#@lru_cache(32)
def read_cell(lat: int, lng: int) -> np.ndarray:
    '''
    Read a SRTM tile.
    '''
    ns, lat = ('N', lat) if lat >= 0 else ('S', -lat)
    ew, lng = ('E', lng) if lng >= 0 else ('W', -lng)

    fragment = F'{ns}{lat:02d}{ew}{lng:03d}'
    fname = F'data/{fragment}.SRTMGL1.hgt.zip'

    if not os.path.exists(fname):
        logger.debug('Tile at %s%02d %s%03d does not exist, returning empty tile.', ns, lat, ew, lng)
        arr = np.ndarray((DIM, DIM), INTERMEDIATE_DTYPE)
        arr.fill(INTERMEDIATE_NAN)
        return arr

    with zipfile.ZipFile(fname) as zf:
        with zf.open(zf.namelist()[0]) as f:  # sometimes, the file is called '{fragment}.SRTMGL1.hgt', but mostly the '.SRTMGL1' part is missing from the name
            decompressed = f.read()

            data = np.ndarray((DIM, DIM), IN_DTYPE, decompressed)
            no_value = (data == -32768)

            data2 = np.asfarray(data, dtype=INTERMEDIATE_DTYPE)
            data2[no_value] = INTERMEDIATE_NAN

            return data2


def to_hillshade(data: np.ndarray) -> Image.Image:
    '''
    Create hillshading luminance data from a height map.
    '''
    hillshade = es.hillshade(data, azimuth=HILLSHADE_AZIMUTH)

    # to output type
    out_array = np.asarray(hillshade, OUT_DTYPE)

    # lighten
    out_array = 255 - ((255 - out_array) // 3)

    return Image.fromarray(out_array, mode='L')


@lru_cache(32)
def read_as_hillshade(lat: int, lng: int) -> Image.Image:
    data = read_cell(lat, lng)
    return to_hillshade(data)