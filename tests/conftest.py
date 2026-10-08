import pytest


@pytest.fixture(scope="session")
def qt_app():
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app
    app.processEvents()
