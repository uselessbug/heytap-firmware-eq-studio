"""Readable audio axes and stable, user-controlled display ranges."""

import numpy as np
import pyqtgraph as pg


class ResponsePlot(pg.PlotWidget):
    def __init__(self, label):
        super().__init__(background="#12171e")
        self.addLegend(offset=(15, 15), labelTextColor="#dce4ef")
        self.showGrid(x=True, y=True, alpha=.18)
        self.setLabel("left", label, color="#c0ccda")
        self.setLabel("bottom", "频率 (Hz)", color="#c0ccda")
        ticks = [(np.log10(f), f"{f//1000}k" if f >= 1000 else str(f))
                 for f in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000)]
        self.getAxis("bottom").setTicks([ticks])
        for axis in ("left", "bottom"):
            self.getAxis(axis).setTextPen("#b5c4d6")
            self.getAxis(axis).setPen("#384657")
        self.getAxis("left").setWidth(62)
        self.setMouseEnabled(x=True, y=False)
        self.setLimits(xMin=np.log10(20), xMax=np.log10(20000), minXRange=.1)
        self.setMenuEnabled(False)
        self.readout = pg.TextItem(color="#ccd7e5", anchor=(1, 0), fill="#202834")
        self.proxy = pg.SignalProxy(self.scene().sigMouseMoved, rateLimit=30, slot=self.hover)
        self.reset_range()

    def reset_range(self, low=-24, high=24, step=6):
        self.disableAutoRange()
        self.setXRange(np.log10(20), np.log10(20000), padding=0)
        self.setYRange(low, high, padding=0)
        self.getAxis("left").setTicks([[(float(v), f"{v:g}")
                                        for v in np.arange(low, high+step*.1, step)]])

    def clear_curves(self):
        self.getPlotItem().clear()
        self.addItem(self.readout)

    def hover(self, args):
        pos = args[0]
        if self.sceneBoundingRect().contains(pos):
            point = self.getViewBox().mapSceneToView(pos)
            self.readout.setText(f"{10**point.x():.0f} Hz · {point.y():+.2f} dB")
            view = self.getViewBox().viewRange()
            self.readout.setPos(view[0][1], view[1][1])
        else:
            self.readout.setText("")

    def zero_line(self):
        self.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#62758c", width=1)))


DARK_STYLE = """
QMainWindow, QWidget { background: #171d26; color: #dce4ef; font-size: 12px; }
QToolBar { background: #202836; border: 0; spacing: 8px; padding: 5px; }
QToolButton, QPushButton { background: #263243; border: 1px solid #3d4d63;
                          border-radius: 4px; padding: 6px 10px; }
QPushButton:hover, QToolButton:hover { background: #35475e; }
QPushButton:checked { background: #174b50; border-color: #35c5b7; color: #59e1d3; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background: #202936;
    border: 1px solid #3d4d63; border-radius: 3px; padding: 4px; }
QTableWidget, QPlainTextEdit { background: #12171e; gridline-color: #2e3b4c;
    border: 1px solid #334256; selection-background-color: #24555c; }
QHeaderView::section { background: #263243; color: #c8d6e7; padding: 5px; border: 0; }
QTabBar::tab { background: #202936; padding: 7px 14px; border: 1px solid #334256; }
QTabBar::tab:selected { background: #174b50; color: #59e1d3; }
QStatusBar { background: #12171e; color: #adbdcf; }
QSplitter::handle { background: #334256; }
QCheckBox { spacing: 5px; }
QScrollBar:vertical { background: #202936; width: 12px; }
"""
