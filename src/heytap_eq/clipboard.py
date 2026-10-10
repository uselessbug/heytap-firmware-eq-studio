"""Portable tuning values; firmware addresses are resolved at the destination."""

import copy
import json

import numpy as np

from heytap_eq import opkg
from heytap_eq.configuration import config, record_at
from heytap_eq.eq_formats import EQDocument, parse_text
from heytap_eq.firmware_edit import SCHEMA, active, metrics, quantize, validate_record

MIME = "application/x-heytap-tuning+json"
TUNING_SCHEMA = "heytap-tuning-v1"
PRESET_SCHEMA = "heytap-preset-v1"


def tuning_payload(session):
    state = session.tuning_state()
    state["context"].pop("mapping", None)
    return {"schema": TUNING_SCHEMA, "state": state}


def decode_text(text):
    text = text.strip()
    if text.startswith("{"):
        value = json.loads(text)
        opkg.require(value.get("schema") in (TUNING_SCHEMA, PRESET_SCHEMA), "Unknown clipboard format")
        return value
    return {"schema": TUNING_SCHEMA, "state": {"eq": parse_text(text).to_dict()}}


def preset_payload(firmware, key, plans=()):
    bank = firmware.profiles
    preset = config(bank, key)
    plan = next((p for p in plans if p["destination"] == key), None)
    records = []
    for role in bank["configuration"]["tables"]:
        for state in range(len(preset["indices"])):
            source = record_at(bank, role["name"], key, state)
            record = {"filters": active(source), "gain0": source["gain0"], "gain1": source["gain1"]}
            if plan:
                record = next(c["record"] for c in plan["records"] if c["table"] == role["name"] and c["state"] == state)
            records.append({"region": role["region"], "output": role["output"], "state": state,
                            "record": {k: copy.deepcopy(record[k]) for k in ("filters", "gain0", "gain1")}})
    return {"schema": PRESET_SCHEMA, "title": preset["title"], "special": bool(preset.get("special")),
            "states": [] if preset.get("special") else bank["configuration"]["states"], "records": records}


def copy_plan(firmware, payload, destination):
    opkg.require(payload.get("schema") == PRESET_SCHEMA, "Clipboard is not a firmware preset")
    bank = firmware.profiles
    target_config = config(bank, destination)
    opkg.require(bool(target_config.get("special")) == bool(payload.get("special")), "Different special/ordinary coverage")
    opkg.require(target_config.get("special") or payload["states"] == bank["configuration"]["states"],
                 "State mapping differs; use a correction EQ and refit for this firmware")
    sources = {(r["region"], r["output"], r["state"]): r["record"] for r in payload["records"]}
    changes = []
    for role in bank["configuration"]["tables"]:
        for state in range(len(target_config["indices"])):
            key = (role["region"], role["output"], state)
            opkg.require(key in sources, "Clipboard lacks a destination output/region/state")
            reference = copy.deepcopy(sources[key])
            validate_record(reference)
            reference["filters"] = quantize(reference["filters"])
            for gain in ("gain0", "gain1"):
                reference[gain] = float(np.float32(reference[gain]))
            target = record_at(bank, role["name"], destination, state)
            record = {**reference, "filters": quantize(reference["filters"])}
            record["metrics"] = metrics(reference["filters"], record["filters"], EQDocument())
            changes.append({"table": role["name"], "state": state, "raw_offset": target["raw_offset"],
                            "before_sha256": target["record_sha256"], "baseline_sha256": target["record_sha256"],
                            "reference": reference, "record": record})
    return {"schema": SCHEMA, "operation": "copy", "baseline": destination, "destination": destination,
            "firmware_sha256": firmware.sha256, "raw_sha256": opkg.sha(firmware.package["raw"]),
            "preamp_db": 0., "eq": EQDocument(name=payload.get("title", "Copied preset")).to_dict(), "records": changes}
