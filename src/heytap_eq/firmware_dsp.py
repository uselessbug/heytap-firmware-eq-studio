"""Firmware biquads copied from recovered, ARM-checked research formulas."""

import numpy as np

from heytap_eq.opkg import require

FILTER_TYPES = {0: "LOW_SHELF", 1: "PEAK", 2: "HIGH_SHELF", 3: "LOW_PASS", 4: "HIGH_PASS", 5: "ALL_PASS"}


def coefficients(filters, fs):
    """Normalized biquads, columns [b0,b1,b2,a0,a1,a2].

    Shelf alpha uses Q, as verified by the firmware; Q is not shelf slope S.
    """
    if not filters:
        return np.empty((0, 6))
    t = np.array([f["type_id"] for f in filters], dtype=int)
    g = np.array([f["gain"] for f in filters], dtype=float)
    fc = np.array([f["fc"] for f in filters], dtype=float)
    q = np.array([f["q"] for f in filters], dtype=float)
    require(np.all(np.isin(t, list(FILTER_TYPES))), "Unknown filter type")
    require(np.all(np.isfinite(g)) and np.all(np.isfinite(fc)) and np.all(np.isfinite(q)) and np.all(q > 0), "Invalid IIR parameters")
    w = 2 * np.pi * fc / fs
    c, alpha = np.cos(w), np.sin(w) / (2 * q)
    A = 10 ** (g / 40)
    a0, a1, a2 = 1 + alpha, -2 * c, 1 - alpha
    b0, b1, b2 = np.ones(len(t)), np.zeros(len(t)), np.zeros(len(t))
    for typ in FILTER_TYPES:
        m = t == typ
        if typ == 1:
            a0[m], a2[m] = (1 + alpha / A)[m], (1 - alpha / A)[m]
            b0[m], b1[m], b2[m] = (1 + alpha * A)[m], (-2 * c)[m], (1 - alpha * A)[m]
        elif typ in (0, 2):
            s = 2 * np.sqrt(A) * alpha
            if typ == 0:
                b0[m] = (A * ((A + 1) - (A - 1) * c + s))[m]
                b1[m] = (2 * A * ((A - 1) - (A + 1) * c))[m]
                b2[m] = (A * ((A + 1) - (A - 1) * c - s))[m]
                a0[m] = ((A + 1) + (A - 1) * c + s)[m]
                a1[m] = (-2 * ((A - 1) + (A + 1) * c))[m]
                a2[m] = ((A + 1) + (A - 1) * c - s)[m]
            else:
                b0[m] = (A * ((A + 1) + (A - 1) * c + s))[m]
                b1[m] = (-2 * A * ((A - 1) + (A + 1) * c))[m]
                b2[m] = (A * ((A + 1) + (A - 1) * c - s))[m]
                a0[m] = ((A + 1) - (A - 1) * c + s)[m]
                a1[m] = (2 * ((A - 1) - (A + 1) * c))[m]
                a2[m] = ((A + 1) - (A - 1) * c - s)[m]
        elif typ == 3:
            b0[m], b1[m], b2[m] = ((1 - c) / 2)[m], (1 - c)[m], ((1 - c) / 2)[m]
        elif typ == 4:
            b0[m], b1[m], b2[m] = ((1 + c) / 2)[m], (-(1 + c))[m], ((1 + c) / 2)[m]
        elif typ == 5:
            b0[m], b1[m], b2[m] = (1 - alpha)[m], (-2 * c)[m], (1 + alpha)[m]
    sos = np.column_stack([b0, b1, b2, a0, a1, a2]) / a0[:, None]
    sos[(fc <= 0) | (fc >= fs / 2)] = [1, 0, 0, 1, 0, 0]
    return sos


def response(filters, frequency, fs=48000, complex_output=False):
    sos = coefficients(filters, fs)
    z = np.exp(-2j * np.pi * np.asarray(frequency) / fs)[None, :]
    if not len(sos):
        h = np.ones(z.shape[1], dtype=complex)
    else:
        num = sos[:, 0, None] + sos[:, 1, None] * z + sos[:, 2, None] * z ** 2
        den = 1 + sos[:, 4, None] * z + sos[:, 5, None] * z ** 2
        h = np.prod(num / den, axis=0)
    return h if complex_output else 20 * np.log10(np.maximum(np.abs(h), 1e-30))


