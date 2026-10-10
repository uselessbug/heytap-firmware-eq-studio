"""Fit whole presets, independently validate saved plans, and export new OPKG files."""

import copy
import json
import math
import os
import re
import struct
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

from heytap_eq import metadata, opkg
from heytap_eq.adapters import PRESETS, verified_bank
from heytap_eq.configuration import config, record_at
from heytap_eq.dsp import FIRMWARE_KIND, SAMPLE_RATES, correction
from heytap_eq.eq_formats import EQDocument
from heytap_eq.firmware_dsp import coefficients, response

SCHEMA = "heytap-firmware-plan-v2"
FREQUENCY = np.geomspace(20, 20000, 1024)


def check_cancel(cancelled):
    if cancelled is not None and cancelled.is_set():
        raise InterruptedError("Firmware operation cancelled")


def active(record):
    return [{k: f[k] for k in ("type_id", "gain", "fc", "q")}
            for f in record["slots"][:record["count"]]]


def quantize(filters):
    return [{"type_id": int(f["type_id"]), **{k: float(np.float32(f[k]))
            for k in ("gain", "fc", "q")}} for f in filters]


def metrics(original, filters, doc):
    result = {}
    for rate in SAMPLE_RATES:
        baseline = response(original, FREQUENCY, rate)
        error = response(filters, FREQUENCY, rate)-baseline-correction(doc, FREQUENCY, rate)
        audible = baseline >= np.max(baseline)-30
        result[str(rate)] = {
            "rms_db": float(np.sqrt(np.mean(error[audible]**2))),
            "max_db": float(np.max(np.abs(error[audible]))),
            "full_band_rms_db": float(np.sqrt(np.mean(error**2))),
            "audible_min_hz": float(FREQUENCY[audible][0]),
            "audible_max_hz": float(FREQUENCY[audible][-1]),
        }
    return result


def validate_record(record, cache=None):
    filters = record["filters"]
    opkg.require(isinstance(filters, list) and len(filters) <= opkg.PROFILE_CAPACITY,
                 "Profile exceeds 18 filter slots")
    opkg.require(all(math.isfinite(record[k]) and -60 <= record[k] <= 1
                     for k in ("gain0", "gain1")), "Overall gain outside known bounds")
    for f in filters:
        opkg.require(type(f["type_id"]) is int and f["type_id"] in range(6), "Unknown firmware filter")
        opkg.require(all(math.isfinite(f[k]) for k in ("gain", "fc", "q"))
                     and -60 <= f["gain"] <= 24 and 0 < f["fc"] <= 21000
                     and .01 <= f["q"] <= 100, "Invalid firmware filter parameters")
    key = tuple((f["type_id"], f["gain"], f["fc"], f["q"]) for f in filters)
    if cache is not None and key in cache:
        return
    for rate in SAMPLE_RATES:
        for row in coefficients(filters, rate):
            opkg.require(np.max(np.abs(np.roots(row[3:]))) < 1, "Unstable firmware filter")
            opkg.require(np.max(np.abs(row)) < 15.9, "Firmware coefficient exceeds hardware bounds")
    if cache is not None:
        cache.add(key)


def pack_record(record, cache=None):
    validate_record(record, cache)
    filters = record["filters"]
    return (struct.pack("<ffI", record["gain0"], record["gain1"], len(filters))
            + b"".join(struct.pack("<Ifff", f["type_id"], f["gain"], f["fc"], f["q"])
                       for f in filters) + b"\0"*(16*(18-len(filters))))


def fit_record(source, doc, cancelled=None, max_nfev=300):
    check_cancel(cancelled)
    original = active(source)
    fixed = [f for f in original if f["type_id"] in (3, 4, 5)]
    variable = [f for f in original if f["type_id"] in (0, 1, 2)]
    enabled = [f for f in doc.filters if f.enabled]
    raw_neutral = not doc.raw or all(abs(p[1]) < 1e-12 for p in doc.raw)
    # Cascading a representable PEQ is exact and avoids unnecessary optimization.
    if (raw_neutral and all(f.kind in ("PEAK", "LS", "HS") for f in enabled)
            and len(original)+len(enabled) <= 18):
        fitted = quantize(original+[{"type_id": FIRMWARE_KIND[f.kind], "gain": f.gain,
                                   "fc": f.frequency, "q": f.q} for f in enabled])
        record = {"gain0": source["gain0"], "gain1": source["gain1"], "filters": fitted}
        validate_record(record)
        return {**record, "metrics": metrics(original, fitted, doc), "optimizer_nfev": 0}
    count = 18-len(fixed)
    opkg.require(count > 0, "Baseline has no available magnitude-filter slots")
    extras = count-len(variable)
    variable += [{"type_id": 1, "gain": 0., "fc": float(f), "q": 1.2}
                 for f in np.geomspace(35, 13000, max(1, extras))[:extras]]
    kinds = [f["type_id"] for f in variable]
    lower = np.tile([-24, np.log(12), np.log(.2)], count)
    upper = np.tile([24, np.log(20500), np.log(14)], count)
    initial = np.array([[f["gain"], np.log(f["fc"]), np.log(f["q"])] for f in variable]).ravel()
    grid = np.geomspace(20, 20000, 256)
    if doc.raw:
        grid = np.unique(np.concatenate([grid, np.asarray(doc.raw)[:, 0]]))
    desired, weights, fixed_db = [], [], []
    for rate in SAMPLE_RATES:
        baseline = response(original, grid, rate)
        desired.append(baseline+correction(doc, grid, rate))
        weights.append(np.clip(10**((baseline-np.max(baseline))/40), .035, 1))
        fixed_db.append(response(fixed, grid, rate))

    def decode(values):
        return [{"type_id": kind, "gain": float(p[0]), "fc": float(np.exp(p[1])),
                 "q": float(np.exp(p[2]))} for kind, p in zip(kinds, values.reshape(-1, 3))]

    def residual(values):
        check_cancel(cancelled)
        filters = decode(values)
        return np.concatenate([(response(filters, grid, rate)+fd-target)*weight
                               for rate, fd, target, weight in
                               zip(SAMPLE_RATES, fixed_db, desired, weights)])

    fit = least_squares(residual, np.clip(initial, lower+1e-8, upper-1e-8),
                        bounds=(lower, upper), max_nfev=max_nfev,
                        ftol=1e-7, xtol=1e-7, gtol=1e-7)
    check_cancel(cancelled)
    fitted = quantize(fixed+decode(fit.x))
    record = {"gain0": source["gain0"], "gain1": source["gain1"], "filters": fitted}
    validate_record(record)
    return {**record, "metrics": metrics(original, fitted, doc), "optimizer_nfev": int(fit.nfev)}


def plan_shape(plan):
    opkg.require(isinstance(plan, dict) and plan.get("schema") in (SCHEMA, "heytap-firmware-plan-v1"),
                 "Unsupported firmware plan")
    opkg.require(isinstance(plan.get("destination"), str) and isinstance(plan.get("records"), list)
                 and 0 < len(plan["records"]) <= 4096, "Invalid plan coverage")
    if plan["schema"] == "heytap-firmware-plan-v1":
        opkg.require(plan["destination"] in PRESETS and len(plan["records"]) == 36, "Invalid legacy plan")
    opkg.require(plan.get("operation", "fit") in ("fit", "copy"), "Unknown plan operation")
    opkg.require(isinstance(plan.get("firmware_sha256"), str)
                 and bool(re.fullmatch(r"[0-9a-f]{64}", plan["firmware_sha256"])),
                 "Invalid plan firmware SHA-256")
    opkg.require(math.isfinite(plan["preamp_db"]) and -24 <= plan["preamp_db"] <= 0,
                 "Preamp must be -24..0 dB")
    doc = EQDocument.from_dict(plan["eq"])
    cache = set()
    for change in plan["records"]:
        opkg.require(isinstance(change, dict) and type(change.get("state")) is int
                     and 0 <= change["state"] < 1024, "Invalid planned internal state")
        validate_record(change["record"], cache)
    return doc


def make_plan(firmware, doc, destination, preamp_db=0., cancelled=None, progress=None,
              max_nfev=300, baseline=None):
    doc = EQDocument.from_dict(doc.to_dict())
    bank = verified_bank(firmware.package, firmware.mapping)
    opkg.require(bank is not None, "Firmware code and table semantics are not verified")
    destination_config = config(bank, destination)
    baseline = baseline or (destination if destination_config.get("special") else "丹拿原声")
    baseline_config = config(bank, baseline)
    opkg.require(len(baseline_config["indices"]) == len(destination_config["indices"]),
                 "Baseline and destination have different state coverage")
    opkg.require(math.isfinite(preamp_db) and -24 <= preamp_db <= 0, "Preamp must be -24..0 dB")
    cache, changes = {}, []
    for table in bank["tables"]:
        for state in range(len(destination_config["indices"])):
            check_cancel(cancelled)
            if progress:
                progress(f"拟合 {destination_config['title']} · {table['name']} · {state+1}/{len(destination_config['indices'])}")
            source = record_at(bank, table["name"], baseline, state)
            target = record_at(bank, table["name"], destination, state)
            key = json.dumps(active(source), sort_keys=True)
            if key not in cache:
                cache[key] = fit_record(source, doc, cancelled, max_nfev)
            record = copy.deepcopy(cache[key])
            for gain in ("gain0", "gain1"):
                record[gain] = float(np.float32(source[gain]+preamp_db))
            validate_record(record)
            changes.append({"table": table["name"], "state": state,
                            "raw_offset": target["raw_offset"],
                            "before_sha256": target["record_sha256"],
                            "baseline_sha256": source["record_sha256"], "record": record})
    return {"schema": SCHEMA, "firmware_sha256": firmware.sha256,
            "raw_sha256": opkg.sha(firmware.package["raw"]), "baseline": baseline, "operation": "fit",
            "destination": destination, "preamp_db": preamp_db, "eq": doc.to_dict(), "records": changes}


def apply_plans(firmware, plans, cancelled=None, max_rms=.45, max_error=1.5):
    item = firmware.package
    bank = verified_bank(item, firmware.mapping)
    opkg.require(bank is not None, "Firmware code and table semantics are not verified")
    edited, ranges, reports = bytearray(item["raw"]), [], []
    selected = set()
    coefficient_cache, metric_cache = set(), {}
    tables = {t["name"]: t["profile_indices"] for t in bank["tables"]}
    for plan in plans:
        check_cancel(cancelled)
        doc = plan_shape(plan)
        target_config = config(bank, plan["destination"])
        expected = {(t["name"], state) for t in bank["tables"] for state in range(len(target_config["indices"]))}
        opkg.require(len(plan["records"]) == len(expected), "Plan does not cover the complete configuration")
        opkg.require(plan["firmware_sha256"] == firmware.sha256
                     and plan["raw_sha256"] == opkg.sha(item["raw"]), "Plan belongs to another firmware")
        seen = set()
        for change in plan["records"]:
            check_cancel(cancelled)
            name, state = change["table"], change["state"]
            opkg.require(name in tables and (name, state) not in seen, "Invalid or duplicate path/state")
            seen.add((name, state))
            opkg.require((name, state) in expected, "State is outside configuration")
            source = record_at(bank, name, plan.get("baseline", "丹拿原声"), state)
            target = record_at(bank, name, plan["destination"], state)
            offset = target["raw_offset"]
            opkg.require(change["raw_offset"] == offset and offset not in selected,
                         "Invalid or overlapping target records")
            opkg.require(change["before_sha256"] == target["record_sha256"]
                         and change["baseline_sha256"] == source["record_sha256"], "Plan records have changed")
            # Validate the float32 values actually written, not editable report metrics.
            record = copy.deepcopy(change["record"])
            record["filters"] = quantize(record["filters"])
            validate_record(record, coefficient_cache)
            copying = plan.get("operation") == "copy"
            reference = change.get("reference") if copying else source
            if copying:
                validate_record(reference, coefficient_cache)
            for gain in ("gain0", "gain1"):
                opkg.require(abs(record[gain]-float(np.float32(reference[gain]+plan["preamp_db"]))) < 1e-6,
                             "Overall gain differs from baseline plus preamp")
            baseline_filters = reference["filters"] if copying else active(source)
            protected = [f for f in baseline_filters if f["type_id"] in (3, 4, 5)]
            opkg.require([f for f in record["filters"] if f["type_id"] in (3, 4, 5)] == protected,
                         "Baseline HP/LP/AP parameters changed")
            metric_key = json.dumps([baseline_filters, record["filters"], plan["eq"]], sort_keys=True)
            if metric_key not in metric_cache:
                metric_cache[metric_key] = metrics(baseline_filters, record["filters"], doc)
            actual_metrics = metric_cache[metric_key]
            opkg.require(all(m["rms_db"] <= max_rms and m["max_db"] <= max_error
                             for m in actual_metrics.values()),
                         f"Fit exceeds RMS {max_rms} / max {max_error} dB at {name}, state {state}: {actual_metrics}")
            edited[offset:offset+300] = pack_record(record, coefficient_cache)
            selected.add(offset)
            ranges.append((offset, offset+300))
            reports.append({"preset": plan["destination"], "path": name, "state": state,
                            "raw_offset": offset, "metrics": actual_metrics})
    return edited, ranges, reports


def outside_ranges_unchanged(before, after, ranges):
    previous = 0
    for low, high in sorted(ranges):
        opkg.require(low >= previous and high <= len(before), "Invalid or overlapping write ranges")
        opkg.require(before[previous:low] == after[previous:low], "Bytes outside edited fields changed")
        previous = high
    opkg.require(before[previous:] == after[previous:], "Bytes after edited fields changed")


def export_firmware(firmware, plans, edits, output, cancelled=None, max_rms=.45, max_error=1.5):
    check_cancel(cancelled)
    opkg.require(math.isfinite(max_rms) and math.isfinite(max_error)
                 and 0 < max_rms <= max_error, "Invalid export error limits")
    path = Path(output)
    opkg.require(path.resolve() != Path(firmware.path).resolve(), "Choose a new output path")
    opkg.require(not path.exists(), "Output already exists; choose a new path")
    opkg.require(opkg.sha(Path(firmware.path).read_bytes()) == firmware.sha256, "Input file has changed")
    opkg.require(plans or edits, "No firmware changes prepared")
    raw, ranges, reports = apply_plans(firmware, plans, cancelled, max_rms, max_error)
    ranges += metadata.apply_raw(firmware.package, raw, edits)
    outside_ranges_unchanged(firmware.package["raw"], raw, ranges)
    opkg.profiles(bytes(raw), firmware.mapping["layout"] if firmware.mapping else None)
    packed, blocks = opkg.repack(firmware.package, bytes(raw), cancelled)
    packed = metadata.apply_header(firmware.package, packed, edits)
    verified = opkg.parse(packed)
    opkg.require(verified["raw"] == bytes(raw), "Exported raw data differs from the validated edits")
    check_cancel(cancelled)
    opkg.require(opkg.sha(Path(firmware.path).read_bytes()) == firmware.sha256, "Input file changed during export")
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(packed)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise
    return {"output": str(path), "sha256": opkg.sha(packed), "source_sha256": firmware.sha256,
            "presets": [p["destination"] for p in plans], "changed_records": len(reports),
            "changed_blocks": blocks, "metadata_edits": edits, "checks": verified["summary"]["checks"],
            "outside_permitted_raw_ranges_unchanged": True, "on_device_test": False,
            "error_limits": {"rms_db": max_rms, "max_db": max_error},
            "records": reports}
