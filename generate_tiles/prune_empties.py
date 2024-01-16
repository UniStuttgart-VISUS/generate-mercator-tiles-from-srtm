import gzip
from typing import Set, Tuple

from .webmercatorcell import WebMercatorCell
from .logger import logger


class EmptyChecker:
    _empty_set: Set[Tuple[int, int, int]]

    def __init__(self, empty_set: Set[Tuple[int, int, int]]):
        self._empty_set = empty_set

    def __call__(self, cell: WebMercatorCell) -> bool:
        return (cell.level, cell.i, cell.j) in self._empty_set


def load_empties():
    empties = set()

    with gzip.open('empties.txt.gz', 'rb') as f:
        for line in f:
            w = line.decode().strip().removesuffix('.png')
            level, i, j = tuple(map(int, w.split('/')))

            empties.add((level, i, j))

    return EmptyChecker(empties)


def _inner_prune_empties(root: WebMercatorCell, checker: EmptyChecker):
    prune_count = 0
    for key in ['cell_0', 'cell_1', 'cell_2', 'cell_3']:
        child = getattr(root, key)
        if child is not None:
            if checker(child):
                setattr(root, key, None)
                prune_count += 1
            else:
                prune_count += _inner_prune_empties(child, checker)

    return prune_count


def prune_empties(root: WebMercatorCell):
    checker = load_empties()
    logger.info('Pruning %d empty cells.', len(checker._empty_set))
    pc = _inner_prune_empties(root, checker)
    logger.info('Actively pruned %d.', pc)

    return checker

