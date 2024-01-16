from typing import Callable, Tuple, Sequence

from geojson import Feature
from turfpy.transformation import intersect

from .webmercatorcell import WebMercatorCell
from .mercator import proj_mercator, invert_mercator


def generate_within_polygon_checker(features: Sequence[Feature]) -> Callable[[WebMercatorCell], bool]:
    def checker(cell: WebMercatorCell) -> bool:
        polygon = cell.to_geojson()

        return any(map(lambda feature: intersect([feature, polygon]) is not None, features))

    return checker
