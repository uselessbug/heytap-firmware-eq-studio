import copy
import json
import os
from pathlib import Path

import numpy as np

from heytap_eq.dsp import correction
from heytap_eq.eq_formats import dump_eq, parse_text
from heytap_eq.gui import MainWindow
from heytap_eq.measurements import Measurement
from tests.test_gui_shell import pump, wait

SETTINGS = {"enabled": True, "low_hz": 100., "high_hz": 8000., "low_octaves": .5, "high_octaves": 1.5}


def test_range_live_gesture_history_controls_and_import(tmp_path, qt_app):
    window = MainWindow(recover=False, auto_path=tmp_path/"range.json")
    window.show()
    window.set_document(parse_text("[PEQ]\nPEQ1: 1000 2 1 PEAK"))
    assert not window.range_enabled.isChecked() and not window.range_body.isVisible()
    initial = copy.deepcopy(window.session.document.to_dict())
    history = len(window.session._undo)
    window.editor_event({"op": "begin"})
    window.editor_event({"op": "range", "phase": "change", "range": SETTINGS})
    window.preview_timer.stop()
    window.refresh()
    assert window.session.document.to_dict() == initial
    assert len(window.session._undo) == history
    assert not window.range_body.isHidden() and window.range_enabled.isChecked()
    assert window.main_plot.payload()["correctionRange"]["low_octaves"] == .5
    window.editor_event({"op": "range", "phase": "end", "range": SETTINGS})
    assert len(window.session._undo) == history+1
    window.undo()
    assert not window.range_enabled.isChecked()
    window.redo()
    assert window.session.document.correction_range.high_octaves == 1.5
    assert window.range_sliders["low"].value() == 3
    assert window.range_sliders["high"].value() == 9
    # A normal import retains the range; RAW exported with the range starts unrestricted.
    window.set_document(parse_text("GraphicEQ: 20 1; 20000 1"), imported=True)
    assert window.session.document.correction_range.enabled
    baked = parse_text(dump_eq(window.session.document, 48000))
    before = correction(window.session.document, np.geomspace(20, 20000, 127))
    window.set_document(baked, imported=True)
    assert not window.session.document.correction_range.enabled
    np.testing.assert_allclose(correction(window.session.document, np.geomspace(20, 20000, 127)), before, atol=.003)
    # Users may enable a new range intentionally; subsequent node edits keep it enabled.
    window.editor_event({"op": "range", "range": SETTINGS})
    window.add_filter()
    assert window.session.document.correction_range.enabled
    previous = window.session.document.to_dict()
    window.editor_event({"op": "begin"})
    window.editor_event({"op": "range", "phase": "change", "range": {**SETTINGS, "low_hz": 200}})
    window.editor_event({"op": "cancel"})
    assert window.session.document.to_dict() == previous
    window.editor_event({"op": "range", "range": {**SETTINGS, "low_hz": 9000}})
    assert window.session.document.to_dict() == previous
    window.close()


def test_range_real_webchannel_preview_and_screenshots(tmp_path, qt_app):
    window = MainWindow(recover=False, auto_path=tmp_path/"range-web.json")
    window.show()
    window.set_document(parse_text("[PEQ]\nPEQ1: 200 4 0.8 PEAK\nPEQ2: 10000 3 1 HS"))
    window.set_measurements([Measurement("Synthetic baseline", [20, 1000, 20000], [85, 90, 82]).validate()])
    window.set_targets([Measurement("Synthetic target", [20, 1000, 20000], [87, 90, 83]).validate()])
    window.set_rail_expanded(True)
    window.cards["correction"].set_expanded(True)
    assert wait(qt_app, lambda: window.main_plot.is_ready)
    window.main_plot.page().runJavaScript('window.studioEdit('+json.dumps({"op": "range", "range": SETTINGS})+')')
    assert wait(qt_app, lambda: window.session.document.correction_range.enabled)
    window.fit_target_button.setChecked(True)
    assert wait(qt_app, lambda: window.correction_preview is not None, steps=400)
    assert window.correction_preview[0].correction_range == window.session.document.correction_range
    for width, height, mode in ((1028, 749, "light"), (1366, 768, "dark")):
        window.resize(width, height)
        window.set_appearance(mode=mode, accent="violet", contrast="standard")
        window.set_rail_expanded(True)
        window.rail.ensureWidgetVisible(window.range_enabled)
        painted = []
        assert wait(qt_app, lambda: (window.main_plot.inspect(painted.append), painted and painted[-1]
            and painted[-1]["boundaries"] == 2 and painted[-1]["theme"] == mode
            and painted[-1]["height"] >= 400)[1], delay=50)
        # Additional compositor time before capturing the actual Qt window.
        pump(250)
        scale = os.environ.get("QT_SCALE_FACTOR", "1")
        image = Path("reports")/f"correction-range-{mode}-{width}x{height}-scale-{scale}.png"
        image.parent.mkdir(exist_ok=True)
        assert window.grab().save(str(image))
        window.main_plot.page().runJavaScript('document.querySelector("button[data-boundary=low]").focus()')
        pump(250)
        focused_image = image.with_name(image.stem+"-focus.png")
        assert window.grab().save(str(focused_image))
    window.fit_target_button.setChecked(False)
    assert wait(qt_app, lambda: window.preview_worker is None)
    window.close()
