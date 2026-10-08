"""Untrusted structural candidates. Discovery never grants semantic or write access."""

import math
import struct

import numpy as np


def discover(raw, limit=100):
    if len(raw) > 32*1024*1024:
        raise ValueError("Candidate scanner currently supports images up to 32 MiB")
    if len(raw) < 300:
        return {"writable": False, "candidates": [], "truncated": False}
    count = (len(raw)-300)//4+1
    dtype = np.dtype([("gain0", "<f4"), ("gain1", "<f4"), ("count", "<u4")])
    view = np.ndarray((count,), dtype=dtype, buffer=raw, strides=(4,))
    valid = np.isfinite(view["gain0"]) & np.isfinite(view["gain1"])
    valid &= (view["gain0"] >= -60) & (view["gain0"] <= 6)
    valid &= (view["gain1"] >= -60) & (view["gain1"] <= 6)
    valid &= (view["count"] >= 1) & (view["count"] <= 18)
    results = []
    truncated = False
    for index in np.flatnonzero(valid):
        offset = int(index)*4
        filters = []
        n = int(view["count"][index])
        for slot in range(n):
            kind, gain, fc, q = struct.unpack_from("<Ifff", raw, offset+12+slot*16)
            if not (kind <= 5 and all(math.isfinite(x) for x in (gain, fc, q))
                    and -60 <= gain <= 24 and 0 < fc < 22050 and .01 <= q <= 100):
                break
            filters.append({"type_id_candidate": kind, "gain": gain, "fc": fc, "q": q})
        if len(filters) != n:
            continue
        if len(results) == limit:
            truncated = True
            break
        # A matching word is only a candidate pointer, not proof of selector semantics.
        pointer = struct.pack("<I", 0x10028000+offset)
        refs = []
        at = raw.find(pointer)
        while at >= 0 and len(refs) < 16:
            if at % 4 == 0:
                refs.append(at)
            at = raw.find(pointer, at+1)
        results.append({"raw_offset": offset, "gain0": float(view["gain0"][index]),
                        "gain1": float(view["gain1"][index]), "count": n, "filters": filters,
                        "possible_pointer_words_at_base_0x10028000": refs})
    return {"writable": False, "candidates": results, "truncated": truncated,
            "interpretation": "Only plausible numeric records and pointer words; type meaning, base address, tables and preset names remain unverified."}
