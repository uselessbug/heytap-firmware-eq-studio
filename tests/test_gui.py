from PySide6 import QtWidgets

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
    window.edit_raw((0, -2))
    assert window.session.document.raw[0][1] == -2
    window.undo()
    assert window.session.document.raw[0][1] == 1
    window.set_measurements([Measurement("Synthetic", [20, 1000, 20000], [80, 90, 80]).validate()])
    assert len(window.acoustic_plot.listDataItems()) == 2
    assert (tmp_path/"recovery.json").exists()
    assert window.grab().save(str(tmp_path/"gui.png"))
    window.close()
