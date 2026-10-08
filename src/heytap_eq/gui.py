"""Local Qt studio; firmware remains read-only in this milestone."""

import copy
import json
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from heytap_eq.adapters import PRESETS, STATES, inspect_firmware
from heytap_eq.apk_config import measurement_authorization
from heytap_eq.discovery import discover
from heytap_eq.dsp import correction, firmware_curve
from heytap_eq.eq_formats import KINDS, Filter, dump_eq, load_eq
from heytap_eq.flowmix import FlowmixClient
from heytap_eq.measurements import load_measurements
from heytap_eq.session import Session


class Worker(QtCore.QThread):
    def __init__(self, fn, callback, network, parent):
        super().__init__(parent)
        self.fn = fn
        self.callback = callback
        self.network = network
        self.result = None

    def run(self):
        try:
            self.result = (self.fn(), None)
        except Exception as exc:
            self.result = (None, exc)


class DragNodes(pg.GraphItem):
    moved = QtCore.Signal(object)

    def __init__(self, peq=False):
        super().__init__()
        self.positions = np.empty((0, 2))
        self.drag_index = None
        self.peq = peq

    def set_points(self, points):
        self.positions = np.array(points, dtype=float).reshape(-1, 2)
        self.refresh()

    def refresh(self):
        self.setData(pos=self.positions, data=np.arange(len(self.positions)),
                     symbol="d" if self.peq else "o", size=9 if self.peq else 7,
                     pxMode=True, brush="#85c997" if self.peq else "#d8a650", pen=None)

    def mouseDragEvent(self, event):
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            event.ignore()
            return
        if event.isStart():
            points = self.scatter.pointsAt(event.buttonDownPos())
            if not points:
                event.ignore()
                return
            self.drag_index = int(points[0].data())
        if self.drag_index is None:
            event.ignore()
            return
        index = self.drag_index
        if self.peq:
            self.positions[index, 0] = np.clip(event.pos().x(), np.log10(20), np.log10(20000))
        self.positions[index, 1] = np.clip(event.pos().y(), -60, 60)
        self.refresh()
        event.accept()
        if event.isFinish():
            change = (index, 10**float(self.positions[index, 0]), float(self.positions[index, 1])) if self.peq else (index, float(self.positions[index, 1]))
            self.moved.emit(change)
            self.drag_index = None


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, recover=True, auto_path=None):
        super().__init__()
        self.setWindowTitle("HeyTap Firmware EQ Studio")
        self.resize(1380, 880)
        self.session = Session()
        self.firmware = None
        self.measurements = []
        self.workers = set()
        self.network_workers = set()
        self.flowmix_client = None
        default_path = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.AppDataLocation)
        self.auto_path = Path(auto_path) if auto_path else Path(default_path)/"recovery.heytap.json"
        self._setup()
        if recover and self.auto_path.exists():
            try:
                self.session.restore(self.auto_path)
                self.statusBar().showMessage("已恢复上次 EQ 工程；重新打开原固件后会核对 SHA-256。")
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.statusBar().showMessage(f"恢复文件未加载：{exc}")
        self.refresh()

    def _action(self, toolbar, label, fn, shortcut=None):
        action = QtGui.QAction(label, self)
        action.triggered.connect(fn)
        if shortcut:
            action.setShortcut(shortcut)
        toolbar.addAction(action)
        return action

    def _setup(self):
        toolbar = self.addToolBar("文件与编辑")
        for label, fn in (("新建工程", self.new_project), ("打开固件", self.open_firmware),
                          ("导入 EQ", self.import_eq), ("导出 EQ", self.export_eq),
                          ("导入测量", self.import_measurements), ("打开工程", self.open_project)):
            self._action(toolbar, label, fn)
        self._action(toolbar, "保存工程", self.save_project, "Ctrl+S")
        self._action(toolbar, "候选结构扫描", self.scan_candidates)
        self.undo_action = self._action(toolbar, "撤销", self.undo, "Ctrl+Z")
        self.redo_action = self._action(toolbar, "重做", self.redo, "Ctrl+Shift+Z")
        body = QtWidgets.QWidget()
        self.setCentralWidget(body)
        layout = QtWidgets.QVBoxLayout(body)
        self.firmware_label = QtWidgets.QLabel("未打开固件")
        self.firmware_label.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.firmware_label)
        selectors = QtWidgets.QHBoxLayout()
        self.path_combo = QtWidgets.QComboBox()
        self.preset_combo = QtWidgets.QComboBox()
        self.preset_combo.addItems([*PRESETS, "特殊记录 45"])
        self.state_combo = QtWidgets.QComboBox()
        self.state_combo.addItems(["内部状态 "+s for s in STATES])
        self.rate_combo = QtWidgets.QComboBox()
        self.rate_combo.addItems(["44100", "48000", "96000"])
        self.rate_combo.setCurrentText("48000")
        for label, combo in (("路径", self.path_combo), ("预设", self.preset_combo),
                             ("状态", self.state_combo), ("采样率 Hz", self.rate_combo)):
            selectors.addWidget(QtWidgets.QLabel(label))
            selectors.addWidget(combo)
            combo.currentIndexChanged.connect(self.refresh)
        layout.addLayout(selectors)
        online = QtWidgets.QHBoxLayout()
        connect = QtWidgets.QPushButton("连接 Flowmix (APK)")
        connect.clicked.connect(self.connect_flowmix)
        self.source_combo = QtWidgets.QComboBox()
        self.brand_combo = QtWidgets.QComboBox()
        self.headphone_combo = QtWidgets.QComboBox()
        load_online = QtWidgets.QPushButton("载入在线测量")
        load_online.clicked.connect(self.load_online_measurements)
        self.source_combo.activated.connect(self.load_online_brands)
        self.brand_combo.activated.connect(self.load_online_headphones)
        self.online_controls = [connect, self.source_combo, self.brand_combo,
                                self.headphone_combo, load_online]
        for widget in self.online_controls:
            online.addWidget(widget)
        layout.addLayout(online)
        split = QtWidgets.QSplitter()
        layout.addWidget(split, 1)
        self.tabs = QtWidgets.QTabWidget()
        split.addWidget(self.tabs)
        self.digital_plot = self._plot("数字滤波增益 dB")
        self.tabs.addTab(self.digital_plot, "数字 EQ")
        acoustic = QtWidgets.QWidget()
        acoustic_layout = QtWidgets.QVBoxLayout(acoustic)
        self.measurement_combo = QtWidgets.QComboBox()
        self.measurement_combo.currentIndexChanged.connect(self.refresh)
        acoustic_layout.addWidget(self.measurement_combo)
        self.acoustic_plot = self._plot("人工耳 SPL dB")
        acoustic_layout.addWidget(self.acoustic_plot)
        acoustic_layout.addWidget(QtWidgets.QLabel(
            "估计 = 所选实测 + 当前修正；请选丹拿原声测量。固件版本 / 内部状态未确认时，不代表实测结果。"))
        self.tabs.addTab(acoustic, "人工耳实测与估计")
        self.metadata_text = QtWidgets.QPlainTextEdit()
        self.metadata_text.setReadOnly(True)
        self.tabs.addTab(self.metadata_text, "固件元数据 · 只读")
        side = QtWidgets.QWidget()
        side_layout = QtWidgets.QVBoxLayout(side)
        self.eq_label = QtWidgets.QLabel()
        side_layout.addWidget(self.eq_label)
        self.filters_table = QtWidgets.QTableWidget(0, 6)
        self.filters_table.setHorizontalHeaderLabels(["启用", "ID", "类型", "频率 Hz", "增益 dB", "Q"])
        self.filters_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.filters_table.itemChanged.connect(self.edit_filter)
        side_layout.addWidget(self.filters_table)
        buttons = QtWidgets.QHBoxLayout()
        for title, fn in (("增加 PEQ", self.add_filter), ("删除 PEQ", self.remove_filter)):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(fn)
            buttons.addWidget(button)
        side_layout.addLayout(buttons)
        side_layout.addWidget(QtWidgets.QLabel("类型："+", ".join(KINDS)+"\n黄色圆点：RAW 增益；绿色菱形：PEQ 频率/增益。\nQ 在表格编辑；一次拖动可一次撤销。"))
        self.firmware_table = QtWidgets.QTableWidget(0, 4)
        self.firmware_table.setHorizontalHeaderLabels(["固件类型", "增益 dB", "频率 Hz", "Q"])
        self.firmware_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        side_layout.addWidget(self.firmware_table)
        self.gains_label = QtWidgets.QLabel()
        side_layout.addWidget(self.gains_label)
        split.addWidget(side)
        split.setSizes([850, 530])
        self.nodes = DragNodes()
        self.nodes.moved.connect(self.edit_raw)
        self.peq_nodes = DragNodes(peq=True)
        self.peq_nodes.moved.connect(self.edit_peq)
        self._peq_map = []
        self.statusBar().showMessage("本地编辑 · 固件只读；拟合、封包和版本写入待后续验证")

    def _plot(self, label):
        plot = pg.PlotWidget(background="#171b22")
        plot.addLegend()
        plot.showGrid(x=True, y=True, alpha=.15)
        plot.setLabel("left", label)
        plot.setLabel("bottom", "频率 Hz · 对数轴")
        ticks = [(np.log10(f), str(f)) for f in (20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000)]
        plot.getAxis("bottom").setTicks([ticks])
        plot.setXRange(np.log10(20), np.log10(20000), padding=.01)
        return plot

    def _choose(self, title, pattern="所有文件 (*)", save=False):
        method = QtWidgets.QFileDialog.getSaveFileName if save else QtWidgets.QFileDialog.getOpenFileName
        return method(self, title, "", pattern)[0]

    def _task(self, fn, callback, network=False):
        workers = self.network_workers if network else self.workers
        if workers:
            self.statusBar().showMessage("正在读取文件，请等待当前任务完成。")
            return
        worker = Worker(fn, callback, network, self)
        workers.add(worker)
        if network:
            for control in self.online_controls:
                control.setEnabled(False)
        self.statusBar().showMessage("正在读取并验证…")

        worker.finished.connect(self.worker_finished, QtCore.Qt.ConnectionType.QueuedConnection)
        worker.start()

    @QtCore.Slot()
    def worker_finished(self):
        worker = self.sender()
        # finished can precede native TLS cleanup; join before freeing the wrapper.
        worker.wait()
        workers = self.network_workers if worker.network else self.workers
        workers.discard(worker)
        if worker.network:
            for control in self.online_controls:
                control.setEnabled(True)
        try:
            value, error = worker.result
            if error:
                raise error
            worker.callback(value)
        except Exception as exc:
            self.statusBar().showMessage(f"未加载：{exc}")
        finally:
            worker.fn = None
            worker.callback = None
            worker.deleteLater()

    def connect_flowmix(self):
        path = self._choose("选择 Flowmix Beta 5-10 APK", "APK (*.apk)")
        if path:
            def connected(auth):
                self.flowmix_client = FlowmixClient(auth, self.auto_path.parent/"flowmix-cache")
                self._task(self.flowmix_client.sources, self.set_online_sources, network=True)
            self._task(lambda: measurement_authorization(path), connected)

    def fill_online(self, combo, entries, preferred=None):
        combo.clear()
        for entry in entries:
            combo.addItem(entry["display"], entry["name"])
        index = combo.findData(preferred) if preferred else -1
        if index >= 0:
            combo.setCurrentIndex(index)

    def set_online_sources(self, entries):
        self.fill_online(self.source_combo, entries, "realab")
        self.load_online_brands()

    def load_online_brands(self, *_):
        source = self.source_combo.currentData()
        if self.flowmix_client and source:
            self.brand_combo.clear()
            self.headphone_combo.clear()
            self._task(lambda: self.flowmix_client.brands(source), self.set_online_brands, network=True)

    def set_online_brands(self, entries):
        self.fill_online(self.brand_combo, entries, "OPPO")
        self.load_online_headphones()

    def load_online_headphones(self, *_):
        source, brand = self.source_combo.currentData(), self.brand_combo.currentData()
        if self.flowmix_client and source and brand:
            self.headphone_combo.clear()
            self._task(lambda: self.flowmix_client.headphones(source, brand), self.set_online_headphones, network=True)

    def set_online_headphones(self, entries):
        self.fill_online(self.headphone_combo, entries, "OPPO_Enco_X4")
        origin = "离线缓存" if self.flowmix_client.from_cache else "在线"
        self.statusBar().showMessage(f"{origin}型号索引已载入；选择型号后载入测量。")

    def load_online_measurements(self):
        source, brand = self.source_combo.currentData(), self.brand_combo.currentData()
        name = self.headphone_combo.currentData()
        if self.flowmix_client and source and brand and name:
            def received(curves):
                self.set_measurements(curves)
                self.tabs.setCurrentIndex(1)
                origin = "离线缓存" if self.flowmix_client.from_cache else "在线"
                self.statusBar().showMessage(f"已载入{origin}测量 {len(curves)} 条；采样点数与原 HAR 可能不同。")
            self._task(lambda: self.flowmix_client.measurements(source, brand, name), received, network=True)

    def open_firmware(self):
        path = self._choose("打开固件")
        if path:
            self._task(lambda: inspect_firmware(path), self.set_firmware)

    def set_firmware(self, firmware):
        if self.session.firmware_sha256 not in (None, firmware.sha256):
            raise ValueError("工程绑定另一个固件；请打开原固件，或新建工程后切换。")
        self.firmware = firmware
        self.session.firmware_sha256 = firmware.sha256
        self.session.firmware_path = firmware.path
        self.path_combo.blockSignals(True)
        self.path_combo.clear()
        if firmware.profiles:
            self.path_combo.addItems([t["name"] for t in firmware.profiles["tables"]])
        self.path_combo.blockSignals(False)
        self.metadata_text.setPlainText(json.dumps(firmware.package["summary"], ensure_ascii=False, indent=2))
        self._changed()
        self.statusBar().showMessage(firmware.recognition)

    def scan_candidates(self):
        if self.firmware:
            self._task(lambda: discover(self.firmware.package["raw"]), self.show_candidates)

    def show_candidates(self, result):
        self.metadata_text.setPlainText(json.dumps(result, ensure_ascii=False, indent=2))
        self.tabs.setCurrentWidget(self.metadata_text)
        self.statusBar().showMessage("仅显示候选参数和可能指针；没有赋予名称或写入权限。")

    def import_eq(self):
        path = self._choose("导入 EQ", "EQ 文本 (*.txt);;所有文件 (*)")
        if path:
            self._task(lambda: load_eq(path), self.set_document)

    def set_document(self, doc):
        self.session.replace(doc)
        self._changed()

    def import_measurements(self):
        path = self._choose("导入人工耳测量", "测量 (*.csv *.json *.har)")
        if path:
            self._task(lambda: load_measurements(path), self.set_measurements)

    def set_measurements(self, curves):
        for curve in curves:
            if curve not in self.measurements:
                self.measurements.append(curve)
        self.measurement_combo.blockSignals(True)
        self.measurement_combo.clear()
        self.measurement_combo.addItems([c.title+" · "+c.source for c in self.measurements])
        self.measurement_combo.setCurrentIndex(self.measurements.index(curves[0]) if curves else -1)
        self.measurement_combo.blockSignals(False)
        self.refresh()
        self.statusBar().showMessage(f"已导入 {len(curves)} 条实测；离线功能可独立使用。")

    def new_project(self):
        if self.workers:
            return
        self.session = Session()
        self.firmware = None
        self.path_combo.clear()
        self.metadata_text.clear()
        self._changed()

    def open_project(self):
        path = self._choose("打开工程", "HeyTap 工程 (*.json)")
        if path:
            try:
                self.session.restore(path, self.firmware.sha256 if self.firmware else None)
                self._changed()
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.statusBar().showMessage(f"工程未加载：{exc}")

    def save_project(self):
        path = self._choose("保存工程", "HeyTap 工程 (*.heytap.json)", save=True)
        if path:
            try:
                self.session.save(path)
                self.statusBar().showMessage("工程已保存")
            except (ValueError, OSError) as exc:
                self.statusBar().showMessage(f"保存失败：{exc}")

    def export_eq(self):
        path = self._choose("导出 Flowmix EQ", "EQ 文本 (*.txt)", save=True)
        if path:
            try:
                Path(path).write_text(dump_eq(self.session.document), encoding="utf-8")
                self.statusBar().showMessage("EQ 文本已导出")
            except (ValueError, OSError) as exc:
                self.statusBar().showMessage(f"导出失败：{exc}")

    def add_filter(self):
        doc = copy.deepcopy(self.session.document)
        new_id = max((f.id for f in doc.filters), default=0)+1
        doc.filters.append(Filter(new_id, 1000, 0, .7))
        self.set_document(doc)

    def remove_filter(self):
        row = self.filters_table.currentRow()
        if row >= 0:
            doc = copy.deepcopy(self.session.document)
            del doc.filters[row]
            self.set_document(doc)

    def edit_filter(self, item):
        row = item.row()
        doc = copy.deepcopy(self.session.document)
        try:
            entries = [self.filters_table.item(row, i) for i in range(6)]
            doc.filters[row] = Filter(int(entries[1].text()), float(entries[3].text()),
                                      float(entries[4].text()), float(entries[5].text()),
                                      entries[2].text().upper(), entries[0].checkState() == QtCore.Qt.CheckState.Checked)
            self.set_document(doc)
        except (ValueError, IndexError) as exc:
            self.refresh()
            self.statusBar().showMessage(f"参数未应用：{exc}")

    def edit_raw(self, change):
        index, gain = change
        doc = copy.deepcopy(self.session.document)
        doc.raw[index][1] = gain
        self.set_document(doc)

    def edit_peq(self, change):
        index, frequency, gain = change
        doc = copy.deepcopy(self.session.document)
        f = doc.filters[self._peq_map[index]]
        f.frequency = frequency
        f.gain = gain
        self.set_document(doc)

    def undo(self):
        self.session.undo()
        self._changed()

    def redo(self):
        self.session.redo()
        self._changed()

    def _changed(self):
        self.refresh()
        try:
            self.session.save(self.auto_path)
        except OSError as exc:
            self.statusBar().showMessage(f"自动保存失败：{exc}")

    def refresh(self, *_):
        if not hasattr(self, "nodes"):
            return
        doc = self.session.document
        frequency = np.geomspace(20, 20000, 800)
        fs = int(self.rate_combo.currentText())
        self.digital_plot.clear()
        self.digital_plot.plot(np.log10(frequency), correction(doc, frequency, fs),
                               pen=pg.mkPen("#d8a650", width=2), name="当前修正 RAW + PEQ")
        self.nodes.set_points([[np.log10(f), g] for f, g in doc.raw])
        self.digital_plot.addItem(self.nodes)
        self._peq_map = [i for i, f in enumerate(doc.filters) if f.enabled]
        self.peq_nodes.set_points([[np.log10(doc.filters[i].frequency), doc.filters[i].gain] for i in self._peq_map])
        self.digital_plot.addItem(self.peq_nodes)
        record = None
        if self.firmware and self.firmware.profiles and self.path_combo.currentIndex() >= 0:
            bank = self.firmware.profiles
            table = bank["tables"][self.path_combo.currentIndex()]
            name = self.preset_combo.currentText()
            index = 45 if name == "特殊记录 45" else PRESETS[name]+self.state_combo.currentIndex()
            record = bank["profiles"][table["profile_indices"][index]]
            self.digital_plot.plot(np.log10(frequency), firmware_curve(record, frequency, fs),
                                   pen="#67afd1", name="固件滤波链 · 不含整体增益")
        label = "未打开固件"
        if self.firmware:
            label = f"{self.firmware.path}\nSHA-256 {self.firmware.sha256}\n{self.firmware.recognition}"
        elif self.session.firmware_sha256:
            label += f" · 工程绑定 {self.session.firmware_sha256}"
        self.firmware_label.setText(label)
        self.state_combo.setEnabled(self.preset_combo.currentText() != "特殊记录 45")
        self.gains_label.setText(f"gain0 = {record['gain0']:.6g} dB · gain1 = {record['gain1']:.6g} dB\n原始地址 {record['raw_offset']:#x} · {record['count']}/18 槽" if record else "固件字段与滤波器只读")
        self.firmware_table.setRowCount(record["count"] if record else 0)
        if record:
            for row, f in enumerate(record["slots"][:record["count"]]):
                for column, key in enumerate(("type_id", "gain", "fc", "q")):
                    self.firmware_table.setItem(row, column, QtWidgets.QTableWidgetItem(str(f[key])))
        self.eq_label.setText(f"{doc.name} · RAW {len(doc.raw)} 点 · PEQ {len(doc.filters)} 个")
        self.filters_table.blockSignals(True)
        self.filters_table.setRowCount(len(doc.filters))
        for row, f in enumerate(doc.filters):
            check = QtWidgets.QTableWidgetItem()
            check.setFlags(QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            check.setCheckState(QtCore.Qt.CheckState.Checked if f.enabled else QtCore.Qt.CheckState.Unchecked)
            self.filters_table.setItem(row, 0, check)
            for column, value in enumerate((f.id, f.kind, f.frequency, f.gain, f.q), 1):
                self.filters_table.setItem(row, column, QtWidgets.QTableWidgetItem(str(value)))
        self.filters_table.blockSignals(False)
        self.undo_action.setEnabled(bool(self.session._undo))
        self.redo_action.setEnabled(bool(self.session._redo))
        self.acoustic_plot.clear()
        if self.measurements and self.measurement_combo.currentIndex() >= 0:
            m = self.measurements[self.measurement_combo.currentIndex()]
            x = np.asarray(m.frequencies)
            self.acoustic_plot.plot(np.log10(x), m.spl_values, pen="#67afd1", name="人工耳实测 · "+m.source)
            self.acoustic_plot.plot(np.log10(x), np.asarray(m.spl_values)+correction(doc, x, fs),
                                    pen="#d8a650", name="修改后估计 · 实测 + 当前修正")

    def closeEvent(self, event):
        if self.workers or self.network_workers:
            self.statusBar().showMessage("正在读取文件，完成后即可关闭窗口。")
            event.ignore()
        else:
            event.accept()
