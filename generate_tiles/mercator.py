import math
from typing import Tuple

R = 6371

def proj_mercator(lat: float, lng: float) -> Tuple[float, float]:
    x = R * lng * math.pi / 180
    y = R * math.log(math.tan(math.pi/4 + lat / 2 * math.pi / 180))

    return x, y

def invert_mercator(x: float, y: float) -> Tuple[float, float]:
    lng = (x * 180 / math.pi) / R

    res_log = y / R
    res_tan = math.exp(res_log)
    res_inner = math.atan(res_tan)
    lat = 360 * (res_inner - math.pi/4) / math.pi

    return lat, lng