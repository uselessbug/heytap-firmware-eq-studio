import numpy as np
import pytest

from heytap_eq.clipboard import decode_text
from heytap_eq.configuration import record_at
from heytap_eq.dsp import correction, filter_response
from heytap_eq.eq_formats import Filter, load_eq, parse_text
from heytap_eq.firmware_edit import make_plan
from heytap_eq.measurements import load_measurements
from tests.firmware_fixture import synthetic_firmware

AUTOEQ = """Preamp: -6.2 dB
Filter 1: ON LSC Fc 105 Hz Gain 6.4 dB Q 0.70
Filter 2: ON PK Fc 2000 Hz Gain -3.1 dB Q 1.41
Filter 3: OFF HSC Fc 10000 Hz Gain 2.0 dB Q 0.70
Filter 4: ON HSC Fc 8000 Hz Gain -1.5 dB Q 0.70
"""

REW = """Filter Settings file

Room EQ V5.31
Dated: Oct 11, 2026 10:00:00 AM

Notes:

Equaliser: Generic
Average 1
Filter  1: ON  PK       Fc   63.0 Hz  Gain  -5.0 dB  Q  4.00
Filter  2: ON  LPQ      Fc   18000 Hz  Q  0.707
Filter  3: OFF None
Filter  4: ON  NO       Fc   3000 Hz  Gain   0.0 dB  Q  8.0
"""


def test_autoeq_parametric_eq_keeps_types_order_disabled_filters_and_preamp(tmp_path):
    path = tmp_path/"ParametricEQ.txt"
    path.write_text(AUTOEQ, encoding="utf-8")
    doc = load_eq(path)
    assert [(f.id, f.kind, f.enabled) for f in doc.filters] == [
        (1, "LS", True), (2, "PEAK", True), (3, "HS", False), (4, "HS", True)]
    assert (doc.filters[0].frequency, doc.filters[0].gain, doc.filters[0].q) == (105, 6.4, .7)
    # Preamp is a flat level, kept for the firmware preamp control rather than the shape.
    assert doc.metadata == {"PREAMP_DB": "-6.2"} and not doc.raw
    # APO shelves use the RBJ midpoint frequency: half of the shelf gain at Fc.
    assert abs(filter_response([doc.filters[0]], [105])[0]-3.2) < 1e-9
    enabled = [f for f in doc.filters if f.enabled]
    x = np.geomspace(20, 20000, 300)
    assert np.allclose(correction(doc, x), filter_response(enabled, x))
    assert decode_text(AUTOEQ)["state"]["eq"]["filters"] == doc.to_dict()["filters"]


def test_rew_generic_export_skips_description_and_unused_slots():
    doc = parse_text(REW)
    assert doc.filters == [Filter(1, 63., -5., 4.), Filter(2, 18000., 0., .707, "LP"),
                           Filter(3, 3000., 0., 8., "NOTCH")]
    assert not doc.metadata


@pytest.mark.parametrize("bad", [
    "Filter: ON LS 6dB Fc 50 Hz Gain 7.2 dB",  # corner-frequency shelf
    "Filter: ON LSC 10.8 dB Fc 300 Hz Gain 5 dB",  # slope instead of Q
    "Filter: ON PK Fc 50 Hz Gain -10 dB BW Oct 1",  # bandwidth instead of Q
    "Filter: ON PK Fc 50 Hz Q 2",  # missing gain
    "Filter: ON LP Fc 1000 Hz",  # implicit Q
    "Filter: ON HP Fc 100 Hz Gain 3 dB Q 0.7",  # gain on a type without gain
    "Filter: ON XX Fc 100 Hz Gain 3 dB Q 0.7",
    "Filter: ON PK Fc 30000 Hz Gain 3 dB Q 0.7",
    "Preamp: -3",
    "Channel: L\nFilter: ON PK Fc 50 Hz Gain 1 dB Q 1\n"
    "Channel: R\nFilter: ON PK Fc 60 Hz Gain 1 dB Q 1",
    "Filter: ON PK Fc 50 Hz Gain 1 dB Q 1\nInclude: other.txt",
    "Filter: ON PK Fc 50 Hz Gain 1 dB Q 1\nunexpected text",
    "Preamp: -3 dB\nFilter 1: OFF None",
])
def test_ambiguous_or_unsupported_equalizer_apo_text_is_rejected(bad):
    with pytest.raises(ValueError):
        parse_text(bad)


def test_flowmix_metadata_named_like_apo_still_uses_flowmix_rules():
    doc = parse_text("[PEQ]\nPEQ1: 100 1 .7\n[METADATA]\nPREAMP: -3\nPEQ_COUNT: 1")
    assert doc.metadata == {"PREAMP": "-3", "PEQ_COUNT": "1"}


def test_autoeq_peaks_and_shelves_cascade_exactly_into_firmware(monkeypatch, tmp_path):
    firmware = synthetic_firmware(monkeypatch, tmp_path)
    plan = make_plan(firmware, parse_text(AUTOEQ), "清亮高音")
    assert plan["preamp_db"] == 0 and plan["eq"]["metadata"]["PREAMP_DB"] == "-6.2"
    assert len(plan["records"]) == 36
    for row in plan["records"]:
        source = record_at(firmware.profiles, row["table"], plan["baseline"], row["state"])
        for gain in ("gain0", "gain1"):
            assert row["record"][gain] == source[gain]
    assert all(r["record"]["optimizer_nfev"] == 0 for r in plan["records"])
    for row in plan["records"]:
        assert max(v["max_db"] for v in row["record"]["metrics"].values()) < 1e-4


@pytest.mark.parametrize("name, text", [
    ("legacy.csv", "frequency_hz,spl_db\n20,85.5\n1000,90\n20000,80.25\n"),
    ("autoeq.csv", "frequency,raw,error,smoothed\n20,85.5,0,0\n1000,90,0,0\n20000,80.25,,\n"),
    ("headerless.csv", "20, 85.5\n1000, 90\n20000, 80.25\n"),
    ("rew.txt", "* Measurement data measured by REW\n* Freq(Hz) SPL(dB) Phase(degrees)\n"
                "20.000 85.5 -12.0\n1000.000 90.0 3.5\n20000.000 80.25 0\n"),
    ("squig.txt", "Frequency [Hz]  SPL [dB]\n20 85.5\n1000 90\n20000 80.25\n"),
    ("tabs.txt", "Freq(Hz)\tSPL(dB)\n20\t85,5\n1000\t90\n20000\t80,25\n"),
    ("semicolon.csv", "Frequency;SPL\n20;85,5\n1000;90\n20000;80,25\n"),
    ("driver.frd", "* FRD\n20 85.5 0\n1000 90 0\n20000 80.25 0\n"),
    ("decimal.txt", "20 85,5\n1000 90\n20000 80,25\n"),
])
def test_common_measurement_and_target_tables(tmp_path, name, text):
    path = tmp_path/name
    path.write_text(text, encoding="utf-8")
    (curve,) = load_measurements(path)
    assert curve.title == path.stem
    assert curve.frequencies == [20, 1000, 20000] and curve.spl_values == [85.5, 90, 80.25]


@pytest.mark.parametrize("text", [
    "frequency,phase\n20,1\n1000,2\n",  # no SPL column
    "20,85\n1000\n",  # short row
    "20,85\n1000,abc\n",
    "20,85\n10,86\n",  # not increasing
    "* only comments\n",
])
def test_ambiguous_measurement_tables_are_rejected(tmp_path, text):
    path = tmp_path/"bad.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_measurements(path)


@pytest.mark.parametrize("alias,kind", [
    ("PK", "PEAK"), ("PEQ", "PEAK"), ("Modal", "PEAK"), ("LSC", "LS"), ("LS", "LS"),
    ("HSC", "HS"), ("HS", "HS"), ("LP", "LP"), ("LPQ", "LP"), ("HP", "HP"), ("HPQ", "HP"),
    ("BP", "BAND_PASS"), ("NO", "NOTCH"), ("AP", "ALL_PASS"),
])
def test_all_supported_apo_filter_mappings(alias, kind):
    gain = " Gain -2 dB" if kind in ("PEAK", "LS", "HS") else ""
    doc = parse_text(f"Filter 9: OFF {alias} Fc 1234 Hz{gain} Q 1.23")
    assert doc.filters == [Filter(1, 1234, -2 if gain else 0, 1.23, kind, False)]


@pytest.mark.parametrize("bad", [
    "Channel: L\nGraphicEQ: 20 1; 20000 0",
    "Channel: L\n[RAW]\nGraphicEQ: 20 1; 20000 0",
    "Include: other.txt\nGraphicEQ: 20 1; 20000 0",
    "Copy: L=R\nFilter: ON PK Fc 100 Hz Gain 1 dB Q 1",
    "VSTPlugin: other.dll\nFilter: ON PK Fc 100 Hz Gain 1 dB Q 1",
    "Equaliser: miniDSP\nFilter: ON PK Fc 100 Hz Gain 1 dB Q 1",
    "Preamp: 1e309 dB\nFilter: ON PK Fc 100 Hz Gain 1 dB Q 1",
    "Filter 1: ON None\nFilter 2: ON PK Fc 100 Hz Gain 1 dB Q 1",
])
def test_unsupported_commands_and_nonfinite_preamp_are_rejected(bad):
    with pytest.raises(ValueError):
        parse_text(bad)


def test_preamp_and_disabled_filters_survive_project_clipboard_and_history(tmp_path):
    from heytap_eq.clipboard import tuning_payload
    from heytap_eq.eq_formats import EQDocument, dump_eq
    from heytap_eq.session import Session

    doc = parse_text(AUTOEQ)
    session = Session()
    session.replace(doc)
    changed = EQDocument.from_dict(doc.to_dict())
    changed.filters[1].gain = -2.5
    session.replace(changed)
    session.undo()
    session.redo()
    path = tmp_path/"project.json"
    session.save(path)
    restored = Session()
    restored.restore(path)
    assert restored.document.metadata == doc.metadata
    assert restored.document.filters[2].enabled is False
    copied = tuning_payload(restored)
    assert EQDocument.from_dict(copied["state"]["eq"]).metadata == doc.metadata
    with pytest.raises(ValueError, match="disabled"):
        dump_eq(restored.document)
    restored.document.filters[2].enabled = True
    assert parse_text(dump_eq(restored.document)).metadata["PREAMP_DB"] == "-6.2"


@pytest.mark.parametrize("text", [
    "Frequency(kHz),SPL(dB)\n20,80\n1000,81",
    "Frequency [kHz] SPL [dB]\n20 80\n1000 81",
    "* Freq(kHz) SPL(dB)\n20 80\n1000 81",
    "Frequency(Hz),Magnitude(linear)\n20,80\n1000,81",
    AUTOEQ,
    "GraphicEQ: 20 1; 20000 0",
])
def test_non_measurements_and_unsupported_units_are_rejected(tmp_path, text):
    path = tmp_path/"wrong.txt"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        load_measurements(path)


@pytest.mark.parametrize("encoding", [None, "base64"])
def test_legacy_json_and_realab_har_keep_their_curves(tmp_path, encoding):
    import base64
    import json

    values = {"title": "Synthetic", "frequencies": [20, 1000, 20000], "spl_values": [80, 90, 82]}
    path = tmp_path/"legacy.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    assert load_measurements(path)[0].spl_values == values["spl_values"]
    html = "<script>window.__INITIAL_DATA__ = "+json.dumps({"Data": {"time": "2026-10-12", "data": [
        {"title": "Synthetic B&K 5128", "data": [[0, 0], [20, 80], [1000, 90], [20000, 82]]},
        {"title": "Synthetic B&K 5128 THD", "data": [[20, 1], [1000, 2]]},
    ]}})+";</script>"
    content = {"mimeType": "text/html", "text": html}
    if encoding:
        content.update(encoding=encoding, text=base64.b64encode(html.encode()).decode())
    # Entirely synthetic; no real request headers or credentials enter the fixture.
    path = tmp_path/"synthetic.har"
    path.write_text(json.dumps({"log": {"entries": [{"response": {"content": content}}]}}), encoding="utf-8")
    (curve,) = load_measurements(path)
    assert curve.frequencies == values["frequencies"] and curve.spl_values == values["spl_values"]


def test_preamp_precision_and_inline_comments():
    doc = parse_text("Preamp: -3.123456789012345 dB # annotation\n"
                     "Filter: ON PK Fc 100 Hz Gain 1 dB Q 1 # annotation")
    assert float(doc.metadata["PREAMP_DB"]) == -3.123456789012345
