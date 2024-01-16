from __future__ import annotations
from dataclasses import dataclass
from typing import Callable, Sequence, List, Tuple
import math

from geojson import Feature, Polygon

from .mercator import proj_mercator, invert_mercator

@dataclass
class WebMercatorCell:
    level: int
    i: int
    j: int

    x0: float
    x1: float
    y0: float
    y1: float

    cell_0: None | WebMercatorCell
    cell_1: None | WebMercatorCell
    cell_2: None | WebMercatorCell
    cell_3: None | WebMercatorCell


    def conditional_recursive_subdivide(self, condition: Callable[[WebMercatorCell], bool], max_depth: int = 0):
        if self.level >= max_depth:
            return

        xmid = (self.x0 + self.x1) / 2
        ymid = (self.y0 + self.y1) / 2

        for cell_key, i, j, x0, x1, y0, y1 in [
            ('cell_0', 2 * self.i, 2 * self.j, self.x0, xmid, self.y0, ymid),
            ('cell_1', 2 * self.i + 1, 2 * self.j, xmid, self.x1, self.y0, ymid),
            ('cell_2', 2 * self.i, 2 * self.j + 1, self.x0, xmid, ymid, self.y1),
            ('cell_3', 2 * self.i + 1, 2 * self.j + 1, xmid, self.x1, ymid, self.y1),
        ]:
            cell = self.__getattribute__(cell_key) or WebMercatorCell(self.level + 1, i, j, x0, x1, y0, y1, None, None, None, None)
            if condition(cell):
                self.__setattr__(cell_key, cell)
                self.__getattribute__(cell_key).conditional_recursive_subdivide(condition, max_depth)


    def full_recursive_subdivide(self, max_depth: int = 0):
        return self.conditional_recursive_subdivide(lambda _: True, max_depth)


    def contains(self, x, y) -> bool:
        # y1 < y0
        return not (x < self.x0 or x > self.x1 or y < self.y1 or y > self.y0)


    def contains_srtm_data(self) -> bool:
        lat0, _ = invert_mercator(self.x0, self.y0)
        lat1, _ = invert_mercator(self.x1, self.y1)
        return not (lat1 > 60 or lat0 < -60)


    def get_srtm_tile_indices(self, mercator_margin: float = 0.03) -> List[Tuple[int, int]]:
        '''
        Mercator margin: percentage increase in tile width and height as a safe
        margin for the gradient calculation for the hillshades. By default, the
        256x256px tiles have a margin of 8px on each side. Hence, a margin of
        slightly over 8/256 = 1/32 -> 0.03 is suitable.
        '''
        dx = self.x1 - self.x0
        margin = mercator_margin * dx

        maxlat, minlng = invert_mercator(self.x0 - margin, self.y0 + margin)
        minlat, maxlng = invert_mercator(self.x1 + margin, self.y1 - margin)

        tiles = []
        for x in range(math.floor(minlng), math.ceil(maxlng)):
            for y in range(math.floor(minlat), math.ceil(maxlat)):
                tiles.append((x, y))

        return tiles


    def flatten(self) -> Sequence[WebMercatorCell]:
        l = [self]
        if self.cell_0:
            l += self.cell_0.flatten()
        if self.cell_1:
            l += self.cell_1.flatten()
        if self.cell_2:
            l += self.cell_2.flatten()
        if self.cell_3:
            l += self.cell_3.flatten()

        return l


    def prune_children(self, condition: Callable[[WebMercatorCell], bool]):
        for attr in ('cell_0', 'cell_1', 'cell_2', 'cell_3'):
            child = getattr(self, attr)
            if child is None:
                continue

            if condition(child):
                setattr(self, attr, None)
            else:
                child.prune_children(condition)


    def __repr__(self):
        return F'WebMercatorCell[level={self.level}, i={self.i}, j={self.j}]'


    def __hash__(self):
        return hash((self.level, self.i, self.j))


    def to_geojson(self) -> Feature:
        lat0, lng0 = invert_mercator(self.x0, self.y0)
        lat1, lng1 = invert_mercator(self.x1, self.y1)

        return Feature(geometry=Polygon(coordinates=[[
            [lng0, lat0],
            [lng1, lat0],
            [lng1, lat1],
            [lng0, lat1],
            [lng0, lat0],
        ]]))


def generate_webmercator_grid(refine_to_level: int = 0) -> WebMercatorCell:
    x0, _ = proj_mercator(0, -180)
    x1, _ = proj_mercator(0, 180)
    dx = x1 - x0
    lat0, lng0 = invert_mercator(0, x0)
    lat1, lng1 = invert_mercator(0, x1)

    x0, y0 = proj_mercator(lat1, -180)
    x1, y1 = proj_mercator(lat0, 180)

    root = WebMercatorCell(0, 0, 0, x0, x1, y0, y1, None, None, None, None)
    root.full_recursive_subdivide(refine_to_level)
    return root
