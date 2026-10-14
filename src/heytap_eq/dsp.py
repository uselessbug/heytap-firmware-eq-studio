"""Magnitude previews; external EQ response is not a claim of app DSP equivalence."""

import numpy as np

from heytap_eq.firmware_dsp import coefficients as firmware_coefficients
from heytap_eq.firmware_dsp import response as firmware_response

FIRMWARE_KIND = {"LS": 0, "PEAK": 1, "HS": 2, "LP": 3, "HP": 4, "ALL_PASS": 5}
SAMPLE_RATES = (44100, 48000, 96000)


def coefficients(filters, fs):
    if fs not in SAMPLE_RATES:
        raise ValueError("Unsupported sample rate")
    rows = []
    for f in filters:
        f.validate()
        if not f.enabled:
            continue
        if f.kind in FIRMWARE_KIND:
            rows.append(firmware_coefficients([{
                "type_id": FIRMWARE_KIND[f.kind], "gain": f.gain,
                "fc": f.frequency, "q": f.q,
            }], fs)[0])
        else:
            omega = 2 * np.pi * f.frequency / fs
            c, alpha = np.cos(omega), np.sin(omega) / (2 * f.q)
            numerator = [1, -2*c, 1] if f.kind == "NOTCH" else [alpha, 0, -alpha]
            rows.append(np.array(numerator + [1+alpha, -2*c, 1-alpha]) / (1+alpha))
    return np.asarray(rows).reshape(-1, 6)


def filter_response(filters, frequency, fs=48000):
    sos = coefficients(filters, fs)
    z = np.exp(-2j*np.pi*np.asarray(frequency)/fs)
    h = np.ones(len(z), dtype=complex)
    for b0, b1, b2, _, a1, a2 in sos:
        h *= (b0+b1*z+b2*z*z)/(1+a1*z+a2*z*z)
    return 20*np.log10(np.maximum(abs(h), 1e-30))


def correction(doc, frequency, fs=48000):
    doc.validate()
    frequency = np.asarray(frequency)
    gain = np.zeros(len(frequency))
    if doc.raw:
        points = np.asarray(doc.raw)
        gain = np.interp(np.log(frequency), np.log(points[:, 0]), points[:, 1])
    return (gain + filter_response(doc.filters, frequency, fs))*doc.correction_range.weights(frequency)


def flatten_correction(doc, fs=48000):
    """Export the effective response once, as RAW at an explicit sample rate."""
    import json
    from dataclasses import asdict

    from heytap_eq.eq_formats import EQDocument

    if fs not in SAMPLE_RATES:
        raise ValueError("Unsupported sample rate")
    frequency = np.unique(np.concatenate((np.geomspace(20, 20000, 4096),
                         doc.correction_range.knots(65), [p[0] for p in doc.raw],
                         [f.frequency for f in doc.filters if f.enabled])))
    # Match dump_eq's numeric precision before deduplicating coincident grid/edge points.
    frequency = np.unique([float(f"{f:.9g}") for f in frequency])
    values = correction(doc, frequency, fs)
    # Refine sharp PEQ features so logarithmic RAW interpolation follows the effective curve.
    # Filter centres and transition knots above prevent a narrow feature from being skipped.
    for _ in range(8):
        middle = np.sqrt(frequency[:-1]*frequency[1:])
        error = np.abs(correction(doc, middle, fs)-(values[:-1]+values[1:])/2)
        if not np.any(error > .001):
            break
        frequency = np.unique(np.concatenate((frequency, [float(f"{f:.9g}") for f in middle[error > .001]])))
        values = correction(doc, frequency, fs)
    else:
        raise ValueError("有效修正过于陡峭，无法可靠导出 RAW；请保存工程或调整滤波器")
    result = EQDocument(name=doc.name, raw=np.column_stack((frequency, values)).tolist(),
                        metadata={**doc.metadata, "HEYTAP_EFFECTIVE_CORRECTION": "1",
                                  "SAMPLE_RATE_HZ": str(fs),
                                  "APPLIED_CORRECTION_RANGE": json.dumps(asdict(doc.correction_range))})
    result.validate()
    return result


def firmware_curve(record, frequency, fs=48000):
    filters = [{k: f[k] for k in ("type_id", "gain", "fc", "q")}
               for f in record["slots"] if f["active"]]
    return firmware_response(filters, frequency, fs)
