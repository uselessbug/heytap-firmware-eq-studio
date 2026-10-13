"""Centered, independent transitions for additional correction; never gates the baseline."""

import math
from dataclasses import asdict, dataclass

import numpy as np

OUTSIDE_REFERENCE_DB = .2


@dataclass
class CorrectionRange:
    enabled: bool = False
    low_hz: float = 20.
    high_hz: float = 20000.
    low_octaves: float = 1.
    high_octaves: float = 1.

    def validate(self):
        values = (self.low_hz, self.high_hz, self.low_octaves, self.high_octaves)
        if type(self.enabled) is not bool or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                                or not math.isfinite(v) for v in values):
            raise ValueError("Correction range values must be finite numbers")
        if not (20 <= self.low_hz < self.high_hz <= 20000
                and 1/3-1e-6 <= self.low_octaves <= 2 and 1/3-1e-6 <= self.high_octaves <= 2):
            raise ValueError("Invalid correction boundaries or transition widths")
        return self

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError("Invalid correction range")
        try:
            return cls(**value).validate()
        except TypeError as exc:
            raise ValueError("Invalid correction range fields") from exc

    @property
    def limited(self):
        return self.enabled and (self.low_hz > 20 or self.high_hz < 20000)

    def widths(self):
        self.validate()
        low = self.low_octaves if self.low_hz > 20 else 0.
        high = self.high_octaves if self.high_hz < 20000 else 0.
        scale = min(1., 2*math.log2(self.high_hz/self.low_hz)/(low+high)) if low+high else 1.
        return low*scale, high*scale

    def edges(self):
        low, high = self.widths()
        return (self.low_hz/2**(low/2), self.low_hz*2**(low/2),
                self.high_hz/2**(high/2), self.high_hz*2**(high/2))

    def weights(self, frequency):
        self.validate()
        frequency = np.asarray(frequency, dtype=float)
        if not self.limited:
            return np.ones_like(frequency)
        low, high = self.widths()

        def smooth(t):
            t = np.clip(t, 0., 1.)
            return t*t*t*(10+t*(-15+6*t))

        left = smooth(np.log2(frequency/self.low_hz)/low+.5) if low else np.ones_like(frequency)
        right = smooth(np.log2(self.high_hz/frequency)/high+.5) if high else np.ones_like(frequency)
        return np.minimum(left, right)

    def outside(self, frequency):
        frequency = np.asarray(frequency)
        result = np.zeros_like(frequency, dtype=bool)
        if self.limited:
            low_outer, _, _, high_outer = self.edges()
            if self.low_hz > 20:
                result |= frequency <= low_outer
            if self.high_hz < 20000:
                result |= frequency >= high_outer
        return result

    def knots(self, points=33):
        if not self.limited:
            return np.array([], dtype=float)
        a, b, c, d = np.clip(self.edges(), 20., 20000.)
        return np.unique(np.concatenate((np.geomspace(a, b, points), np.geomspace(c, d, points),
                                         [self.low_hz, self.high_hz])))

    def payload(self):
        low, high = self.widths()
        return {**asdict(self), "effective_low_octaves": low, "effective_high_octaves": high,
                "edges_hz": list(self.edges()), "outside_reference_db": OUTSIDE_REFERENCE_DB}
