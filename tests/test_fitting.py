import threading

import numpy as np
import pytest

from heytap_eq.fitting import FitOptions, fit_response
from heytap_eq.measurements import Measurement
from heytap_eq.preferences import BrowserMemory, unique_match
from heytap_eq.session import Session


def test_raw_aligns_different_frequency_grids_without_extrapolation():
    original = Measurement("A", [20, 1000, 20000], [85, 90, 88])
    target = Measurement("B", [40, 200, 1000, 18000], [2, 3, 0, -2])
    doc, report = fit_response(original, target, options=FitOptions(smoothing_octaves=0))
    assert report["range_hz"] == [40, 18000]
    assert report["target_offset_db"] == 90
    assert doc.raw[0] == [20, 0] and doc.raw[-1] == [20000, 0]
    assert all(v["rms_db"] < 1e-9 for v in report["rates"].values())
    with pytest.raises(ValueError, match="shared"):
        fit_response(original, Measurement("No overlap", [30000, 40000], [1, 2]))


def test_peq_recovers_a_smooth_peak_and_cancel_does_not_return_a_document():
    frequency = np.geomspace(20, 20000, 127)
    # An independently specified smooth bell, rather than an optimizer response fixture.
    target_db = 4*np.exp(-.5*(np.log2(frequency/1000)/.6)**2)
    before = Measurement("Flat", frequency.tolist(), [80.]*127)
    after = Measurement("Bell", frequency.tolist(), (80+target_db).tolist())
    options = FitOptions(align_hz=None, smoothing_octaves=0, filters=2, sample_rates=(48000,))
    doc, report = fit_response(before, after, "PEQ", options)
    assert len(doc.filters) <= 2
    assert report["rates"]["48000"]["rms_db"] < .3
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        fit_response(before, after, cancelled=cancel)


def test_browser_memory_is_empty_initially_and_remembers_each_device(tmp_path):
    memory = BrowserMemory(tmp_path/"memory.json")
    assert memory.selection() == {}
    first = {"source": "woodenears", "brand": "A", "headphone": "A_1"}
    memory.remember(first, "device-a")
    memory.remember({"source": "realab", "brand": "B", "headphone": "B_2"}, "device-b")
    restored = BrowserMemory(memory.path)
    assert restored.selection("device-a") == first
    assert restored.selection()["headphone"] == "B_2"
    assert restored.selection("unseen") == {}
    entries = [{"name": "Brand_Model_1", "display": "Brand Model 1"}]
    assert unique_match(entries, ["Brand Model 1"]) == "Brand_Model_1"
    assert unique_match(entries+entries, ["Brand Model 1"]) is None


def test_project_restores_measurements_targets_and_rejects_bad_curves_atomically(tmp_path):
    import json

    session = Session()
    session.measurements = [Measurement("Original", [20, 20000], [80, 90])]
    session.targets = [Measurement("Target", [20, 20000], [0, 1])]
    session.measurement_index = session.target_index = 0
    session.online_selection = {"source": "woodenears"}
    path = tmp_path/"project.json"
    session.save(path)
    restored = Session()
    restored.restore(path)
    assert restored.measurements == session.measurements and restored.targets == session.targets
    payload = json.loads(path.read_text())
    payload["targets"][0]["frequencies"] = [20000, 20]
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError):
        restored.restore(path)
    assert restored.targets == session.targets
