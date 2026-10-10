"""Bundled DSSSP editor inside Qt; DSP and edits remain in Python."""

import json
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWebChannel, QtWebEngineCore, QtWebEngineWidgets, QtWidgets


class PlotBridge(QtCore.QObject):
    publish = QtCore.Signal(str)

    def __init__(self, plot):
        super().__init__(plot)
        self.plot = plot

    @QtCore.Slot()
    def ready(self):
        self.plot.is_ready = True
        self.plot.commit()

    @QtCore.Slot(str)
    def submit(self, value):
        try:
            data = json.loads(value)
            if not isinstance(data, dict):
                raise ValueError("Invalid editor event")
            self.plot.editRequested.emit(data)
        except (ValueError, TypeError, KeyError) as exc:
            self.plot.error.emit(str(exc))


class ResponsePlot(QtWebEngineWidgets.QWebEngineView):
    editRequested = QtCore.Signal(object)
    error = QtCore.Signal(str)

    def __init__(self, label):
        super().__init__()
        self.axis_label = label
        self.is_ready = False
        self.curves = []
        self.low, self.high = -24., 24.
        self.reset_requested = True
        self.editor = {}
        self.bridge = PlotBridge(self)
        self.channel = QtWebChannel.QWebChannel(self.page())
        self.channel.registerObject("bridge", self.bridge)
        self.page().setWebChannel(self.channel)
        self.page().setBackgroundColor(QtGui.QColor("#101722"))
        self.settings().setAttribute(
            QtWebEngineCore.QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
        self.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.NoContextMenu)
        self.setMinimumSize(300, 210)
        assets = Path(__file__).with_name("web")/"index.html"
        if not assets.exists():
            self.setHtml("<body style='background:#101722;color:white'>"
                         "图形资源未构建，请使用 Actions 安装包或先运行 frontend 的构建。 </body>")
        else:
            self.load(QtCore.QUrl.fromLocalFile(str(assets.resolve())))

    def reset_range(self, low=-24., high=24., step=6):
        self.low, self.high = float(low), float(high)
        self.reset_requested = True

    def setLabel(self, axis, text, **_):
        if axis == "left":
            self.axis_label = text

    def clear_curves(self):
        self.curves = []

    def zero_line(self):
        # The SVG grid already draws the zero reference.
        pass

    def plot(self, frequency, values, color="#efb55a", name="", dashed=False):
        points = np.column_stack((frequency, values))
        if not np.all(np.isfinite(points)):
            raise ValueError("Non-finite plot points")
        self.curves.append({"name": name, "points": points.tolist(),
                            "color": color, "dashed": bool(dashed)})

    def listDataItems(self):
        return list(self.curves)

    def set_editor(self, **data):
        self.editor = data
        self.commit()

    def commit(self):
        if not self.is_ready:
            return
        payload = {"curves": self.curves, "low": self.low, "high": self.high,
                   "reset": self.reset_requested, "axisLabel": self.axis_label,
                   "filters": [], "raw": [], **self.editor}
        self.bridge.publish.emit(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        self.reset_requested = False

    def inspect(self, callback):
        self.page().runJavaScript("window.studioInspect ? window.studioInspect() : null", callback)


def initialize_web_engine():
    """Call before constructing QApplication, including GUI tests."""
    if QtWidgets.QApplication.instance() is None:
        QtCore.QCoreApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
