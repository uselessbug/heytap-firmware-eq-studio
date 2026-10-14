"""Reference-relative DSP differences and an explicit two-driver power model."""

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from heytap_eq.clipboard import preset_payload
from heytap_eq.configuration import config, configurations, record_at, tables_for
from heytap_eq.firmware_dsp import response
from heytap_eq.firmware_edit import active


def builtin_reference():
    path = Path(__file__).with_name("data").joinpath("enco-x4-reference.json")
    if not path.exists():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    filters = value.pop("filter_bank")
    for preset in value["presets"]:
        for row in preset["records"]:
            record = row["record"]
            record["filters"] = [dict(zip(("type_id", "gain", "fc", "q"), f)) for f in filters[record.pop("filter_index")]]
    return value


def measurement_key(measurement):
    return hashlib.sha256(json.dumps(asdict(measurement), sort_keys=True, allow_nan=False).encode()).hexdigest()


def reference_snapshot(firmware):
    return {"schema": "heytap-reference-v1", "title": Path(firmware.path).name,
            "product_id": firmware.package["summary"]["product_id"], "sha256": firmware.sha256,
            "presets": [preset_payload(firmware, p["key"]) | {"key": p["key"]} for p in configurations(firmware.profiles)]}


def estimate_difference(firmware, reference, current_key, reference_key, frequency, region="other",
                        state=0, rate=48000, crossover=None, gain_mode="none", plans=(), reference_state=None):
    bank = firmware.profiles
    if reference.get("product_id") != firmware.package["summary"]["product_id"]:
        raise ValueError("参考固件与当前固件的机型不同，请重新绑定测量参考")
    config(bank, current_key)
    ref = next((p for p in reference["presets"] if p["key"] == reference_key), None)
    if ref is None:
        raise ValueError("参考固件没有所选配置")
    roles = tables_for(bank, region)
    plan = next((p for p in plans if p["destination"] == current_key), None)
    ratios, differences, highpasses, gain_changed = [], {}, [], False
    for role in sorted(roles, key=lambda r: r["output"]):
        current = record_at(bank, role["name"], current_key, state)
        current = {"filters": active(current), "gain0": current["gain0"], "gain1": current["gain1"]}
        if plan:
            current = next(c["record"] for c in plan["records"] if c["table"] == role["name"] and c["state"] == state)
        candidates = [r for r in ref["records"] if r["region"] == region and r["output"] == role["output"]]
        ref_state = 0 if ref.get("special") else (state if reference_state is None else reference_state)
        source = next((r["record"] for r in candidates if r["state"] == ref_state), None)
        if source is None:
            raise ValueError("参考配置缺少对应区域／输出／状态")
        h0, h1 = response(source["filters"], frequency, rate, True), response(current["filters"], frequency, rate, True)
        valid = np.abs(h0) >= 1e-12
        ratio = np.divide(h1, h0, out=np.ones_like(h1), where=valid)
        gain_changed |= any(abs(current[g]-source[g]) > 1e-6 for g in ("gain0", "gain1"))
        if gain_mode in ("gain0", "gain1"):
            ratio *= 10**((current[gain_mode]-source[gain_mode])/20)
        delta = 20*np.log10(np.maximum(np.abs(ratio), 1e-30))
        differences[role["output"]] = delta
        ratios.append(ratio)
        highpasses += [f["fc"] for f in source["filters"] if f["type_id"] == 4 and f["fc"] > 1000]
    if not ratios:
        raise ValueError("没有可比较的数字输出")
    common = all(np.allclose(r, ratios[0], rtol=1e-5, atol=1e-7) for r in ratios[1:])
    if common:
        delta = next(iter(differences.values()))
        mode, band = "共同传递变化", None
    elif len(ratios) == 2:
        crossover = float(crossover or (min(highpasses) if highpasses else 14000))
        # A complementary power weighting is an assumption, not an acoustic reconstruction.
        weight2 = 1/(1+(crossover/np.asarray(frequency))**8)
        power = (1-weight2)*np.abs(ratios[0])**2 + weight2*np.abs(ratios[1])**2
        delta = 10*np.log10(np.maximum(power, 1e-30))
        mode, band = "双单元近似 · 功率权重，忽略相干干涉", [crossover/1.4, crossover*1.4]
    else:
        raise ValueError("不同输出超过两路，请提供对应声学模型")
    suffix = "；增益字段变化未折算" if gain_changed and gain_mode == "none" else ""
    if gain_mode != "none":
        suffix += f"；整体增益假定按 {gain_mode}"
    return {"delta": delta, "branches": differences, "mode": mode+suffix, "uncertain_band": band}
