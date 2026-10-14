"""Synthetic OPKG bytes only; no vendor firmware in CI."""

import hashlib
import lzma
import struct
import zlib

from heytap_eq.opkg import CHUNK_SIZE, MAGIC


def package(raw=b"Synthetic firmware payload"):
    chunks = [raw[i:i+CHUNK_SIZE] for i in range(0, len(raw), CHUNK_SIZE)]
    blocks = []
    for i, chunk in enumerate(chunks):
        stream = lzma.compress(chunk, format=lzma.FORMAT_ALONE,
                               filters=[{"id": lzma.FILTER_LZMA1, "dict_size": 0x4000000}])
        body = struct.pack("<8I", MAGIC, 36+len(stream), 32, len(chunks), i+1, 1,
                           len(chunk), len(stream)) + stream
        blocks.append(body + struct.pack("<I", zlib.crc32(body)))
    header = bytearray(208)
    header[:5] = b"OPKG\x01"
    struct.pack_into("<I", header, 5, 55)
    header[9] = 3
    header[54] = 1
    struct.pack_into("<I", header, 64, 140)
    section = 68
    struct.pack_into("<I", header, 47, 0x123abc)
    header[section+33:section+36] = bytes([1, 2, 3])
    payload = b"".join(blocks)
    struct.pack_into("<II", header, section+60, len(payload), len(raw))
    header[section+68:section+100] = hashlib.sha256(raw).digest()
    struct.pack_into("<I", header, section+100, 208)
    header[section+104:section+136] = hashlib.sha256(b"".join(b[28:-4] for b in blocks)).digest()
    struct.pack_into("<I", header, 42, len(header)+len(payload)-46)
    header[10:42] = hashlib.sha256(header[42:]+payload).digest()
    return bytes(header)+payload
