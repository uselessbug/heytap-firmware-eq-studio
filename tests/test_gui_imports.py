"""Real Qt file/clipboard entry points and WebChannel after third-party imports."""

import json
import threading
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from heytap_eq.configuration import record_at
from heytap_eq.eq_formats import parse_text
from heytap_eq.gui import MainWindow
from heytap_eq.gui_correction import PreviewWorker
from heytap_eq.measurements import load_measurements
from tests.firmware_fixture import synthetic_firmware
from tests.test_gui_shell import wait
from tests.test_imports import AUTOEQ, REW

WAVELET = "GraphicEQ: 20 1; 1000 0; 20000 -1"
FLOWMIX = "[RAW]\nGraphicEQ: 20 1; 1000 0; 20000 -1\n[PEQ]\nPEQ7: 1200 -2 1.2 PEAK"


@pytest.mark.parametrize("text", [AUTOEQ, REW, WAVELET, FLOWMIX])
@pytest.mark.parametrize("route", ["file", "paste"])
def test_eq_import_actions_keep_parameters_and_feedback(monkeypatch, tmp_path, qt_app, text, route):
    window = MainWindow(recover=False, auto_path=tmp_path/"recovery.json")
    window.show()
    calls = []
    path = tmp_path/"EQ.txt"
    path.write_text(text, encoding="utf-8")

    def choose(parent, title, directory, pattern):
        calls.append((title, pattern))
        return str(path), ""

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", choose)
    if route == "file":
        window.import_eq_action.trigger()
        assert wait(qt_app, lambda: not window.workers)
        assert len(calls) == 1 and "*.txt" in calls[0][1] and "AutoEQ" in calls[0][1]
        assert window.session.document.source_sha256
    else:
        qt_app.clipboard().setText(text)
        window.paste_action.trigger()
    doc = parse_text(text)
    assert window.session.document.filters == doc.filters
    assert window.session.document.raw == doc.raw
    assert window.session.document.metadata == doc.metadata
    assert len(window.session._undo) == 1
    if "PREAMP_DB" in doc.metadata:
        assert "-6.2" in window.eq_import_warning.text()
        assert "未应用" in window.statusBar().currentMessage()
        assert window.eq_import_warning.isVisibleTo(window.cards["correction"].body)
    window.undo()
    assert not window.session.document.filters and not window.session.document.raw
    assert window.eq_import_warning.isHidden()
    window.redo()
    assert window.session.document.metadata == doc.metadata
    window.close()


TABLES = [
    ("autoeq.csv", "frequency,raw\n20,80\n1000,90\n20000,82"),
    ("rew.txt", "* REW measurement\n* Freq(Hz) SPL(dB) Phase(degrees)\n20 80 0\n1000 90 0\n20000 82 0"),
    ("driver.frd", "20 80 0\n1000 90 0\n20000 82 0"),
]


@pytest.mark.parametrize("name,text", TABLES)
@pytest.mark.parametrize("role", ["measurement", "target"])
def test_measurement_file_dialogs_load_both_roles(monkeypatch, tmp_path, qt_app, name, text, role):
    window = MainWindow(recover=False, auto_path=tmp_path/"recovery.json")
    path = tmp_path/name
    path.write_text(text, encoding="utf-8")
    calls = []

    def choose(parent, title, directory, pattern):
        calls.append(pattern)
        return str(path), ""

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", choose)
    getattr(window, "import_measurements" if role == "measurement" else "import_target")()
    assert wait(qt_app, lambda: not window.workers)
    assert len(calls) == 1 and all(ext in calls[0] for ext in ("*.csv", "*.txt", "*.frd", "*.json", "*.har"))
    curves = window.measurements if role == "measurement" else window.targets
    assert curves == load_measurements(path)
    assert (window.measurement_combo if role == "measurement" else window.target_combo).currentIndex() == 0
    assert "已导入" in window.statusBar().currentMessage()
    window.close()


def test_gui_rejects_wrong_file_roles_without_changing_the_session(monkeypatch, tmp_path, qt_app):
    window = MainWindow(recover=False, auto_path=tmp_path/"recovery.json")
    path = tmp_path/"wrong.txt"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args: (str(path), ""))
    path.write_text(AUTOEQ, encoding="utf-8")
    window.import_measurements()
    assert wait(qt_app, lambda: not window.workers)
    assert "未完成" in window.statusBar().currentMessage() and not window.measurements
    path.write_text("20 80\n1000 90", encoding="utf-8")
    window.import_eq()
    assert wait(qt_app, lambda: not window.workers)
    assert "未完成" in window.statusBar().currentMessage() and not window.session.document.filters
    qt_app.clipboard().setText("Copy: L=R\n"+AUTOEQ)
    window.paste_tuning()
    assert "粘贴未完成" in window.statusBar().currentMessage()
    assert not window.session._undo
    window.close()


def test_imported_eq_webchannel_preview_fit_export_and_project(monkeypatch, tmp_path, qt_app):
    window = MainWindow(recover=False, auto_path=tmp_path/"recovery.json")
    window.connect_flowmix = lambda: None
    window.show()
    path = tmp_path/"ParametricEQ.txt"
    path.write_text(AUTOEQ, encoding="utf-8")
    selected = [path]
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args: (str(selected[0]), ""))
    window.import_eq_action.trigger()
    assert wait(qt_app, lambda: not window.workers and window.main_plot.is_ready)
    window.main_plot.page().runJavaScript('window.studioEdit({op:"filter",phase:"end",index:1,'
        'filter:{frequency:2300,gain:-2.5,q:1.6,kind:"PEAK",enabled:true}})')
    assert wait(qt_app, lambda: window.session.document.filters[1].frequency == 2300)
    assert window.session.document.filters[1].q == 1.6
    assert window.session.document.filters[2].enabled is False
    assert window.session.document.metadata["PREAMP_DB"] == "-6.2"
    # Real embedded Qt/WebEngine screenshots of the imported EQ and persistent warning.
    window.set_rail_expanded(True)
    window.cards["correction"].set_expanded(True)
    for width, height in ((1028, 749), (1366, 768)):
        window.resize(width, height)
        qt_app.processEvents()
        window.set_rail_expanded(True)
        window.rail.ensureWidgetVisible(window.eq_import_warning)
        painted = []
        assert wait(qt_app, lambda: (window.main_plot.inspect(painted.append),
            painted and painted[-1] and painted[-1]["filters"] == 4
            and painted[-1]["svgPaths"] >= 1 and painted[-1]["height"] >= 400)[1], delay=50)
        image = Path("reports")/f"imported-eq-{width}x{height}.png"
        image.parent.mkdir(exist_ok=True)
        assert window.grab().save(str(image))
    for method, name, text in [
        (window.import_measurements, "original.csv", TABLES[0][1]),
        (window.import_target, "target.frd", "20 82 0\n1000 90 0\n20000 81 0"),
    ]:
        selected[0] = tmp_path/name
        selected[0].write_text(text, encoding="utf-8")
        method()
        assert wait(qt_app, lambda: not window.workers)
    before = window.session.document.to_dict()
    window.fit_target_button.setChecked(True)
    assert wait(qt_app, lambda: window.correction_preview is not None)
    assert window.session.document.to_dict() == before
    assert any(c["name"].startswith("生成预览") for c in window.main_plot.curves)
    window.fit_target_button.setChecked(False)
    window.set_firmware(synthetic_firmware(monkeypatch, tmp_path))
    window.fit_firmware_preset("清亮高音")
    assert wait(qt_app, lambda: not window.workers and window.session.firmware_plans, steps=800)
    plan = window.session.firmware_plans[0]
    assert len(plan["records"]) == 36 and plan["preamp_db"] == 0
    assert plan["eq"]["metadata"]["PREAMP_DB"] == "-6.2"
    assert {r["table"] for r in plan["records"]} == {
        "other_output1", "india_output1", "other_output2", "india_output2"}
    for row in plan["records"]:
        source = record_at(window.firmware.profiles, row["table"], plan["baseline"], row["state"])
        assert row["record"]["gain0"] == source["gain0"]
        assert row["record"]["gain1"] == source["gain1"]
    output = tmp_path/"export.bin"
    window.export_to_path(output)
    assert wait(qt_app, lambda: not window.workers and output.exists(), steps=800)
    assert window.last_export_report["checks"]
    project = tmp_path/"saved.heytap.json"
    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", lambda *args: (str(project), ""))
    window.save_project()
    assert json.loads(project.read_text(encoding="utf-8"))["schema"] == "heytap-project-v4"
    window.add_filter()
    selected[0] = project
    window.open_project()
    assert window.session.document.to_dict() == before
    assert len(window.session.firmware_plans) == 1
    received = []
    assert wait(qt_app, lambda: (window.main_plot.inspect(received.append),
                               received and received[-1] and received[-1]["svgPaths"] >= 3)[1])
    window.close()


def test_close_keeps_a_running_preview_thread_alive(tmp_path, qt_app):
    window = MainWindow(recover=False, auto_path=tmp_path/"close.json")
    window.show()
    release = threading.Event()
    worker = PreviewWorker(lambda: release.wait(10), ("slow",), window)
    worker.completed.connect(window._preview_finished, QtCore.Qt.ConnectionType.QueuedConnection)
    window.preview_worker = worker
    worker.start()
    try:
        assert window.close() is False
        assert window.correction_cancel.is_set() and window.isVisible()
        assert "正在取消" in window.statusBar().currentMessage()
    finally:
        release.set()
        assert wait(qt_app, lambda: window.preview_worker is None)
        window.close()
