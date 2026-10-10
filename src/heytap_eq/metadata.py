"""Bounded container/text edits and the rechecked Enco X4 Thumb version getter."""

import re
import struct

from heytap_eq import opkg

GETTERS = {
    8717764: (0xa5958, bytes.fromhex("012302220370437082707047")),
    8650680: (0xa6bc8, bytes.fromhex("012306220370437082707047")),
}


def version_digits(value):
    opkg.require(isinstance(value, str), "Version must be three decimal digits")
    value = value.replace(".", "")
    opkg.require(bool(re.fullmatch(r"[0-9]{3}", value)), "Version must be 000..999 or x.y.z")
    return value


def version_patch(value):
    major, minor, patch = map(int, version_digits(value))
    immediate = major | (minor << 8)
    # MOVW r3, #imm16; STRH r3, [r0]; MOVS r3, #patch; STRB r3, [r0,#2]; BX lr.
    first = 0xf240 | (((immediate >> 11) & 1) << 10) | (immediate >> 12)
    second = (((immediate >> 8) & 7) << 12) | 0x0300 | (immediate & 255)
    return struct.pack("<6H", first, second, 0x8003, 0x2300 | patch, 0x7083, 0x4770)


def getter_offset(item):
    descriptor = GETTERS.get(len(item["raw"]))
    if not descriptor:
        return None
    offset, original = descriptor
    actual = item["raw"][offset:offset+12]
    version = item["summary"]["version_digits"]
    if actual == original:
        expected = "112" if original[2] == 2 else "116"
        return offset if version == expected else None
    if len(version) == 3 and version.isdecimal() and actual == version_patch(version):
        return offset
    return None


def fields(item):
    summary, section = item["summary"], item["section"]
    result = []
    for key, label, offset, width, kind in (
        ("pkg_type", "包类型", 46, 1, "byte"),
        ("product_id", "产品 ID（十六进制）", 47, 4, "hex"),
        ("manufacturer", "厂商编号", 51, 1, "byte"),
        ("hardware_version", "硬件版本（两位数字）", 52, 2, "digits"),
        ("section_id", "分区 ID", section, 1, "byte"),
        ("section_name", "分区名称", section+1, 32, "text"),
        ("build_time", "容器构建时间", section+36, 24, "text"),
    ):
        result.append({"id": key, "label": label, "value": str(summary[key]),
                       "offset": offset, "width": width, "kind": kind, "area": "header"})
    result.append({"id": "version_digits", "label": "软件版本（同步容器、SW_VER、getter）",
                   "value": summary["version_digits"], "width": 3, "kind": "version",
                   "area": "version", "editable": getter_offset(item) is not None})
    raw = item["raw"]
    for block in summary["embedded_build_metadata"]:
        start = block["raw_offset"]
        end = raw.find(b"\0", start)
        opkg.require(end >= start, "Unterminated build metadata")
        label = block["fields"].get("CHIP_ROLE", block["fields"].get("KERNEL", ""))
        for match in re.finditer(rb"\n(BUILD_DATE|REV_INFO|SW_VER)=([^\r\n\x00]*)", raw[start:end]):
            key = match[1].decode("ascii")
            offset = start+match.start(2)
            result.append({"id": f"raw:{offset:x}", "label": f"{key} · {label} · {start:#x}",
                           "value": match[2].decode("ascii"), "offset": offset,
                           "width": len(match[2]), "kind": "fixed_text", "area": "raw",
                           "key": key, "editable": key != "SW_VER"})
    return result


def encode(field, value):
    opkg.require(isinstance(value, str), "Metadata value must be text")
    kind, width = field["kind"], field["width"]
    if kind in ("byte", "hex"):
        opkg.require(bool(re.fullmatch(r"[0-9A-Fa-f]+" if kind == "hex" else r"[0-9]+", value)),
                     "Invalid numeric metadata")
        number = int(value, 16 if kind == "hex" else 10)
        opkg.require(0 <= number < 256**width, "Metadata number exceeds field capacity")
        return number.to_bytes(width, "little")
    if kind == "digits":
        opkg.require(bool(re.fullmatch(r"[0-9]{2}", value)), "Hardware version needs two digits")
        return bytes(map(int, value))
    opkg.require(all(32 <= ord(c) <= 126 for c in value), "Metadata requires printable ASCII")
    encoded = value.encode("ascii")
    opkg.require(len(encoded) <= width, f"Metadata exceeds {width} bytes")
    return encoded.ljust(width, b" " if kind == "fixed_text" else b"\0")


def apply_raw(item, raw, edits):
    """Validate every field before applying, and return exact permitted byte ranges."""
    opkg.require(isinstance(edits, dict), "Invalid metadata edits")
    lookup = {f["id"]: f for f in fields(item)}
    opkg.require(not set(edits)-set(lookup), "Unknown metadata field")
    ranges = []
    pending = []
    for key, value in edits.items():
        field = lookup[key]
        opkg.require(field.get("editable", True), "Metadata field is not independently editable")
        if field["area"] == "raw":
            pending.append((field["offset"], encode(field, value)))
        elif field["area"] == "header":
            encode(field, value)
    if "version_digits" in edits:
        value = version_digits(edits["version_digits"])
        offset = getter_offset(item)
        opkg.require(offset is not None, "Version getter does not match the verified function")
        pending.append((offset, version_patch(value)))
        for field in lookup.values():
            if field.get("key") == "SW_VER":
                opkg.require(field["width"] == 3 and field["value"] == item["summary"]["version_digits"],
                             "SW_VER is inconsistent with the container version")
                pending.append((field["offset"], value.encode("ascii")))
        opkg.require(any(f.get("key") == "SW_VER" for f in lookup.values()), "SW_VER is missing")
    for offset, data in pending:
        raw[offset:offset+len(data)] = data
        ranges.append((offset, offset+len(data)))
    return ranges


def apply_header(item, packed, edits):
    result = bytearray(packed)
    lookup = {f["id"]: f for f in fields(item)}
    for key, value in edits.items():
        field = lookup[key]
        if field["area"] == "header":
            data = encode(field, value)
            result[field["offset"]:field["offset"]+len(data)] = data
        elif field["area"] == "version":
            offset = item["section"]+33
            result[offset:offset+3] = bytes(map(int, version_digits(value)))
    result[10:42] = bytes.fromhex(opkg.sha(result[42:]))
    return bytes(result)
