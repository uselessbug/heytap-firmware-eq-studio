#!/usr/bin/env python3
"""Enco X4 offline EQ research tool. No device connection or flashing.

GraphicEQ curves are fitted by magnitude; this is not an exact Wavelet DSP port.
The baseline is always the matching Dynaudio Original record, even when a
different built-in preset is selected as the destination.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys

import numpy as np
from scipy.optimize import least_squares

import opkg_tool as opkg

PRESETS = {
    "丹拿原声": {"protocol_id": 0, "mode_type": 42, "start": 0},
    "清亮高音": {"protocol_id": 1, "mode_type": 46, "start": 9},
    "纯享人声": {"protocol_id": 2, "mode_type": 28, "start": 18},
    "澎湃低音": {"protocol_id": 3, "mode_type": 29, "start": 27},
    "丹拿高解析": {"protocol_id": 7, "mode_type": 43, "start": 36},
}
FILTER_TYPES = {0: "LOW_SHELF", 1: "PEAK", 2: "HIGH_SHELF", 3: "LOW_PASS", 4: "HIGH_PASS", 5: "ALL_PASS"}
ANC_POSITIONS = {1: 0, 2: 1, 3: 2, 4: 2, 5: 3, 6: 4, 7: 5, 9: 6, 8: 7, 14: 8}
SAMPLE_RATES = (44100, 48000, 96000)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def parse_eq(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    lines = re.findall(r"^\s*GraphicEQ:\s*(.+)$", text, re.M | re.I)
    require(len(lines) == 1, "Expected exactly one GraphicEQ line")
    pairs = []
    for item in lines[0].split(";"):
        if item.strip():
            fields = item.strip().split()
            require(len(fields) == 2, "Each GraphicEQ point must be frequency and gain")
            pairs.append([float(v) for v in fields])
    points = np.asarray(pairs, dtype=float)
    require(len(points) >= 2 and np.all(np.isfinite(points)), "Invalid GraphicEQ values")
    require(np.all(points[:, 0] > 0) and np.all(np.diff(points[:, 0]) > 0), "Frequencies must increase strictly")
    require(points[0, 0] <= 20 and points[-1, 0] >= 19000, "Curve must cover 20 Hz through at least 19 kHz")
    require(np.max(np.abs(points[:, 1])) <= 24, "GraphicEQ gains exceed the prototype's 24 dB range")
    peq = []
    pattern = r"^\s*PEQ(\d+):\s*([\d.eE+-]+)\s+([\d.eE+-]+)\s+([\d.eE+-]+)\s+(\w+)\s*$"
    for number, fc, gain, q, typ in re.findall(pattern, text, re.M):
        require(typ.upper() in {"PEAK", "PK"}, f"Unsupported personal filter {typ}")
        vals = [float(gain), float(fc), float(q)]
        require(all(math.isfinite(v) for v in vals) and 0 < vals[1] < 21000 and 0.1 <= vals[2] <= 20
                and abs(vals[0]) <= 24, "Invalid personal PEQ")
        require(int(number) == len(peq) + 1, "PEQ numbers must be consecutive from 1")
        peq.append({"type_id": 1, "gain": vals[0], "fc": vals[1], "q": vals[2]})
    require(len(re.findall(r"^\s*PEQ\d+:", text, re.M)) == len(peq), "Malformed PEQ line")
    for field, actual in [("PEQ_COUNT", len(peq)), ("RAW_BANDS", len(points))]:
        match = re.search(rf"^\s*{field}:\s*(\d+)\s*$", text, re.M)
        if match:
            require(int(match.group(1)) == actual, f"{field} metadata does not match the content")
    return {"name": Path(path).stem, "source_sha256": opkg.sha(Path(path).read_bytes()),
            "graphic_points": points.tolist(), "personal_peq": peq,
            "interpretation": "All listed PEQs are cascaded with RAW; SELECTED_PEQ is ignored as UI selection."}


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


def correction(eq, frequency, fs=48000):
    p = np.asarray(eq["graphic_points"])
    # Equalizer APO-style magnitude interpretation, not Wavelet implementation verification.
    return np.interp(np.log(frequency), np.log(p[:, 0]), p[:, 1]) + response(eq["personal_peq"], frequency, fs)


def float32_filters(filters):
    return [{"type_id": int(f["type_id"]), **{k: float(np.float32(f[k])) for k in ("gain", "fc", "q")}} for f in filters]


def pack_record(record):
    require(len(record["filters"]) <= 18, "Profile exceeds 18 stored biquads")
    return struct.pack("<ffI", record["gain0"], record["gain1"], len(record["filters"])) + b"".join(
        struct.pack("<Ifff", f["type_id"], f["gain"], f["fc"], f["q"]) for f in record["filters"]
    ) + b"\0" * (16 * (18 - len(record["filters"])))


def active_filters(rec):
    return [{k: s[k] for k in ("type_id", "gain", "fc", "q")} for s in rec["slots"] if s["active"]]


def error_metrics(error):
    return {"rms_db": float(np.sqrt(np.mean(error ** 2))), "max_abs_db": float(np.max(np.abs(error)))}


def fit_record(rec, eq, max_nfev=500):
    """Preserve HP/LP/AP parameters; fit the remaining slots to baseline + delta.

    Existing peak/shelf filters remain free to merge the correction. Fit only
    the audible contribution of each path: suppressed bands below -30 dB receive
    reduced weight, and that fact is made explicit in the validation report.
    """
    original = active_filters(rec)
    fixed = [f for f in original if f["type_id"] in (3, 4, 5)]
    variable = [f for f in original if f["type_id"] in (0, 1, 2)]
    # Use all available slots. This changes bank records only, not runtime capacity.
    available = 18 - len(fixed)
    extras = available - len(variable)
    centers = np.geomspace(35, 13000, max(extras, 1))
    variable += [{"type_id": 1, "gain": 0.0, "fc": float(fc), "q": 1.2} for fc in centers[:extras]]
    types = [f["type_id"] for f in variable]
    x0 = np.array([[f["gain"], np.log(f["fc"]), np.log(f["q"])] for f in variable]).ravel()
    lower = np.tile([-24, np.log(12), np.log(.2)], available)
    upper = np.tile([24, np.log(20500), np.log(14)], available)
    # Fit with a shared parameter set across three sample rates.
    freq = np.unique(np.concatenate([np.geomspace(20, 20000, 256), np.asarray(eq["graphic_points"])[:, 0]]))
    targets, weights, fixed_db = [], [], []
    for fs in SAMPLE_RATES:
        baseline = response(original, freq, fs)
        targets.append(baseline + correction(eq, freq, fs))
        weights.append(np.clip(10 ** ((baseline - np.max(baseline)) / 40), .035, 1))
        fixed_db.append(response(fixed, freq, fs))

    def decode(x):
        p = x.reshape(-1, 3)
        return [{"type_id": t, "gain": float(v[0]), "fc": float(np.exp(v[1])), "q": float(np.exp(v[2]))} for t, v in zip(types, p)]

    def residual(x):
        filters = decode(x)
        return np.concatenate([(response(filters, freq, fs) + fd - target) * w
                               for fs, fd, target, w in zip(SAMPLE_RATES, fixed_db, targets, weights)])

    fit = least_squares(residual, np.clip(x0, lower + 1e-8, upper - 1e-8), bounds=(lower, upper),
                        max_nfev=max_nfev, ftol=1e-7, xtol=1e-7, gtol=1e-7)
    result = float32_filters(fixed + decode(fit.x))
    dense = np.geomspace(20, 20000, 2048)
    metrics = {}
    for fs in SAMPLE_RATES:
        baseline = response(original, dense, fs)
        error = response(result, dense, fs) - baseline - correction(eq, dense, fs)
        audible = baseline >= np.max(baseline) - 30
        h0 = response(original, dense, fs, True)
        h1 = response(result, dense, fs, True)
        metrics[str(fs)] = {"all_20_20000_hz": error_metrics(error),
                            "path_within_30_db_of_peak": error_metrics(error[audible]),
                            "audible_frequency_min_hz": float(dense[audible][0]),
                            "audible_frequency_max_hz": float(dense[audible][-1]),
                            "phase_change_max_abs_deg": float(np.max(np.abs(np.unwrap(np.angle(h1 / h0))) * 180 / np.pi))}
    return {"gain0": rec["gain0"], "gain1": rec["gain1"], "filters": result,
            "fixed_filters": fixed, "metrics": metrics, "optimizer_nfev": fit.nfev,
            "optimizer_status": int(fit.status), "baseline_filter_count": len(original),
            "note": "Magnitude fit; dual-driver acoustic summation, actual codec rates, phase and on-device sound remain unverified."}


def make_plan(firmware, eq, destination, max_nfev=500, preamp_db=0):
    item = opkg.load(firmware)
    raw = item["raw"]
    p = opkg.profiles(raw)
    # Known code anchors must match, not just image length.
    expected = {8717764: (0x147c4c, "f5eec00a10b5f1ee10fa0c462ded048b"),
                8650680: (0x14a60c, "f5eec00a10b5f1ee10fa0c462ded048b")}
    at, anchor = expected[len(raw)]
    require(raw[at:at + 16].hex() == anchor, "Coefficient generator does not match the verified code")
    require(raw[0x30e78:0x30e7e].hex() == "30b57d4b83b0", "EQ selector does not match the verified code")
    # Fits are valid only relative to the studied official Dynaudio bank.
    known = json.loads((Path(__file__).parent / "mapping.json").read_text())
    require(opkg.sha(raw) in known["official_raw_sha256"].values(), "Raw image is not one of the two verified official images")
    require(opkg.sha(raw[p["bank_offset"]:p["bank_end_exclusive"]]) == known["official_bank_sha256"],
            "EQ bank differs from official 112/116; choose an unmodified official package")
    start = PRESETS[destination]["start"]
    cache, changes = {}, []
    for table in p["tables"]:
        for state in range(9):
            source = p["profiles"][table["profile_indices"][state]]
            target = p["profiles"][table["profile_indices"][start + state]]
            key = json.dumps(active_filters(source), sort_keys=True)
            if key not in cache:
                print(f"Fitting {table['name']} state {state} ...", file=sys.stderr, flush=True)
                cache[key] = fit_record(source, eq, max_nfev)
            record = copy.deepcopy(cache[key])
            record["gain0"] = float(np.float32(source["gain0"] + preamp_db))
            record["gain1"] = float(np.float32(source["gain1"] + preamp_db))
            changes.append({"table": table["name"], "state_position": state, "table_index": start + state,
                            "source_profile": source["profile_index"], "target_profile": target["profile_index"],
                            "raw_offset": target["raw_offset"], "before_sha256": target["record_sha256"],
                            "baseline_sha256": source["record_sha256"], "record": record})
    return {"format": "enco-x4-eq-plan-v1", "firmware_sha256": item["summary"]["file_sha256"],
            "raw_sha256": opkg.sha(raw), "raw_size": len(raw), "bank_offset": p["bank_offset"],
            "eq": eq, "baseline": "丹拿原声", "destination": destination, "destination_mapping": PRESETS[destination],
            "preamp_db": preamp_db, "records": changes,
            "limitations": ["Only verified official 112/116 bank is accepted.",
                            "Magnitude approximation, not bit-exact Wavelet or exact preservation of driver phase.",
                            "App label is unchanged. Calibration outside these bank records is retained.",
                            "Special slot 45 and fallback selection behavior are unchanged.",
                            "OPKG integrity is not proof of boot/OTA acceptance; no device test performed."]}


def validate_record(record):
    require(len(record["filters"]) <= 18, "Profile exceeds capacity")
    require(all(math.isfinite(record[k]) and -60 <= record[k] <= 0 for k in ("gain0", "gain1")), "Invalid overall gain")
    for f in record["filters"]:
        require(f["type_id"] in FILTER_TYPES and all(math.isfinite(f[k]) for k in ("gain", "fc", "q")), "Invalid filter")
        require(-60 <= f["gain"] <= 24 and 0 < f["fc"] <= 21000 and .1 <= f["q"] <= 20, "IIR values outside validated bounds")
    for fs in SAMPLE_RATES:
        for sos in coefficients(record["filters"], fs):
            require(np.max(np.abs(np.roots(sos[3:]))) < 1, "Unstable IIR")
            require(np.max(np.abs(sos)) < 15.9, "Coefficient exceeds observed hardware bounds")


def apply_plans(firmware, plans, output, max_rms=.45, max_error=1.5):
    """Repack reviewed plans; reject overlap, changed sources or poor fitting."""
    item = opkg.load(firmware)
    p = opkg.profiles(item["raw"])
    known = json.loads((Path(__file__).parent / "mapping.json").read_text())
    require(opkg.sha(item["raw"]) in known["official_raw_sha256"].values(), "Source must be a verified official image")
    by_offset = {r["raw_offset"]: r for r in p["profiles"]}
    edited = bytearray(item["raw"])
    selected = set()
    for plan in plans:
        require(plan["format"] == "enco-x4-eq-plan-v1" and plan["firmware_sha256"] == item["summary"]["file_sha256"], "Plan is for another firmware")
        require(plan["raw_sha256"] == opkg.sha(item["raw"]) and plan["raw_size"] == len(edited), "Plan raw image mismatch")
        require(plan["destination"] in PRESETS and len(plan["records"]) == 36, "Plan must contain all 9 states in all 4 tables")
        preamp = plan["preamp_db"]
        require(math.isfinite(preamp) and -24 <= preamp <= 0, "Invalid preamp")
        dest_start = PRESETS[plan["destination"]]["start"]
        table_map = {t["name"]: t["profile_indices"] for t in p["tables"]}
        seen_states = set()
        for c in plan["records"]:
            offset = c["raw_offset"]
            state = c["state_position"]
            require(c["table"] in table_map and 0 <= state <= 8, "Invalid table or state")
            require((c["table"], state) not in seen_states, "Duplicate table state")
            seen_states.add((c["table"], state))
            ids = table_map[c["table"]]
            source = p["profiles"][ids[state]]
            target = p["profiles"][ids[dest_start + state]]
            require(offset == target["raw_offset"] and c["source_profile"] == source["profile_index"], "Plan mapping mismatch")
            require(c["baseline_sha256"] == source["record_sha256"], "Baseline changed")
            require(offset in by_offset and offset not in selected, "Invalid or overlapping record")
            require(by_offset[offset]["record_sha256"] == c["before_sha256"], "Source record changed")
            rec = c["record"]
            validate_record(rec)
            for gain_key in ("gain0", "gain1"):
                require(abs(rec[gain_key] - float(np.float32(source[gain_key] + preamp))) < 1e-6, "Overall gain differs from baseline plus preamp")
            original = active_filters(source)
            protected = [f for f in original if f["type_id"] in (3, 4, 5)]
            actual_protected = [f for f in rec["filters"] if f["type_id"] in (3, 4, 5)]
            require(protected == actual_protected, "HP/LP/AP parameters changed")
            dense = np.geomspace(20, 20000, 2048)
            # Recompute, rather than trusting metrics embedded in an editable plan.
            for fs in SAMPLE_RATES:
                baseline = response(original, dense, fs)
                error = response(rec["filters"], dense, fs) - baseline - correction(plan["eq"], dense, fs)
                audible = baseline >= np.max(baseline) - 30
                m = error_metrics(error[audible])
                require(m["rms_db"] <= max_rms and m["max_abs_db"] <= max_error,
                        f"Fit fails quality gate at {c['table']} state {c['state_position']}: {m}")
            encoded = pack_record(rec)
            require(len(encoded) == 300, "Record size changed")
            edited[offset:offset + 300] = encoded
            selected.add(offset)
    require(selected, "Empty plan")
    # Verify every byte outside selected bank records remains identical.
    previous = 0
    for offset in sorted(selected):
        require(edited[previous:offset] == item["raw"][previous:offset], "Unexpected mutation outside target records")
        previous = offset + 300
    require(edited[previous:] == item["raw"][previous:], "Unexpected mutation after target records")
    opkg.profiles(bytes(edited))
    result, changed = opkg.repack(item, bytes(edited))
    out = Path(output)
    require(not out.exists(), "Output already exists; choose a new path")
    out.write_bytes(result)
    return {"output": str(out), "sha256": opkg.sha(result), "selected_record_count": len(selected),
            "changed_blocks": changed, "raw_length_unchanged": True, "outside_target_records_unchanged": True,
            "all_opkg_checks_pass": True, "on_device_test": False, "version_changed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("mapping", help="Show display names, protocol IDs, table positions and verified types")
    inspect = sub.add_parser("inspect", help="Parse a correction file; no firmware changes")
    inspect.add_argument("eq")
    plan = sub.add_parser("plan", help="Fit Dynaudio baseline plus correction to a destination preset")
    plan.add_argument("firmware"); plan.add_argument("eq"); plan.add_argument("output")
    plan.add_argument("--target", choices=PRESETS, required=True)
    plan.add_argument("--preamp-db", type=float, default=0)
    plan.add_argument("--max-nfev", type=int, default=500)
    apply = sub.add_parser("apply", help="Validate and repack one or more reviewed plans offline")
    apply.add_argument("firmware"); apply.add_argument("output"); apply.add_argument("plans", nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "mapping":
            result = json.loads((Path(__file__).parent / "mapping.json").read_text())
        elif args.command == "inspect":
            result = parse_eq(args.eq)
        elif args.command == "plan":
            require(not Path(args.output).exists(), "Output already exists")
            require(math.isfinite(args.preamp_db) and -24 <= args.preamp_db <= 0, "Preamp must be between -24 and 0 dB")
            result = make_plan(args.firmware, parse_eq(args.eq), args.target, args.max_nfev, args.preamp_db)
            Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            result = {"plan": args.output, "records": len(result["records"]), "destination": args.target,
                      "baseline": "丹拿原声", "on_device_test": False}
        else:
            result = apply_plans(args.firmware, [json.loads(Path(p).read_text()) for p in args.plans], args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, OSError, KeyError, struct.error) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
