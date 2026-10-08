import struct
import urllib.request

import pytest

from heytap_eq.apk_config import dex_strings, measurement_authorization
from heytap_eq.flowmix import SafeRedirect, endpoint


def test_path_encoding_and_host_restriction():
    assert endpoint("https://fr-api.ykload.cn", "sources", "A/B 中文") == "https://fr-api.ykload.cn/api/sources/A%2FB%20%E4%B8%AD%E6%96%87"
    for base in ("http://fr-api.ykload.cn", "https://example.com", "https://fr-api.ykload.cn/other"):
        with pytest.raises(ValueError):
            endpoint(base, "sources")


def test_redirect_never_transfers_auth_to_other_hosts():
    req = urllib.request.Request("https://fr-api.ykload.cn/api/sources", headers={"Authorization": "Bearer synthetic"})
    for url in ("https://fr-api.ykload.com/api/sources", "http://fr-api.ykload.cn/api/sources"):
        with pytest.raises(ValueError):
            SafeRedirect().redirect_request(req, None, 302, "Found", {}, url)


def test_dex_bounds_and_unknown_apk(tmp_path):
    blob = bytearray(120)
    blob[:4] = b"dex\n"
    struct.pack_into("<II", blob, 56, 1, 112)
    struct.pack_into("<I", blob, 112, 116)
    blob[116:120] = b"\x02Hi\0"
    assert list(dex_strings(bytes(blob))) == ["Hi"]
    struct.pack_into("<I", blob, 112, 1000)
    with pytest.raises(ValueError):
        list(dex_strings(bytes(blob)))
    path = tmp_path/"unknown.apk"
    path.write_bytes(b"not the studied apk")
    with pytest.raises(ValueError):
        measurement_authorization(path)
