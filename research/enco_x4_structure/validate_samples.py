#!/usr/bin/env python3
"""Reproduce integrity, byte-exact roundtrip and isolated-edit checks.

Usage: python validate_samples.py ORIGINAL_112 ORIGINAL_116 THIRD_113 THIRD_101
Inputs are read only. Synthetic edits exist in memory only.
"""
import argparse
import hashlib
import json
import struct

import opkg_tool as tool


def rejected(data, expected):
    try:
        tool.parse(bytes(data))
    except tool.FormatError as exc:
        assert expected in str(exc), str(exc)
    else:
        raise AssertionError(f"Corruption accepted: {expected}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("samples", nargs=4)
    args = parser.parse_args()
    items = [tool.load(p) for p in args.samples]
    for p, item in zip(args.samples, items):
        packed, changed = tool.repack(item, item["raw"])
        assert packed == item["data"] and changed == []
        assert tool.profiles(item["raw"])["profile_count"] == 184
        print(f"PASS integrity / byte-exact roundtrip / EQ pointers: {p}")
    a, b = tool.profiles(items[0]["raw"]), tool.profiles(items[1]["raw"])
    assert items[0]["raw"][a["bank_offset"]:a["bank_end_exclusive"]] == items[1]["raw"][b["bank_offset"]:b["bank_end_exclusive"]]
    assert all(x["profile_indices"] == y["profile_indices"] for x, y in zip(a["tables"], b["tables"]))
    assert tool.compare(items[0], items[2])["raw_changed_bytes"] == 20898
    assert tool.compare(items[0], items[3])["raw_changed_bytes"] == 2455
    original = items[0]
    edited = bytearray(original["raw"])
    struct.pack_into("<f", edited, 0x735768, 0.2)
    rebuilt, changed = tool.repack(original, bytes(edited))
    assert changed == [29]
    parsed = tool.parse(rebuilt)
    assert parsed["raw"] == edited
    assert all(x["bytes"] == y["bytes"] for x, y in zip(original["blocks"], parsed["blocks"]) if x["index"] != 29)
    for offset, message in [(-4, "CRC32"), (136, "Raw SHA-256"), (172, "Compressed SHA-256")]:
        corrupted = bytearray(original["data"])
        corrupted[offset] ^= 1
        corrupted[10:42] = hashlib.sha256(corrupted[42:]).digest()
        rejected(corrupted, message)
    corrupted = bytearray(original["data"])
    corrupted[10] ^= 1
    rejected(corrupted, "Package SHA-256")
    print("PASS relocated EQ bank equality / known diffs / isolated EQ edit / corruption rejection")
    print(json.dumps({"samples": 4, "blocks": sum(len(x["blocks"]) for x in items), "device_flash_test": False}))


if __name__ == "__main__":
    main()
