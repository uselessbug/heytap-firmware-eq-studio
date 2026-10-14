import pytest


@pytest.fixture(scope="session")
def qt_app():
    from PySide6 import QtCore, QtWidgets

    from heytap_eq.web_plot import initialize_web_engine

    initialize_web_engine()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    app.processEvents()
