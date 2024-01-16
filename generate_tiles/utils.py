from __future__ import annotations
from dataclasses import dataclass

@dataclass
class LinearInterpolator:
    domain_0: float
    domain_1: float
    range_0: float
    range_1: float

    def __call__(self, value: float) -> float:
        return self.range_0 + (value - self.domain_0) / (self.domain_1 - self.domain_0) * (self.range_1 - self.range_0)

    def invert(self) -> LinearInterpolator:
        return LinearInterpolator(self.range_0, self.range_1, self.domain_0, self.domain_1)