import copy
import json
import threading

import numpy as np
import pytest

from heytap_eq import metadata, opkg
from heytap_eq.adapters import inspect_firmware
from heytap_eq.eq_formats import EQDocument, Filter
from heytap_eq.firmware_edit import apply_plans, export_firmware, fit_record, make_plan
from tests.firmware_fixture import synthetic_firmware


def test_whole_preset_export_and_reopen(monkeypatch, tmp_path):
    firmware = synthetic_firmware(monkeypatch, tmp_path)
    original = firmware.package["data"]
    doc = EQDocument(filters=[Filter(9, 1800., -2., 1.2)])
    plan = make_plan(firmware, doc, "丹拿高解析")
    # A saved plan is portable; application validates the serialized snapshot again.
    plan = json.loads(json.dumps(plan))
    assert len(plan["records"]) == 36
    assert all(r["record"]["optimizer_nfev"] == 0 for r in plan["records"])
    output = tmp_path/"edited.bin"
    report = export_firmware(firmware, [plan], {}, output)
    reopened = inspect_firmware(output)
    assert reopened.profiles and report["changed_records"] == 36
    assert all(report["checks"].values())
    assert firmware.package["data"] == original and firmware.path != str(output)
    before = firmware.profiles["profiles"]
    after = reopened.profiles["profiles"]
    changed = {a["profile_index"] for a, b in zip(before, after) if a["record_sha256"] != b["record_sha256"]}
    expected = {i for t in firmware.profiles["tables"] for i in t["profile_indices"][36:45]}
    assert changed == expected
    for row in report["records"]:
        assert max(v["max_db"] for v in row["metrics"].values()) < 1e-4
    with pytest.raises(ValueError, match="Output already exists"):
        export_firmware(firmware, [plan], {}, output)
    with pytest.raises(ValueError, match="new output path"):
        export_firmware(firmware, [plan], {}, firmware.path)


def test_plans_reject_overlap_forged_metrics_protection_and_binding(monkeypatch, tmp_path):
    firmware = synthetic_firmware(monkeypatch, tmp_path)
    plan = make_plan(firmware, EQDocument(filters=[Filter(1, 1000., 2., 1.)]), "清亮高音")
    with pytest.raises(ValueError, match="overlapping"):
        apply_plans(firmware, [plan, plan])
    broken = copy.deepcopy(plan)
    broken["records"][0]["record"]["filters"][0]["fc"] = 40.
    with pytest.raises(ValueError, match="HP/LP/AP"):
        apply_plans(firmware, [broken])
    broken = copy.deepcopy(plan)
    broken["records"][0]["record"]["filters"][-1]["gain"] = -20.
    broken["records"][0]["record"]["metrics"] = {}
    with pytest.raises(ValueError, match="Fit exceeds"):
        apply_plans(firmware, [broken])
    broken = copy.deepcopy(plan)
    broken["firmware_sha256"] = "0"*64
    with pytest.raises(ValueError, match="another firmware"):
        apply_plans(firmware, [broken])
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(InterruptedError):
        make_plan(firmware, EQDocument(), "清亮高音", cancelled=cancelled)


def test_raw_optimizer_and_cancellation(monkeypatch, tmp_path):
    from heytap_eq.dsp import correction
    firmware = synthetic_firmware(monkeypatch, tmp_path)
    grid = np.geomspace(20, 20000, 127)
    doc = EQDocument(filters=[Filter(1, 1000., 1., 1.)])
    raw_doc = EQDocument(raw=[[float(f), float(g)] for f, g in zip(grid, correction(doc, grid))])
    source = firmware.profiles["profiles"][0]
    record = fit_record(source, raw_doc, max_nfev=35)
    assert record["optimizer_nfev"] > 0
    assert max(m["rms_db"] for m in record["metrics"].values()) < .1


def test_metadata_and_version_synchronization(monkeypatch, tmp_path):
    firmware = synthetic_firmware(monkeypatch, tmp_path)
    values = metadata.fields(firmware.package)
    revision = next(f for f in values if f.get("key") == "REV_INFO")
    edits = {"version_digits": "1.2.7", "section_name": "edited.bin", revision["id"]: "custom"}
    report = export_firmware(firmware, [], edits, tmp_path/"version.bin")
    reopened = inspect_firmware(report["output"])
    assert reopened.profiles
    assert reopened.package["summary"]["version_digits"] == "127"
    assert reopened.package["summary"]["section_name"] == "edited.bin"
    assert reopened.package["summary"]["embedded_build_metadata"][0]["fields"]["SW_VER"] == "127"
    assert reopened.package["raw"][0x200:0x20c] == metadata.version_patch("127")
    # Modified versions stay recognizable and can be edited a second time.
    export_firmware(reopened, [], {"version_digits": "128"}, tmp_path/"version2.bin")
    with pytest.raises(ValueError, match="exceeds"):
        export_firmware(firmware, [], {revision["id"]: "X"*100}, tmp_path/"bad.bin")
    with pytest.raises(ValueError, match="Unknown metadata"):
        export_firmware(firmware, [], {"payload_offset": "0"}, tmp_path/"bad.bin")
    assert not (tmp_path/"bad.bin").exists()


def test_thumb_getter_all_versions_and_alignment():
    from capstone import CS_ARCH_ARM, CS_MODE_MCLASS, CS_MODE_THUMB, Cs
    from unicorn import UC_ARCH_ARM, UC_MODE_MCLASS, UC_MODE_THUMB, Uc
    from unicorn.arm_const import (
        UC_CPU_ARM_CORTEX_M4,
        UC_ARM_REG_LR,
        UC_ARM_REG_R0,
        UC_ARM_REG_R1,
        UC_ARM_REG_R4,
        UC_ARM_REG_SP,
    )
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    u.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M4)
    u.mem_map(0x10000000, 0x1000)
    u.mem_map(0x20000000, 0x2000)
    disasm = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    for number in range(1000):
        version = f"{number:03d}"
        code = metadata.version_patch(version)
        assert [i.mnemonic for i in disasm.disasm(code, 0x10000000)] == ["movw", "strh", "movs", "strb", "bx"]
        u.mem_write(0x10000000, code)
        # Unicorn caches translated blocks at this address; evict each changed function.
        u.ctl_remove_cache(0x10000000, 0x1000000c)
        for alignment in (0, 1):
            pointer = 0x20000104+alignment
            u.mem_write(0x20000100, b"\xa5"*16)
            for register, value in ((UC_ARM_REG_R0, pointer), (UC_ARM_REG_R1, 0x13579bdf),
                                    (UC_ARM_REG_R4, 0x2468ace0), (UC_ARM_REG_LR, 0x20001001),
                                    (UC_ARM_REG_SP, 0x20001ff0)):
                u.reg_write(register, value)
            u.emu_start(0x10000001, 0x20001000, count=20)
            expected = bytearray(b"\xa5"*16)
            expected[pointer-0x20000100:pointer-0x20000100+3] = bytes(map(int, version))
            assert bytes(u.mem_read(0x20000100, 16)) == bytes(expected)
            assert u.reg_read(UC_ARM_REG_R0) == pointer
            assert u.reg_read(UC_ARM_REG_R1) == 0x13579bdf
            assert u.reg_read(UC_ARM_REG_R4) == 0x2468ace0
