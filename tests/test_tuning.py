import copy
import json

import numpy as np
import pytest

from heytap_eq import opkg
from heytap_eq.adapters import verified_bank
from heytap_eq.clipboard import copy_plan, decode_text, preset_payload, tuning_payload
from heytap_eq.configuration import config, enco_mapping, record_at
from heytap_eq.eq_formats import EQDocument, Filter
from heytap_eq.estimation import builtin_reference, estimate_difference, reference_snapshot
from heytap_eq.firmware_dsp import response
from heytap_eq.firmware_edit import active, apply_plans, make_plan
from heytap_eq.measurements import Measurement
from heytap_eq.session import Session
from tests.firmware_fixture import synthetic_firmware


def test_special_configuration_resolves_adapter_index_and_actual_pointers(monkeypatch, tmp_path):
    firmware = synthetic_firmware(monkeypatch, tmp_path)
    mapping = {"layout": copy.deepcopy(opkg.LAYOUTS[len(firmware.package["raw"])]), "configuration": enco_mapping()}
    special = mapping["configuration"]["presets"][-1]
    special.update(key="special:mapped", title="Mapped special", indices=[44])
    firmware.mapping = mapping
    firmware.profiles = verified_bank(firmware.package, mapping)
    plan = make_plan(firmware, EQDocument(filters=[Filter(1, 1200, 1, 1)]), "special:mapped")
    assert len(plan["records"]) == 4 and plan["baseline"] == "special:mapped"
    edited, ranges, _ = apply_plans(firmware, [plan])
    expected = {record_at(firmware.profiles, t["name"], "special:mapped")["raw_offset"] for t in firmware.profiles["tables"]}
    assert {low for low, _ in ranges} == expected
    for table in firmware.profiles["tables"]:
        untouched = firmware.profiles["profiles"][table["profile_indices"][45]]["raw_offset"]
        assert edited[untouched:untouched+300] == firmware.package["raw"][untouched:untouched+300]


def test_selected_baseline_and_complete_preset_copy(monkeypatch, tmp_path):
    firmware = synthetic_firmware(monkeypatch, tmp_path)
    plan = make_plan(firmware, EQDocument(filters=[Filter(1, 1100, 1, 1)]), "清亮高音", baseline="丹拿高解析")
    assert plan["baseline"] == "丹拿高解析"
    for change in plan["records"]:
        source = record_at(firmware.profiles, change["table"], "丹拿高解析", change["state"])
        assert change["baseline_sha256"] == source["record_sha256"]
    payload = preset_payload(firmware, "丹拿原声")
    assert len(payload["records"]) == 36 and "raw_offset" not in json.dumps(payload)
    copied = copy_plan(firmware, payload, "丹拿高解析")
    raw, _, _ = apply_plans(firmware, [copied])
    bank = opkg.profiles(bytes(raw))
    for table in firmware.profiles["tables"]:
        for state in range(9):
            source = record_at(firmware.profiles, table["name"], "丹拿原声", state)
            index = table["profile_indices"][config(firmware.profiles, "丹拿高解析")["indices"][state]]
            target = bank["profiles"][index]
            assert active(source) == active(target)
            assert (source["gain0"], source["gain1"]) == (target["gain0"], target["gain1"])


def test_common_complex_change_and_phase_sensitive_model_choice(monkeypatch, tmp_path):
    firmware = synthetic_firmware(monkeypatch, tmp_path)
    reference = reference_snapshot(firmware)
    peq = {"type_id": 1, "gain": 2., "fc": 2000., "q": 1.}
    for table in firmware.profiles["tables"]:
        r = record_at(firmware.profiles, table["name"], "丹拿原声")
        r["slots"][r["count"]] = peq.copy()
        r["count"] += 1
    frequency = np.geomspace(20, 20000, 1000)
    result = estimate_difference(firmware, reference, "丹拿原声", "丹拿原声", frequency)
    assert result["mode"] == "共同传递变化"
    np.testing.assert_allclose(result["delta"], response([peq], frequency), atol=1e-10)
    r = record_at(firmware.profiles, "other_output1", "丹拿原声")
    r["slots"][r["count"]] = {"type_id": 5, "gain": 0., "fc": 1500., "q": .7}
    r["count"] += 1
    result = estimate_difference(firmware, reference, "丹拿原声", "丹拿原声", frequency)
    assert "双单元近似" in result["mode"] and result["uncertain_band"]
    # Equal magnitude alone cannot establish a common complex transfer.
    np.testing.assert_allclose(result["branches"]["1"], result["branches"]["2"], atol=1e-10)


def test_gain_assumption_is_explicit_and_region_specific(monkeypatch, tmp_path):
    firmware = synthetic_firmware(monkeypatch, tmp_path)
    reference = reference_snapshot(firmware)
    for name in ("india_output1", "india_output2"):
        r = record_at(firmware.profiles, name, "丹拿原声")
        r["gain0"] += 4
        r["gain1"] += 4
    frequency = np.geomspace(20, 20000, 100)
    ignored = estimate_difference(firmware, reference, "丹拿原声", "丹拿原声", frequency, region="india")
    np.testing.assert_allclose(ignored["delta"], 0, atol=1e-10)
    assert "增益字段变化未折算" in ignored["mode"]
    assumed = estimate_difference(firmware, reference, "丹拿原声", "丹拿原声", frequency, region="india", gain_mode="gain0")
    np.testing.assert_allclose(assumed["delta"], 4, atol=1e-10)
    assert "假定" in assumed["mode"]


def test_lossless_tuning_clipboard_and_one_global_undo():
    source = Session()
    source.replace(EQDocument(raw=[[20, 2], [20000, -1]], filters=[Filter(9, 2000, -2, 2, enabled=False)]))
    source.set_curves([Measurement("Source", [20, 20000], [80, 90])],
                      [Measurement("Target", [20, 20000], [2, 0])], 0, 0)
    source.set_context({"reference_preset": "丹拿原声", "mapping": {"layout": "source address"}})
    payload = decode_text(json.dumps(tuning_payload(source)))
    assert "mapping" not in payload["state"]["context"]
    target = Session()
    target.set_metadata({"version_digits": "119"})
    before = target.snapshot()
    target.paste_tuning(payload["state"])
    assert target.document == source.document and target.measurements == source.measurements
    assert not target.document.filters[0].enabled
    target.undo()
    assert target.snapshot() == before
    target.redo()
    assert target.targets == source.targets and target.metadata_edits == {"version_digits": "119"}
    text = decode_text("GraphicEQ: 20 1; 20000 0")
    target.paste_tuning(text["state"])
    assert target.measurements == source.measurements


def test_builtin_reference_contains_both_outputs_regions_and_special():
    reference = builtin_reference()
    if reference is None:
        pytest.skip("Reference template publication awaits explicit approval; manual reference import is available")
    assert len(reference["presets"]) == 6
    special = reference["presets"][-1]
    assert special["special"] and len(special["records"]) == 4
    for preset in reference["presets"]:
        for row in preset["records"]:
            if row["region"] == "other":
                counterpart = next(r["record"] for r in preset["records"] if r["region"] == "india"
                                   and r["output"] == row["output"] and r["state"] == row["state"])
                assert row["record"]["filters"] == counterpart["filters"]
                assert counterpart["gain0"]-row["record"]["gain0"] == 4
                assert counterpart["gain1"]-row["record"]["gain1"] == 4
