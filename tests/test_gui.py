from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from heytap_eq.eq_formats import parse_text
from heytap_eq.gui import MainWindow
from heytap_eq.measurements import Measurement


def test_edit_undo_project_and_measurement_preview(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(recover=False, auto_path=tmp_path/"recovery.json")
    window.show()
    window.set_document(parse_text("GraphicEQ: 20 1; 20000 0"))
    window.add_filter()
    app.processEvents()
    assert window.filters_table.rowCount() == 1
    window.filters_table.item(0, 4).setText("3")
    assert window.session.document.filters[0].gain == 3
    window.undo()
    assert window.session.document.filters[0].gain == 0
    window.redo()
    assert window.session.document.filters[0].gain == 3
    window.edit_peq((0, 1500, 2))
    assert window.session.document.filters[0].frequency == 1500
    window.undo()
    assert window.session.document.filters[0].frequency == 1000
    window.edit_raw((0, -2))
    assert window.session.document.raw[0][1] == -2
    window.undo()
    assert window.session.document.raw[0][1] == 1
    window.set_measurements([Measurement("Synthetic", [20, 1000, 20000], [80, 90, 80]).validate()])
    assert len(window.acoustic_plot.listDataItems()) == 2
    assert (tmp_path/"recovery.json").exists()
    assert window.grab().save(str(tmp_path/"gui.png"))
    window.close()


def test_raw_mouse_drag_is_one_undo_step(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(recover=False, auto_path=tmp_path/"drag.json")
    window.show()
    window.set_document(parse_text("GraphicEQ: 20 0; 1000 1; 20000 0"))
    app.processEvents()
    point = window.nodes.scatter.points()[1]
    start = window.digital_plot.mapFromScene(window.nodes.scatter.mapToScene(point.pos()))
    target = start+QtCore.QPoint(0, 35)
    viewport = window.digital_plot.viewport()
    QtTest.QTest.mousePress(viewport, QtCore.Qt.MouseButton.LeftButton, pos=start)
    move = QtGui.QMouseEvent(QtCore.QEvent.Type.MouseMove, QtCore.QPointF(target),
                            QtCore.QPointF(viewport.mapToGlobal(target)),
                            QtCore.Qt.MouseButton.NoButton, QtCore.Qt.MouseButton.LeftButton,
                            QtCore.Qt.KeyboardModifier.NoModifier)
    QtCore.QCoreApplication.sendEvent(viewport, move)
    QtTest.QTest.mouseRelease(viewport, QtCore.Qt.MouseButton.LeftButton, pos=target)
    app.processEvents()
    assert window.session.document.raw[1][1] != 1
    assert len(window.session._undo) == 2
    window.undo()
    assert window.session.document.raw[1][1] == 1
    window.close()


def test_online_selection_uses_file_id_without_network(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(recover=False, auto_path=tmp_path/"online.json")
    calls = []
    class Client:
        from_cache = False
        def brands(self, source):
            return [{"name": "OPPO", "display": "OPPO"}]
        def headphones(self, source, brand):
            return [{"name": "File_ID", "display": "Display name"}]
        def measurements(self, source, brand, headphone):
            calls.append((source, brand, headphone))
            return [Measurement("Synthetic", [20, 1000], [80, 90]).validate()]
    window.flowmix_client = Client()
    window.set_online_sources([{"name": "fixture", "display": "Fixture"}])
    for _ in range(100):
        app.processEvents()
        if window.headphone_combo.currentData() == "File_ID" and not window.network_workers:
            break
        QtTest.QTest.qWait(10)
    assert window.headphone_combo.currentData() == "File_ID"
    window.load_online_measurements()
    for _ in range(100):
        app.processEvents()
        if window.measurements and not window.network_workers:
            break
        QtTest.QTest.qWait(10)
    assert calls == [("fixture", "OPPO", "File_ID")]
    assert len(window.measurements) == 1
    window.close()


def test_pending_network_does_not_block_offline_file_task(tmp_path):
    import threading
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = MainWindow(recover=False, auto_path=tmp_path/"independent.json")
    release = threading.Event()
    def slow_network():
        release.wait(timeout=3)
        return []
    window._task(slow_network, lambda result: None, network=True)
    try:
        window._task(lambda: parse_text("GraphicEQ: 20 1; 20000 0"), window.set_document)
        for _ in range(100):
            app.processEvents()
            if window.session.document.raw and not window.workers:
                break
            QtTest.QTest.qWait(10)
        assert window.session.document.raw[0] == [20, 1]
        assert window.network_workers
    finally:
        release.set()
        for _ in range(100):
            app.processEvents()
            if not window.network_workers:
                break
            QtTest.QTest.qWait(10)
        window.close()
