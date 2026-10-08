#!/usr/bin/env python3
"""Offline OPKG inspector/repacker for the four Enco X4 samples studied here.

Python 3.10+, standard library only. No device access or flashing.
Unknown metadata is retained. Repacking accepts equal-length raw images only.
"""
from __future__ import annotations

import hashlib
import lzma
import math
import re
import struct
import zlib
from pathlib import Path

MAGIC = 0x55AA66BB
CHUNK_SIZE = 0x40000
PROFILE_SIZE = 300
PROFILE_COUNT = 184
PROFILE_CAPACITY = 18
FLASH_BASE = 0x10028000
LAYOUTS = {
    8717764: {"bank": 0x735758, "tables": [0x84AE58, 0x84AF14, 0x84AFD0, 0x84B08C]},
    8650680: {"bank": 0x724F04, "tables": [0x83A840, 0x83A8FC, 0x83A9B8, 0x83AA74]},
}
TABLE_NAMES = ["other_output2", "india_output2", "other_output1", "india_output1"]


class FormatError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise FormatError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u32(data: bytes, offset: int) -> int:
    require(0 <= offset <= len(data) - 4, f"Truncated uint32 at {offset:#x}")
    return struct.unpack_from("<I", data, offset)[0]


def text_field(data: bytes) -> str:
    return data.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def digit_field(data: bytes) -> str:
    return "".join(str(v) for v in data if v < 10)


def metadata_strings(raw: bytes) -> list[dict]:
    result = []
    for match in re.finditer(rb"\nCHIP=[^\x00]+", raw):
        fields = {}
        for line in match.group().decode("ascii", errors="replace").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                fields[k] = v
        result.append({"raw_offset": match.start(), "fields": fields})
    return result


def parse(data: bytes) -> dict:
    require(len(data) >= 208, "File is too short")
    require(data[:4] == b"OPKG", "Not an OPKG file")
    require(data[4] == 1, "Only OPKG protocol version 1 is supported")
    header_length = u32(data, 5)
    require(header_length >= 46 and 9 + header_length <= len(data), "Invalid header length")
    require(data[9] == 3, "Only the observed hashId=3 (SHA-256) is supported")
    require(data[54] == 1, "This tool supports the observed single-section packages only")
    section_size_offset = 9 + header_length
    section_length = u32(data, section_size_offset)
    section = section_size_offset + 4
    require(section_length >= 136 and section + section_length <= len(data), "Invalid section header")
    payload_offset = u32(data, section + 100)
    payload_size = u32(data, section + 60)
    raw_size = u32(data, section + 64)
    require(payload_offset == section + section_length, "Unexpected gap before compressed blocks")
    require(payload_offset + payload_size == len(data), "Payload bounds do not cover the file")
    require(u32(data, 42) == len(data) - 46, "Package length mismatch")
    require(hashlib.sha256(data[42:]).digest() == data[10:42], "Package SHA-256 mismatch")
    blocks = []
    raw_parts = []
    compressed_hash = hashlib.sha256()
    position = payload_offset
    raw_offset = 0
    expected_count = None
    while position < len(data):
        require(position + 36 <= len(data), f"Truncated block at {position:#x}")
        h = struct.unpack_from("<8I", data, position)
        magic, total, head, count, index, codec, unpacked, compressed = h
        require(magic == MAGIC, f"Bad block magic at {position:#x}")
        require(head == 32 and codec == 1, "Only observed 32-byte LZMA block headers are supported")
        require(1 <= count <= 4096, "Invalid block count")
        if expected_count is None:
            expected_count = count
        require(count == expected_count and index == len(blocks) + 1, "Block numbering mismatch")
        require(total == 36 + compressed and position + total <= len(data), "Block length mismatch")
        require(0 < unpacked <= CHUNK_SIZE, "Raw block exceeds the observed chunk size")
        block = data[position : position + total]
        require(zlib.crc32(block[:-4]) == u32(block, total - 4), f"Block {index} CRC32 mismatch")
        stream = block[32:-4]
        require(len(stream) >= 13, "Truncated LZMA-alone stream")
        require(stream[:5] == bytes.fromhex("5d00000004"), "Unsupported LZMA properties/dictionary")
        require(stream[5:13] == b"\xff" * 8, "Unexpected LZMA decoded-length field")
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE, memlimit=256 * 1024 * 1024)
        decoded = decoder.decompress(stream, max_length=unpacked + 1)
        require(len(decoded) == unpacked and decoder.eof and not decoder.unused_data,
                f"Block {index} LZMA size/end mismatch")
        if index < count:
            require(unpacked == CHUNK_SIZE, "Non-final block does not use 256 KiB chunks")
        compressed_hash.update(block[28:-4])
        blocks.append({"index": index, "package_offset": position, "raw_offset": raw_offset,
                       "raw_size": unpacked, "compressed_size": compressed, "block_size": total,
                       "crc32": f"{u32(block, total - 4):08x}", "raw_sha256": sha(decoded),
                       "block_sha256": sha(block), "bytes": block, "raw": decoded})
        raw_parts.append(decoded)
        position += total
        raw_offset += unpacked
    require(len(blocks) == expected_count, "Missing blocks")
    raw = b"".join(raw_parts)
    require(len(raw) == raw_size, "Section raw size mismatch")
    require(hashlib.sha256(raw).digest() == data[section + 68 : section + 100], "Raw SHA-256 mismatch")
    require(compressed_hash.digest() == data[section + 104 : section + 136], "Compressed SHA-256 mismatch")
    summary = {
        "file_size": len(data), "file_sha256": sha(data), "protocol_version": data[4],
        "header_body_length": header_length, "section_body_length": section_length,
        "hash_id": data[9], "pkg_length": u32(data, 42), "pkg_type": data[46],
        "product_id": f"{u32(data, 47):06X}", "manufacturer": data[51],
        "hardware_version": digit_field(data[52:54]), "section_count": data[54],
        "section_id": data[section], "section_name": text_field(data[section + 1 : section + 33]),
        "version_digits": digit_field(data[section + 33 : section + 36]),
        "build_time": text_field(data[section + 36 : section + 60]),
        "payload_offset": payload_offset, "payload_size": payload_size,
        "raw_size": raw_size, "raw_sha256": sha(raw), "compressed_content_sha256": compressed_hash.hexdigest(),
        "header_extension_hex": data[55 : 9 + header_length].hex(),
        "section_extension_hex": data[section + 136 : section + section_length].hex(),
        "checks": {"pkg_length": True, "pkg_sha256": True, "raw_sha256": True,
                   "compressed_sha256": True, "all_block_crc32": True, "all_lzma_sizes": True},
        "blocks": [{k: v for k, v in b.items() if k not in {"bytes", "raw"}} for b in blocks],
        "embedded_build_metadata": metadata_strings(raw),
    }
    return {"data": data, "raw": raw, "blocks": blocks, "summary": summary,
            "section": section, "payload_offset": payload_offset}


def load(path: str | Path) -> dict:
    return parse(Path(path).read_bytes())


def repack(original: dict, edited: bytes, cancelled=None) -> tuple[bytes, list[int]]:
    require(len(edited) == len(original["raw"]), "Only equal-length raw images may be repacked")
    packed = []
    changed = []
    filters = [{"id": lzma.FILTER_LZMA1, "dict_size": 0x04000000, "lc": 3, "lp": 0, "pb": 2,
                "mode": lzma.MODE_NORMAL, "nice_len": 64, "mf": lzma.MF_BT4}]
    for block in original["blocks"]:
        if cancelled is not None and cancelled.is_set():
            raise InterruptedError("Repacking cancelled")
        o, size = block["raw_offset"], block["raw_size"]
        raw = edited[o : o + size]
        if raw == block["raw"]:
            packed.append(block["bytes"])
            continue
        changed.append(block["index"])
        stream = lzma.compress(raw, format=lzma.FORMAT_ALONE, filters=filters)
        header = bytearray(block["bytes"][:32])
        struct.pack_into("<I", header, 4, 36 + len(stream))
        struct.pack_into("<I", header, 28, len(stream))
        body = bytes(header) + stream
        packed.append(body + struct.pack("<I", zlib.crc32(body)))
    header = bytearray(original["data"][: original["payload_offset"]])
    section = original["section"]
    payload = b"".join(packed)
    struct.pack_into("<I", header, section + 60, len(payload))
    struct.pack_into("<I", header, section + 64, len(edited))
    header[section + 68 : section + 100] = hashlib.sha256(edited).digest()
    header[section + 104 : section + 136] = hashlib.sha256(b"".join(p[28:-4] for p in packed)).digest()
    struct.pack_into("<I", header, 42, len(header) + len(payload) - 46)
    header[10:42] = hashlib.sha256(bytes(header[42:]) + payload).digest()
    result = bytes(header) + payload
    verified = parse(result)
    require(verified["raw"] == edited, "Internal repack verification failed")
    return result, changed


def profiles(raw: bytes) -> dict:
    require(len(raw) in LAYOUTS, "No verified EQ layout for this raw image length")
    layout = LAYOUTS[len(raw)]
    bank = layout["bank"]
    configs = []
    for i in range(PROFILE_COUNT):
        o = bank + i * PROFILE_SIZE
        gain0, gain1, count = struct.unpack_from("<ffI", raw, o)
        require(0 <= count <= PROFILE_CAPACITY, f"Bad IIR count in profile {i}")
        require(all(math.isfinite(v) for v in [gain0, gain1]), "Non-finite overall gain")
        entries = []
        for k in range(PROFILE_CAPACITY):
            typ, gain, fc, q = struct.unpack_from("<Ifff", raw, o + 12 + k * 16)
            require(all(math.isfinite(v) for v in [gain, fc, q]), f"Non-finite parameter in profile {i}")
            entries.append({"slot": k, "active": k < count, "type_id": typ, "gain": gain, "fc": fc, "q": q})
        configs.append({"profile_index": i, "raw_offset": o, "flash_address": FLASH_BASE + o,
                        "gain0": gain0, "gain1": gain1, "count": count, "slots": entries,
                        "record_sha256": sha(raw[o : o + PROFILE_SIZE]), "memberships": []})
    tables = []
    for name, table in zip(TABLE_NAMES, layout["tables"]):
        indices = []
        for k in range(46):
            ptr = u32(raw, table + 4 * k)
            delta = ptr - FLASH_BASE - bank
            require(0 <= delta < PROFILE_COUNT * PROFILE_SIZE and delta % PROFILE_SIZE == 0,
                    f"Unexpected EQ pointer at {table + 4*k:#x}")
            idx = delta // PROFILE_SIZE
            indices.append(idx)
            configs[idx]["memberships"].append({"table": name, "table_index": k})
        require(u32(raw, table + 46 * 4) == 0, "Missing EQ pointer table terminator")
        tables.append({"name": name, "raw_offset": table, "profile_indices": indices})
    require(sorted(i for t in tables for i in t["profile_indices"]) == list(range(PROFILE_COUNT)),
            "EQ tables do not reference every profile exactly once")
    return {"bank_offset": bank, "bank_end_exclusive": bank + PROFILE_COUNT * PROFILE_SIZE,
            "record_size": PROFILE_SIZE, "capacity": PROFILE_CAPACITY, "profile_count": PROFILE_COUNT,
            "interpretation": "Gain/fc/Q and type_id are decoded by the firmware coefficient generator. "
                              "See eq_tool.py and mapping.json for verified filter types and preset names. "
                              "output1/output2 denote pointer-selector output arguments, not left/right ears.",
            "tables": tables, "profiles": configs}


