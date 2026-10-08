import json
from pathlib import Path

import numpy as np
import pytest

from heytap_eq import opkg
from heytap_eq.adapters import inspect_firmware
from heytap_eq.discovery import discover
from heytap_eq.dsp import coefficients, correction, filter_response
from heytap_eq.eq_formats import EQDocument, Filter, dump_eq, load_eq, parse_text
from heytap_eq.measurements import parse_har, parse_json
from heytap_eq.session import Session
from tests.fixtures import package


def test_recovered_flowmix_example():
    doc = load_eq(Path("research/enco_x4_eq_toolkit/examples/Technics-AZ80-Optimized.txt"))
    assert len(doc.raw) == 127 and len(doc.filters) == 5
    assert doc.metadata["SELECTED_PEQ"] == "0"
    assert np.max(abs(correction(doc, np.geomspace(20, 20000, 500))
                      - correction(EQDocument(raw=doc.raw), np.geomspace(20, 20000, 500)))) > 1


def test_sparse_ids_and_roundtrip():
    doc = parse_text("[RAW]\nGraphicEQ: 20 0; 20000 -1\n[PEQ]\nPEQ2: 100 1 .7\nPEQ9: 1000 -1 1 HS\n[METADATA]\nPEQ_COUNT: 2\nRAW_BANDS: 2\nSELECTED_PEQ: 9")
    assert [f.id for f in doc.filters] == [2, 9]
    assert parse_text(dump_eq(doc)).to_dict() == doc.to_dict()


@pytest.mark.parametrize("bad", [
    "PEQ1: 100 1 .7\nPEQ1: 200 1 .7", "PEQ2: nan 1 .7", "PEQ_COUNT: 2",
    "PEQ1: 100 1 0", "PEQ1: 100 1 .7 UNKNOWN", "RAW_BANDS: 4",
])
def test_bad_eq_rejected(bad):
    with pytest.raises(ValueError):
        parse_text("[RAW]\nGraphicEQ: 20 0; 20000 0\n[PEQ]\n"+bad)


@pytest.mark.parametrize("fs", [44100, 48000, 96000])
def test_biquad_semantics_and_stability(fs):
    x = np.geomspace(20, 20000, 400)
    assert np.max(abs(filter_response([Filter(0, 1000, 0, .7, "ALL_PASS")], x, fs))) < 1e-10
    assert abs(filter_response([Filter(0, 1000, 6, .7)], [1000], fs)[0]-6) < 1e-10
    for kind in ("PEAK", "LS", "HS", "LP", "HP", "NOTCH", "BAND_PASS", "ALL_PASS"):
        sos = coefficients([Filter(0, 1000, 3, .7, kind)], fs)
        assert max(abs(np.roots(sos[0, 3:]))) < 1
    assert filter_response([Filter(0, 1000, 0, .7, "NOTCH")], [1000], fs)[0] < -200


def test_opkg_integrity_and_preserved_blocks(tmp_path):
    original = package(b"A"*opkg.CHUNK_SIZE+b"second block")
    parsed = opkg.parse(original)
    assert opkg.repack(parsed, parsed["raw"]) == (original, [])
    changed = parsed["raw"][:-1]+b"X"
    rebuilt, ids = opkg.repack(parsed, changed)
    assert ids == [2]
    assert opkg.parse(rebuilt)["blocks"][0]["bytes"] == parsed["blocks"][0]["bytes"]
    damaged = bytearray(original)
    damaged[-4] ^= 1
    with pytest.raises(opkg.FormatError):
        opkg.parse(bytes(damaged))
    with pytest.raises(opkg.FormatError):
        opkg.repack(parsed, changed+b"extra")
    path = tmp_path/"unknown.bin"
    path.write_bytes(original)
    assert inspect_firmware(path).profiles is None


def test_project_binding_and_failed_restore_are_atomic(tmp_path):
    session = Session()
    doc = parse_text("GraphicEQ: 20 1; 20000 0")
    session.replace(doc)
    session.undo()
    assert not session.document.raw
    session.redo()
    session.firmware_sha256 = "a"*64
    path = tmp_path/"project.json"
    session.save(path)
    with pytest.raises(ValueError):
        session.restore(path, "b"*64)
    assert session.document.raw == doc.raw
    data = json.loads(path.read_text())
    data["eq"]["raw"] = [[100, 1], [20, 0]]
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        session.restore(path, "a"*64)
    assert session.document.raw == doc.raw and session.firmware_sha256 == "a"*64


def test_measurements_do_not_keep_har_credentials():
    page = {"Data": {"time": "2026-09-15", "data": [{"title": "B&K 5128 丹拿原声", "data": [[20, 80], [1000, 90]]}]}}
    har = {"log": {"entries": [{"request": {"headers": [{"Cookie": "secret"}]},
                                "response": {"content": {"mimeType": "text/html", "text": "window.__INITIAL_DATA__ = "+json.dumps(page)}}}]}}
    curves = parse_har(har)
    assert curves[0].frequencies == [20, 1000]
    assert "secret" not in repr(curves)
    with pytest.raises(ValueError):
        parse_json({"success": False, "data": {}})
    with pytest.raises(ValueError):
        parse_json({"frequencies": [100, 20], "spl_values": [1, 2]})


def test_discovery_never_grants_write_access():
    import struct
    raw = bytearray(600)
    struct.pack_into("<ffIIfff", raw, 16, -1, 1, 1, 1, 3, 1000, .7)
    struct.pack_into("<I", raw, 500, 0x10028000+16)
    result = discover(bytes(raw))
    assert result["writable"] is False
    candidate = next(c for c in result["candidates"] if c["raw_offset"] == 16)
    assert candidate["possible_pointer_words_at_base_0x10028000"] == [500]
