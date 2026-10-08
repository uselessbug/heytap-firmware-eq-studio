"""Read the explicitly selected, studied Flowmix APK. Never persist its credential."""

import hashlib
import struct
import zipfile
from pathlib import Path

KNOWN_APK_SHA256 = "79777621b8dd6643f7ab2c0c0c7e77f846a2cb2d6c4ed23b59ac8858798412e2"


def dex_strings(data):
    if len(data) < 112 or data[:4] != b"dex\n":
        raise ValueError("Invalid DEX header")
    count, offset = struct.unpack_from("<II", data, 56)
    if count > 1000000 or offset+count*4 > len(data):
        raise ValueError("DEX string table outside file")
    for i in range(count):
        pos = struct.unpack_from("<I", data, offset+i*4)[0]
        if pos >= len(data):
            raise ValueError("DEX string outside file")
        for _ in range(5):
            value = data[pos]
            pos += 1
            if not value & 128:
                break
        else:
            raise ValueError("Invalid DEX string length")
        end = data.find(b"\0", pos)
        if end < 0:
            raise ValueError("Unterminated DEX string")
        yield data[pos:end].decode("utf-8", errors="replace")


def measurement_authorization(path):
    return authorization_from_bytes(Path(path).read_bytes())


def authorization_from_bytes(raw):
    import io

    if hashlib.sha256(raw).hexdigest() != KNOWN_APK_SHA256:
        raise ValueError("Only the studied Flowmix Beta 5-10 APK is supported")
    with zipfile.ZipFile(io.BytesIO(raw)) as apk:
        strings = list(dex_strings(apk.read("classes.dex")))
    # This exact APK has one full Bearer constant; Lnw0.b adds it as Authorization.
    values = [s for s in strings if s.startswith("Bearer ") and len(s) > 7]
    if len(values) != 1 or any(x in values[0] for x in ("\r", "\n")):
        raise ValueError("Studied measurement authorization constant not uniquely found")
    return values[0]
