"""Small synthetic semantic adapter; contains no vendor image or measurement data."""

import struct

from heytap_eq import adapters, metadata, opkg
from tests.fixtures import package


def synthetic_firmware(monkeypatch, tmp_path):
    raw = bytearray(0xf000)
    bank, tables = 0x400, [0xe000+i*188 for i in range(4)]
    raw[0x100:0x110] = b"synthetic-code!!"
    # Signature is the 12-byte getter independently rechecked in both real variants.
    raw[0x200:0x20c] = metadata.GETTERS[8717764][1]
    build = b"\nCHIP=synthetic\nKERNEL=1\nSW_VER=112\nBUILD_DATE=Oct  9 2026 00:00:00\nREV_INFO=synthetic-test\n\0"
    raw[0xe400:0xe400+len(build)] = build
    for index in range(184):
        offset = bank+index*300
        gain = 1. if index % 46 == 0 else -3.
        struct.pack_into("<ffI", raw, offset, gain, gain, 3)
        for slot, values in enumerate(((4, 0., 30., .7), (1, 1., 1000., .7), (3, 0., 18000., .7))):
            struct.pack_into("<Ifff", raw, offset+12+slot*16, *values)
    for table_index, offset in enumerate(tables):
        for state in range(46):
            struct.pack_into("<I", raw, offset+state*4,
                             opkg.FLASH_BASE+bank+(table_index*46+state)*300)
    monkeypatch.setitem(opkg.LAYOUTS, len(raw), {"bank": bank, "tables": tables})
    monkeypatch.setitem(adapters.FINGERPRINTS, len(raw), ((0x100, 0x110, opkg.sha(raw[0x100:0x110])),))
    monkeypatch.setitem(metadata.GETTERS, len(raw), (0x200, metadata.GETTERS[8717764][1]))
    packed = bytearray(package(bytes(raw)))
    struct.pack_into("<I", packed, 47, 0x06ec10)
    packed[68+33:68+36] = bytes([1, 1, 2])
    packed[10:42] = bytes.fromhex(opkg.sha(packed[42:]))
    path = tmp_path/"source.bin"
    path.write_bytes(packed)
    return adapters.inspect_firmware(path)
