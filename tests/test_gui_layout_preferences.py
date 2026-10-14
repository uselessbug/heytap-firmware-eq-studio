import os
from pathlib import Path

import pytest
from PySide6 import QtCore, QtWidgets

from heytap_eq import dialogs
from heytap_eq.gui import MainWindow
from heytap_eq.measurements import Measurement
from heytap_eq.preferences import FILE_DIALOG_KINDS
from tests.firmware_fixture import synthetic_firmware
from tests.test_gui_shell import pump, wait

APPEARANCES = (("light", "blue", "standard"), ("dark", "violet", "standard"),
               ("dark", "amber", "standard"), ("dark", "amber", "high"),
               ("light", "violet", "high"), ("dark", "blue", "standard"))


@pytest.mark.parametrize("size", [(1028, 749), (1366, 768), (1920, 1080)])
@pytest.mark.parametrize("rail_width", [270, 330, 430])
def test_rail_width_stays_inside_viewport_after_live_theme_changes(monkeypatch, tmp_path, qt_app, size, rail_width):
    window = MainWindow(recover=False, auto_path=tmp_path/"recovery.json")
    window.connect_flowmix = lambda: None
    window.show()
    window.resize(*size)
    assert wait(qt_app, lambda: window.main_plot.is_ready)
    window.set_firmware(synthetic_firmware(monkeypatch, tmp_path))
    name = "VeryLongUnbrokenMeasurementName"*8+" 中文名称"
    window.set_measurements([Measurement(name, [20, 1000, 20000], [80, 90, 80]).validate()])
    window.set_targets([Measurement(name+" target", [20, 1000, 20000], [82, 90, 78]).validate()])
    window.source_combo.addItem(name)
    window.library_combo.addItem(name)
    window.online_toggle.setChecked(True)
    window.advanced_button.setChecked(True)
    # Show the whole generator without starting an unrelated background fit.
    window.generator_panel.show()
    window.set_rail_expanded(True)
    window.split.setSizes([0, rail_width, max(300, window.width()-rail_width)])
    pump(100)
    before_width = window.rail.width()
    reports = Path("reports")
    reports.mkdir(exist_ok=True)
    scale = os.environ.get("QT_SCALE_FACTOR", "1")
    for mode, accent, contrast in APPEARANCES:
        window.set_appearance(mode=mode, accent=accent, contrast=contrast)
        pump(100)
        viewport = window.rail.viewport()
        body = window.rail.widget()
        assert window.rail.isVisible() and not window.rail_strip.isVisible()
        assert abs(window.rail.width()-before_width) <= 2
        assert body.width() == viewport.width()
        assert window.rail.horizontalScrollBar().maximum() == 0
        controls = [*window.cards.values(), window.measurement_combo, window.target_combo,
                    window.source_combo, window.library_combo, window.firmware_fit_button]
        for control in controls:
            point = control.mapTo(viewport, QtCore.QPoint())
            assert point.x() >= 0 and point.x()+control.width() <= viewport.width(), (mode, control)
        assert window.rail.verticalScrollBar().maximum() > 0
        # Selection/removal behaviour is outside this fix.
        assert window.remove_plan_button.property("flat") is True
        if rail_width == 330 and mode == "dark" and accent == "violet":
            assert window.grab().save(str(reports/f"theme-layout-{size[0]}-scale-{scale}.png"))
    window.set_rail_expanded(False)
    window.set_appearance(mode="light")
    pump(100)
    assert not window.rail.isVisible() and window.rail_strip.isVisible()
    window.set_rail_expanded(True)
    pump(100)
    assert window.rail.widget().width() == window.rail.viewport().width()
    window.close()


ROUTES = (("open_project", "project_open", False), ("save_project", "project_save", True),
          ("open_firmware", "firmware_open", False), ("import_reference", "firmware_open", False),
          ("start_firmware_export", "firmware_export", True), ("import_eq", "eq_import", False),
          ("export_eq", "eq_export", True), ("import_measurements", "measurement_import", False),
          ("import_target", "target_import", False), ("import_mapping", "mapping_import", False))


@pytest.mark.parametrize("route,kind,save", ROUTES)
def test_real_file_actions_use_independent_remembered_directories(monkeypatch, tmp_path, qt_app, route, kind, save):
    window = MainWindow(recover=False, auto_path=tmp_path/"recovery.json")
    window.connect_flowmix = lambda: None
    window.set_firmware(synthetic_firmware(monkeypatch, tmp_path))
    for category in FILE_DIALOG_KINDS:
        folder = tmp_path/category/"中文 目录"
        folder.mkdir(parents=True)
        window.file_memory.remember(category, folder/"last-file.txt")
    window.session.metadata_edits = {"REV_INFO": "synthetic-test"}
    monkeypatch.setattr(dialogs, "export_settings", lambda *args: (.45, 1.5))
    calls = []

    def choose(parent, title, directory, pattern):
        calls.append((parent, directory, pattern))
        return "", ""  # Cancellation leaves session and all remembered directories alone.

    method = "getSaveFileName" if save else "getOpenFileName"
    monkeypatch.setattr(QtWidgets.QFileDialog, method, choose)
    before = window.file_memory.path.read_bytes()
    getattr(window, route)()
    expected = tmp_path/kind/"中文 目录"
    if route == "start_firmware_export":
        expected /= "source-edited.bin"
    assert len(calls) == 1 and calls[0][0] is window and Path(calls[0][1]) == expected
    assert window.file_memory.path.read_bytes() == before and not window.workers
    window.close()


def test_dialog_selection_persists_on_restart_without_entering_project_or_history(monkeypatch, tmp_path, qt_app):
    window = MainWindow(recover=False, auto_path=tmp_path/"recovery.json")
    folders = [tmp_path/"EQ 中文", tmp_path/"工程", tmp_path/"固件导出"]
    for folder in folders:
        folder.mkdir()
    selections = iter([str(folders[0]/"EQ.txt"), str(folders[1]/"project.heytap.json"),
                       str(folders[2]/"firmware.bin")])
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args: (next(selections), ""))
    for kind in ("eq_import", "project_open", "firmware_export"):
        assert window._choose("test", kind=kind)
    assert not window.session._undo and not window.session._redo
    assert "directories" not in window.session.snapshot()
    window.close()
    restored = MainWindow(recover=False, auto_path=tmp_path/"recovery.json")
    calls = []
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName",
                        lambda parent, title, directory, pattern: (calls.append(directory) or "", ""))
    for kind, folder in zip(("eq_import", "project_open", "firmware_export"), folders):
        assert restored._choose("test", kind=kind) == ""
        assert Path(calls[-1]) == folder
    restored.new_project()
    assert restored.file_memory.directory("eq_import") == str(folders[0])
    restored.close()
