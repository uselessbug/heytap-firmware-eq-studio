"""Local Qt studio with external EQ and validated firmware edit plans."""

import copy
import json
import threading
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets

from heytap_eq import metadata
from heytap_eq.adapters import PRESETS, STATES, inspect_firmware
from heytap_eq.discovery import discover
from heytap_eq.dsp import correction, firmware_curve
from heytap_eq.eq_formats import Filter, dump_eq, load_eq
from heytap_eq.firmware_dsp import response as firmware_response
from heytap_eq.firmware_edit import export_firmware, make_plan
from heytap_eq.fitting import FitOptions, fit_response
from heytap_eq.flowmix import FlowmixClient
from heytap_eq.measurements import load_measurements
from heytap_eq.plot import DARK_STYLE
from heytap_eq.web_plot import ResponsePlot
from heytap_eq.preferences import BrowserMemory, device_identity
from heytap_eq.service_profile import builtin_authorization
from heytap_eq.session import Session, atomic_json


class Worker(QtCore.QThread):
    progress = QtCore.Signal(str)
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


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, recover=True, auto_path=None):
        super().__init__()
        self.setWindowTitle("HeyTap Firmware EQ Studio")
        self.resize(1380, 880)
        self.session = Session()
        self.firmware = None
        self.measurements = []
        self.targets = []
        self.sources = []
        self.device = None
        self.fit_cancel = threading.Event()
        self.edit_generation = 0
        self.fit_report = None
        self._preview_document = None
        self.preview_timer = QtCore.QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(25)
        self.preview_timer.timeout.connect(self.refresh)
        self.workers = set()
        self.network_workers = set()
        self.flowmix_client = None
        default_path = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.AppDataLocation)
        self.auto_path = Path(auto_path) if auto_path else Path(default_path)/"recovery.heytap.json"
        self.memory = BrowserMemory(self.auto_path.parent/"browser-memory.json")
        self.desired_selection = self.memory.selection()
        self._setup()
        if recover and self.auto_path.exists():
            try:
                self.session.restore(self.auto_path)
                self.statusBar().showMessage("已恢复上次 EQ 工程；重新打开原固件后会核对 SHA-256。")
            except (ValueError, OSError, KeyError, TypeError) as exc:
                self.statusBar().showMessage(f"恢复文件未加载：{exc}")
        self.restore_curves()
        self.refresh()

    def _action(self, toolbar, label, fn, shortcut=None):
        action = QtGui.QAction(label, self)
        action.triggered.connect(fn)
        if shortcut:
            action.setShortcut(shortcut)
        toolbar.addAction(action)
        return action

    def _setup(self):
        self.setStyleSheet(DARK_STYLE)
        toolbar = self.addToolBar("文件与编辑")
        toolbar.setMovable(False)
        for label, fn in (("新建工程", self.new_project), ("打开固件", self.open_firmware),
                          ("导入 EQ", self.import_eq), ("导出 EQ", self.export_eq),
                          ("导入测量", self.import_measurements), ("打开工程", self.open_project)):
            self._action(toolbar, label, fn)
        self._action(toolbar, "保存工程", self.save_project, "Ctrl+S")
        self._action(toolbar, "候选结构扫描", self.scan_candidates)
        self.undo_action = self._action(toolbar, "撤销", self.undo, "Ctrl+Z")
        self.redo_action = self._action(toolbar, "重做", self.redo, "Ctrl+Shift+Z")
        self.addToolBarBreak()
        firmware_toolbar = self.addToolBar("固件编辑")
        firmware_toolbar.setMovable(False)
        self.firmware_actions = [
            self._action(firmware_toolbar, "拟合到固件预设", self.start_firmware_fit),
            self._action(firmware_toolbar, "编辑固件信息", self.edit_metadata),
            self._action(firmware_toolbar, "清空固件修改", self.clear_firmware_edits),
            self._action(firmware_toolbar, "导出固件", self.start_firmware_export),
        ]
        self._action(firmware_toolbar, "取消拟合/封包", self.cancel_fit)
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
        selectors.addWidget(QtWidgets.QLabel("当前预设"))
        selectors.addWidget(self.preset_combo)
        self.preset_combo.currentIndexChanged.connect(self.refresh)
        advanced = QtWidgets.QPushButton("高级预览")
        advanced.setCheckable(True)
        selectors.addWidget(advanced)
        selectors.addStretch()
        layout.addLayout(selectors)
        self.advanced_controls = QtWidgets.QWidget()
        advanced_layout = QtWidgets.QHBoxLayout(self.advanced_controls)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        for label, combo in (("输出路径", self.path_combo), ("内部状态", self.state_combo),
                             ("预览采样率 Hz", self.rate_combo)):
            advanced_layout.addWidget(QtWidgets.QLabel(label))
            advanced_layout.addWidget(combo)
            combo.currentIndexChanged.connect(self.refresh)
        advanced_layout.addWidget(QtWidgets.QLabel("这些选项只控制数字链预览；写入处理整个预设。"))
        self.advanced_controls.setVisible(False)
        advanced.toggled.connect(self.advanced_controls.setVisible)
        layout.addWidget(self.advanced_controls)
        self.firmware_edits_label = QtWidgets.QLabel("尚未准备固件修改")
        self.firmware_edits_label.setWordWrap(True)
        layout.addWidget(self.firmware_edits_label)
        online = QtWidgets.QHBoxLayout()
        connect = QtWidgets.QPushButton("获取在线测量")
        connect.clicked.connect(self.connect_flowmix)
        self.source_combo = QtWidgets.QComboBox()
        self.brand_combo = QtWidgets.QComboBox()
        self.headphone_combo = QtWidgets.QComboBox()
        load_online = QtWidgets.QPushButton("载入在线测量")
        load_online.clicked.connect(self.load_online_measurements)
        self.source_combo.activated.connect(self.source_chosen)
        self.brand_combo.activated.connect(self.brand_chosen)
        self.headphone_combo.activated.connect(self.remember_browser)
        self.online_controls = [connect, self.source_combo, self.brand_combo,
                                self.headphone_combo, load_online]
        for widget in self.online_controls:
            online.addWidget(widget)
        for combo, placeholder in ((self.source_combo, "选择数据源"),
                                   (self.brand_combo, "搜索品牌"),
                                   (self.headphone_combo, "搜索型号")):
            combo.setPlaceholderText(placeholder)
            combo.setEditable(True)
            combo.lineEdit().setPlaceholderText(placeholder)
            combo.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
            combo.completer().setFilterMode(QtCore.Qt.MatchFlag.MatchContains)
            combo.completer().setCompletionMode(QtWidgets.QCompleter.CompletionMode.PopupCompletion)
        layout.addLayout(online)
        presets = QtWidgets.QHBoxLayout()
        self.preset_buttons = {}
        for name in PRESETS:
            button = QtWidgets.QPushButton(name)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, n=name: self.preset_combo.setCurrentText(n))
            self.preset_buttons[name] = button
            presets.addWidget(button)
        presets.addStretch()
        self.eq_range_combo = QtWidgets.QComboBox()
        self.eq_range_combo.addItems(["±12 dB", "±24 dB", "±48 dB"])
        self.eq_range_combo.setCurrentIndex(1)
        self.eq_range_combo.currentIndexChanged.connect(self.reset_plots)
        presets.addWidget(QtWidgets.QLabel("EQ 范围"))
        presets.addWidget(self.eq_range_combo)
        side_toggle = QtWidgets.QPushButton("参数面板")
        side_toggle.setCheckable(True)
        side_toggle.setChecked(True)
        side_toggle.toggled.connect(lambda visible: self.side.setVisible(visible))
        presets.addWidget(side_toggle)
        reset = QtWidgets.QPushButton("复位视图")
        reset.clicked.connect(self.reset_plots)
        presets.addWidget(reset)
        layout.addLayout(presets)
        split = QtWidgets.QSplitter()
        layout.addWidget(split, 1)
        self.tabs = QtWidgets.QTabWidget()
        split.addWidget(self.tabs)
        self.digital_plot = self._plot("数字滤波增益 dB")
        self.tabs.addTab(self.digital_plot, "数字 EQ／固件链")
        acoustic = QtWidgets.QWidget()
        acoustic_layout = QtWidgets.QVBoxLayout(acoustic)
        self.measurement_combo = QtWidgets.QComboBox()
        self.measurement_combo.currentIndexChanged.connect(self.curve_selection_changed)
        acoustic_controls = QtWidgets.QGridLayout()
        acoustic_controls.addWidget(QtWidgets.QLabel("原始频响"), 0, 0)
        acoustic_controls.addWidget(self.measurement_combo, 0, 1, 1, 5)
        self.target_combo = QtWidgets.QComboBox()
        self.target_combo.setPlaceholderText("选择目标频响")
        self.target_combo.currentIndexChanged.connect(self.curve_selection_changed)
        acoustic_controls.addWidget(QtWidgets.QLabel("目标频响"), 1, 0)
        acoustic_controls.addWidget(self.target_combo, 1, 1, 1, 5)
        for column, title, fn in ((0, "目标曲线库", self.browse_targets),
                                  (1, "导入目标", self.import_target),
                                  (2, "当前实测设为目标", self.measurement_as_target),
                                  (3, "生成修正 EQ", self.start_fit),
                                  (4, "取消拟合", self.cancel_fit)):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(fn)
            acoustic_controls.addWidget(button, 2, column)
        self.relative_check = QtWidgets.QCheckBox("1 kHz 对齐显示")
        self.relative_check.setChecked(True)
        self.relative_check.toggled.connect(self.reset_plots)
        acoustic_controls.addWidget(self.relative_check, 2, 5)
        acoustic_layout.addLayout(acoustic_controls)
        visibility = QtWidgets.QHBoxLayout()
        self.curve_checks = {}
        for key, title in (("original", "原始实测"), ("estimated", "修改后估计"), ("target", "目标频响")):
            check = QtWidgets.QCheckBox(title)
            check.setChecked(True)
            check.toggled.connect(self.refresh)
            self.curve_checks[key] = check
            visibility.addWidget(check)
        visibility.addStretch()
        acoustic_layout.addLayout(visibility)
        self.acoustic_plot = self._plot("人工耳 SPL dB")
        acoustic_layout.addWidget(self.acoustic_plot)
        self.quality_label = QtWidgets.QLabel("选择原始与目标频响，生成 RAW 或 PEQ 修正。估计 = 原始实测 + 当前修正。")
        self.quality_label.setWordWrap(True)
        acoustic_layout.addWidget(self.quality_label)
        self.tabs.addTab(acoustic, "频响与调音")
        self.tabs.setCurrentIndex(1)
        self.metadata_text = QtWidgets.QPlainTextEdit()
        self.metadata_text.setReadOnly(True)
        self.tabs.addTab(self.metadata_text, "固件信息与修改计划")
        side = QtWidgets.QWidget()
        self.side = side
        side_layout = QtWidgets.QVBoxLayout(side)
        self.eq_label = QtWidgets.QLabel()
        side_layout.addWidget(self.eq_label)
        self.filters_table = QtWidgets.QTableWidget(0, 6)
        self.filters_table.setHorizontalHeaderLabels(["启用", "ID", "类型", "频率 Hz", "增益 dB", "Q"])
        self.filters_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.filters_table.itemChanged.connect(self.edit_filter)
        self.filters_table.setMinimumHeight(170)
        side_layout.addWidget(self.filters_table)
        buttons = QtWidgets.QHBoxLayout()
        for title, fn in (("增加 PEQ", self.add_filter), ("删除 PEQ", self.remove_filter)):
            button = QtWidgets.QPushButton(title)
            button.clicked.connect(fn)
            buttons.addWidget(button)
        side_layout.addLayout(buttons)
        side_layout.addWidget(QtWidgets.QLabel("双击图形添加 PEQ；拖动圆点调频率与增益。\n在点上滚轮调 Q；右键打开完整参数。\n黄色小点编辑 RAW；一次拖动可一次撤销。"))
        self.firmware_table = QtWidgets.QTableWidget(0, 4)
        self.firmware_table.setHorizontalHeaderLabels(["固件类型", "增益 dB", "频率 Hz", "Q"])
        self.firmware_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.ResizeToContents)
        self.firmware_table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        side_layout.addWidget(self.firmware_table)
        self.gains_label = QtWidgets.QLabel()
        side_layout.addWidget(self.gains_label)
        split.addWidget(side)
        split.setSizes([1050, 330])
        self.digital_plot.editRequested.connect(self.editor_event)
        self.acoustic_plot.editRequested.connect(self.editor_event)
        for plot in (self.digital_plot, self.acoustic_plot):
            plot.error.connect(lambda message: self.statusBar().showMessage(message))
        self._peq_map = []
        self.reset_plots()
        self.statusBar().showMessage("导入 EQ 或频响后，可拟合到已确认的固件预设并导出新文件。")

    def _plot(self, label):
        return ResponsePlot(label)

    def reset_plots(self, *_):
        if not hasattr(self, "acoustic_plot"):
            return
        span = (12, 24, 48)[self.eq_range_combo.currentIndex()]
        self.digital_plot.reset_range(-span, span, span/4)
        if self.relative_check.isChecked():
            self.acoustic_plot.reset_range(-24, 24, 6)
            self.acoustic_plot.setLabel("left", "相对声压 (dB · 1 kHz = 0)")
        else:
            values = [v for m in self.measurements+self.targets for v in m.spl_values]
            low = np.floor(min(values)/5)*5 if values else 60
            high = max(low+50, np.ceil(max(values)/5)*5) if values else 110
            self.acoustic_plot.reset_range(low, high, 5)
            self.acoustic_plot.setLabel("left", "声压 SPL (dB)")
        self.refresh()

    def _choose(self, title, pattern="所有文件 (*)", save=False):
        method = QtWidgets.QFileDialog.getSaveFileName if save else QtWidgets.QFileDialog.getOpenFileName
        return method(self, title, "", pattern)[0]

    def _task(self, fn, callback, network=False, with_progress=False):
        workers = self.network_workers if network else self.workers
        if workers:
            self.statusBar().showMessage("正在读取文件，请等待当前任务完成。")
            return
        worker = Worker(fn, callback, network, self)
        if with_progress:
            worker.fn = lambda: fn(worker.progress.emit)
        worker.progress.connect(self.statusBar().showMessage)
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
            self.statusBar().showMessage(f"操作未完成：{exc}")
            self.statusBar().setToolTip(str(exc))
        finally:
            worker.fn = None
            worker.callback = None
            worker.deleteLater()

    def connect_flowmix(self):
        def connected(auth):
            self.flowmix_client = FlowmixClient(auth, self.auto_path.parent/"flowmix-cache")
            self._task(self.flowmix_client.sources, self.set_online_sources, network=True)
        def prepare():
            auth = builtin_authorization(self.auto_path.parent)
            if not auth:
                raise ValueError("此包尚未配置测量接口认证；离线导入与拟合可直接使用。")
            return auth
        self._task(prepare, connected, network=True)

    def fill_online(self, combo, entries, preferred=None):
        combo.blockSignals(True)
        combo.clear()
        for entry in entries:
            combo.addItem(entry["display"], entry["name"])
        combo.setCurrentIndex(combo.findData(preferred) if preferred else -1)
        combo.blockSignals(False)

    def remember_browser(self, *_):
        selection = {"source": self.source_combo.currentData(),
                     "brand": self.brand_combo.currentData(),
                     "headphone": self.headphone_combo.currentData()}
        self.desired_selection = selection
        self.session.online_selection = selection
        try:
            self.memory.remember(selection, self.device["key"] if self.device else None)
        except OSError as exc:
            self.statusBar().showMessage(f"选择未保存：{exc}")
        self._changed()

    def source_chosen(self, *_):
        self.brand_combo.clear()
        self.headphone_combo.clear()
        self.remember_browser()
        self.load_online_brands()

    def brand_chosen(self, *_):
        self.headphone_combo.clear()
        self.remember_browser()
        self.load_online_headphones()

    def set_online_sources(self, entries):
        self.sources = entries
        self.fill_online(self.source_combo, entries, self.desired_selection.get("source"))
        if self.source_combo.currentData():
            self.load_online_brands()
        elif self.device and "model" in self.device and not self.desired_selection:
            self.match_firmware_device()
        else:
            self.statusBar().showMessage("在线来源已载入；请选择来源、品牌与型号。")

    def match_firmware_device(self):
        if not self.flowmix_client or not self.device or "model" not in self.device:
            return
        identity = dict(self.device)
        def matched(selection):
            if not self.device or self.device["key"] != identity["key"]:
                return
            if selection:
                self.desired_selection = selection
                self.fill_online(self.source_combo, self.sources, selection["source"])
                self.load_online_brands()
            else:
                self.statusBar().showMessage("未找到唯一的精确型号匹配，请手动选择测量。")
        self._task(lambda: self.flowmix_client.match_device(identity, self.sources), matched, network=True)

    def load_online_brands(self, *_):
        source = self.source_combo.currentData()
        if self.flowmix_client and source:
            self.brand_combo.clear()
            self.headphone_combo.clear()
            self._task(lambda: self.flowmix_client.brands(source), self.set_online_brands, network=True)

    def set_online_brands(self, entries):
        self.fill_online(self.brand_combo, entries, self.desired_selection.get("brand"))
        if self.brand_combo.currentData():
            self.load_online_headphones()

    def load_online_headphones(self, *_):
        source, brand = self.source_combo.currentData(), self.brand_combo.currentData()
        if self.flowmix_client and source and brand:
            self.headphone_combo.clear()
            self._task(lambda: self.flowmix_client.headphones(source, brand), self.set_online_headphones, network=True)

    def set_online_headphones(self, entries):
        self.fill_online(self.headphone_combo, entries, self.desired_selection.get("headphone"))
        if self.headphone_combo.currentData():
            self.remember_browser()
        origin = "离线缓存" if self.flowmix_client.from_cache else "在线"
        self.statusBar().showMessage(f"{origin}型号索引已载入；选择型号后载入测量。")

    def load_online_measurements(self):
        source, brand = self.source_combo.currentData(), self.brand_combo.currentData()
        name = self.headphone_combo.currentData()
        if self.flowmix_client and source and brand and name:
            self.remember_browser()
            def received(curves):
                self.set_measurements(curves)
                self.tabs.setCurrentIndex(1)
                origin = "离线缓存" if self.flowmix_client.from_cache else "在线"
                self.statusBar().showMessage(f"已载入{origin}测量 {len(curves)} 条。")
            self._task(lambda: self.flowmix_client.measurements(source, brand, name), received, network=True)
        else:
            self.statusBar().showMessage("请先选择来源、品牌与型号。")

    def browse_targets(self):
        if not self.flowmix_client:
            self.statusBar().showMessage("先点击获取在线测量以连接数据服务。")
            return
        def choose(entries):
            if not entries:
                return
            display, ok = QtWidgets.QInputDialog.getItem(self, "在线目标曲线", "选择目标",
                                                        [e["display"] for e in entries], 0, False)
            if ok:
                identifier = next(e["name"] for e in entries if e["display"] == display)
                self._task(lambda: self.flowmix_client.target(identifier), self.set_targets, network=True)
        self._task(self.flowmix_client.targets, choose, network=True)

    def import_target(self):
        path = self._choose("导入目标频响", "测量 (*.csv *.json *.har)")
        if path:
            self._task(lambda: load_measurements(path), self.set_targets)

    def measurement_as_target(self):
        index = self.measurement_combo.currentIndex()
        if index >= 0:
            self.set_targets([copy.deepcopy(self.measurements[index])])

    def set_targets(self, curves):
        for curve in curves:
            if curve not in self.targets:
                self.targets.append(curve)
        self.fill_curves(self.target_combo, self.targets,
                         self.targets.index(curves[0]) if curves else -1)
        self.curve_selection_changed()
        self.tabs.setCurrentIndex(1)

    def fill_curves(self, combo, curves, index):
        combo.blockSignals(True)
        combo.clear()
        combo.addItems([c.title+" · "+c.source for c in curves])
        combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def restore_curves(self):
        self.measurements = self.session.measurements
        self.targets = self.session.targets
        self.fill_curves(self.measurement_combo, self.measurements, self.session.measurement_index)
        self.fill_curves(self.target_combo, self.targets, self.session.target_index)
        if self.session.online_selection:
            self.desired_selection = dict(self.session.online_selection)

    def curve_selection_changed(self, *_):
        self._changed()
        self.reset_plots()

    def cancel_fit(self):
        self.fit_cancel.set()
        self.statusBar().showMessage("正在取消当前拟合或封包任务…")

    def start_firmware_fit(self):
        if not self.firmware or not self.firmware.profiles or self.workers:
            return
        if not self.session.document.raw and not self.session.document.filters:
            self.statusBar().showMessage("先导入、编辑或生成修正 EQ。")
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("拟合到固件完整预设")
        form = QtWidgets.QFormLayout(dialog)
        destination = QtWidgets.QComboBox()
        destination.addItems(list(PRESETS))
        current = self.preset_combo.currentText()
        destination.setCurrentText(current if current in PRESETS and current != "丹拿原声" else "丹拿高解析")
        preamp = QtWidgets.QDoubleSpinBox()
        preamp.setRange(-24, 0)
        preamp.setSuffix(" dB")
        form.addRow("替换预设", destination)
        form.addRow("整体衰减", preamp)
        note = QtWidgets.QLabel("以各路径、状态对应的丹拿原声为基线，加上当前修正 EQ。\n"
                               "处理四条路径和全部九个内部状态，保留基线 HP/LP/AP。\n"
                               "完成后加入修改计划；可以继续为其他预设准备不同 EQ。")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.fit_firmware_preset(destination.currentText(), preamp.value())

    def fit_firmware_preset(self, destination, preamp=0):
        if not self.firmware or not self.firmware.profiles or self.workers:
            return
        firmware, doc = self.firmware, copy.deepcopy(self.session.document)
        generation = self.edit_generation
        self.fit_cancel = threading.Event()
        cancelled = self.fit_cancel
        def received(plan):
            if generation != self.edit_generation:
                self.statusBar().showMessage("拟合期间输入已变化，结果未加入当前固件计划。")
                return
            self.session.stage_plan(plan)
            self._changed()
            maximum = max(m["max_db"] for r in plan["records"] for m in r["record"]["metrics"].values())
            self.statusBar().showMessage(f"{destination} 已加入计划：36 条记录，最大误差 {maximum:.3f} dB。")
        self._task(lambda progress: make_plan(firmware, doc, destination, preamp, cancelled, progress),
                   received, with_progress=True)

    def edit_metadata(self):
        if not self.firmware or not self.firmware.profiles:
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("编辑固件信息")
        dialog.resize(850, 650)
        layout = QtWidgets.QVBoxLayout(dialog)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        body = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(body)
        inputs = {}
        known = metadata.fields(self.firmware.package)
        for field in known:
            value = self.session.metadata_edits.get(field["id"], field["value"])
            entry = QtWidgets.QLineEdit(value)
            entry.setReadOnly(not field.get("editable", True))
            if field.get("editable", True):
                inputs[field["id"]] = entry
            label = field["label"]
            if field["kind"] in ("text", "fixed_text"):
                label += f"（最多 {field['width']} 字节）"
            form.addRow(label, entry)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        note = QtWidgets.QLabel("文本按原字段容量保存；校验值和长度由封包自动计算。软件版本会同步 SW_VER 和运行时 getter。")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        edits = {f["id"]: inputs[f["id"]].text() for f in known if f["id"] in inputs
                 and inputs[f["id"]].text() != f["value"]}
        try:
            self.set_metadata_edits(edits)
        except (ValueError, UnicodeError) as exc:
            self.statusBar().showMessage(f"固件信息未应用：{exc}")

    def set_metadata_edits(self, edits):
        if not self.firmware or not self.firmware.profiles:
            raise ValueError("请先打开已确认的固件。")
        metadata.apply_raw(self.firmware.package, bytearray(self.firmware.package["raw"]), edits)
        self.session.set_metadata(edits)
        self._changed()

    def clear_firmware_edits(self):
        self.session.clear_firmware_edits()
        self._changed()

    def start_firmware_export(self):
        if not self.firmware or self.workers:
            return
        if not self.session.firmware_plans and not self.session.metadata_edits:
            self.statusBar().showMessage("先拟合到固件预设，或编辑固件信息。")
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("导出固件")
        form = QtWidgets.QFormLayout(dialog)
        values = [v for p in self.session.firmware_plans for r in p["records"]
                  for v in r["record"]["metrics"].values()]
        summary = "仅修改固件信息" if not values else (
            f"已准备 {len(self.session.firmware_plans)} 个预设；三采样率最差 RMS "
            f"{max(v['rms_db'] for v in values):.3f} / 最大 {max(v['max_db'] for v in values):.3f} dB")
        note = QtWidgets.QLabel(summary+"。导出时按实际写入参数重新计算误差。")
        note.setWordWrap(True)
        form.addRow(note)
        rms, peak = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
        for spin, limit, value in ((rms, 20, .45), (peak, 60, 1.5)):
            spin.setRange(.01, limit)
            spin.setDecimals(2)
            spin.setValue(value)
            spin.setSuffix(" dB")
            spin.setEnabled(bool(values))
        form.addRow("允许 RMS 误差", rms)
        form.addRow("允许最大误差", peak)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        original = Path(self.firmware.path)
        output = QtWidgets.QFileDialog.getSaveFileName(self, "导出修改后的固件",
                  str(original.with_name(original.stem+"-edited.bin")), "固件 (*.bin);;所有文件 (*)")[0]
        if output:
            self.export_to_path(output, rms.value(), peak.value())

    def export_to_path(self, output, max_rms=.45, max_error=1.5):
        if not self.firmware or self.workers:
            return
        firmware = self.firmware
        plans, edits = copy.deepcopy(self.session.firmware_plans), dict(self.session.metadata_edits)
        self.fit_cancel = threading.Event()
        cancelled = self.fit_cancel
        def received(report):
            self.last_export_report = report
            try:
                atomic_json(str(output)+".report.json", report)
                self.statusBar().showMessage(f"已导出 {Path(output).name}，并保存逐路径验证报告。")
            except OSError as exc:
                self.statusBar().showMessage(f"固件已导出，报告保存失败：{exc}")
        self._task(lambda: export_firmware(firmware, plans, edits, output, cancelled, max_rms, max_error), received)

    def start_fit(self):
        a, b = self.measurement_combo.currentIndex(), self.target_combo.currentIndex()
        if a < 0 or b < 0:
            self.statusBar().showMessage("请选择原始频响与目标频响。")
            return
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("频响生成修正 EQ")
        form = QtWidgets.QFormLayout(dialog)
        mode = QtWidgets.QComboBox()
        mode.addItems(["RAW", "PEQ"])
        low, high = QtWidgets.QDoubleSpinBox(), QtWidgets.QDoubleSpinBox()
        for spin, value in ((low, 20), (high, 20000)):
            spin.setRange(20, 20000)
            spin.setValue(value)
        count = QtWidgets.QSpinBox()
        count.setRange(1, 20)
        count.setValue(8)
        strength = QtWidgets.QSpinBox()
        strength.setRange(1, 100)
        strength.setValue(100)
        boost = QtWidgets.QDoubleSpinBox()
        boost.setRange(.1, 60)
        boost.setValue(12)
        align = QtWidgets.QCheckBox("按 1 kHz 对齐整体电平")
        align.setChecked(True)
        for title, widget in (("模式", mode), ("起始 Hz", low), ("结束 Hz", high),
                               ("PEQ 数量", count), ("强度 %", strength), ("最大提升 dB", boost)):
            form.addRow(title, widget)
        form.addRow(align)
        note = QtWidgets.QLabel("生成结果替换当前修正 EQ，可撤销；不需要打开固件。")
        note.setWordWrap(True)
        form.addRow(note)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.StandardButton.Ok |
                                             QtWidgets.QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return
        options = FitOptions(low.value(), high.value(), 1000 if align.isChecked() else None,
                             strength.value()/100, max_boost=boost.value(), filters=count.value())
        self.fit_measurements(self.measurements[a], self.targets[b], mode.currentText(), options)

    def fit_measurements(self, original, target, mode, options):
        if self.workers:
            return
        generation = self.edit_generation
        original, target = copy.deepcopy(original), copy.deepcopy(target)
        self.fit_cancel = threading.Event()
        def received(result):
            if generation != self.edit_generation:
                self.statusBar().showMessage("拟合期间输入发生变化，结果未覆盖当前编辑。")
                return
            doc, report = result
            self.set_document(doc)
            self.fit_report = report
            text = " · ".join(f"{rate} Hz: RMS {v['rms_db']:.3f} / 最大 {v['max_db']:.3f} dB"
                               for rate, v in report["rates"].items())
            self.quality_label.setText("相对于平滑/限幅后的期望修正："+text)
            self.tabs.setCurrentIndex(1)
        self._task(lambda: fit_response(original, target, mode, options, self.fit_cancel), received)

    def open_firmware(self):
        path = self._choose("打开固件")
        if path:
            self._task(lambda: inspect_firmware(path), self.set_firmware)

    def set_firmware(self, firmware):
        if self.session.firmware_sha256 not in (None, firmware.sha256):
            raise ValueError("工程绑定另一个固件；请打开原固件，或新建工程后切换。")
        bound_selection = dict(self.session.online_selection) if self.session.firmware_sha256 == firmware.sha256 else {}
        self.firmware = firmware
        self.session.firmware_sha256 = firmware.sha256
        self.session.firmware_path = firmware.path
        self.path_combo.blockSignals(True)
        self.path_combo.clear()
        if firmware.profiles:
            self.path_combo.addItems([t["name"] for t in firmware.profiles["tables"]])
        self.path_combo.blockSignals(False)
        self.metadata_text.setPlainText(json.dumps(firmware.package["summary"], ensure_ascii=False, indent=2))
        self.device = device_identity(firmware)
        self.desired_selection = self.memory.selection(self.device["key"]) or bound_selection
        self._changed()
        self.statusBar().showMessage(firmware.recognition)
        if self.flowmix_client:
            self.set_online_sources(self.sources)
        else:
            self.connect_flowmix()

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
        self._preview_document = None
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
        self.fill_curves(self.measurement_combo, self.measurements,
                         self.measurements.index(curves[0]) if curves else -1)
        self.curve_selection_changed()
        self.statusBar().showMessage(f"已导入 {len(curves)} 条实测。")

    def new_project(self):
        if self.workers:
            return
        self.session = Session()
        self._preview_document = None
        self.firmware = None
        self.device = None
        self.restore_curves()
        self.path_combo.clear()
        self.metadata_text.clear()
        self._changed()

    def open_project(self):
        path = self._choose("打开工程", "HeyTap 工程 (*.json)")
        if path:
            try:
                self.session.restore(path, self.firmware.sha256 if self.firmware else None)
                self.restore_curves()
                self._changed()
                self.reset_plots()
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

    def editor_event(self, event):
        """Preview a gesture without checkpoints; commit only its final event."""
        try:
            op = event["op"]
            if op == "begin":
                self._preview_document = copy.deepcopy(self.session.document)
                self.edit_generation += 1
                self.fit_report = None
                return
            doc = copy.deepcopy(self.session.document)
            if op == "add":
                new_id = max((f.id for f in doc.filters), default=0)+1
                doc.filters.append(Filter(new_id, float(event["frequency"]),
                                          float(event["gain"]), .7))
            elif op in ("filter", "raw", "delete"):
                index = event["index"]
                if type(index) is not int or index < 0:
                    raise ValueError("Invalid editor index")
                if op == "filter":
                    data = event["filter"]
                    original = doc.filters[index]
                    doc.filters[index] = Filter(original.id, float(data["frequency"]),
                        float(data["gain"]), float(data["q"]), data["kind"], data["enabled"])
                elif op == "raw":
                    doc.raw[index][1] = float(event["gain"])
                else:
                    del doc.filters[index]
            else:
                raise ValueError("Unknown editor operation")
            doc.validate()
            phase = event.get("phase", "end")
            if phase not in ("change", "end"):
                raise ValueError("Invalid edit phase")
            if phase == "change":
                self._preview_document = doc
                if not self.preview_timer.isActive():
                    self.preview_timer.start()
            else:
                self.preview_timer.stop()
                self.set_document(doc)
        except (ValueError, IndexError, KeyError, TypeError, OverflowError) as exc:
            self._preview_document = None
            self.preview_timer.stop()
            self.refresh()
            self.statusBar().showMessage(f"图形参数未应用：{exc}")

    def add_filter(self):
        doc = copy.deepcopy(self.session.document)
        new_id = max((f.id for f in doc.filters), default=0)+1
        frequency = 1000.
        while any(abs(f.frequency-frequency) < 1 for f in doc.filters) and frequency < 16000:
            frequency *= 1.25
        doc.filters.append(Filter(new_id, frequency, 0, .7))
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
        self._preview_document = None
        self.session.undo()
        self._changed()

    def redo(self):
        self._preview_document = None
        self.session.redo()
        self._changed()

    def _changed(self):
        self.edit_generation += 1
        self.fit_report = None
        self.quality_label.setText("估计 = 所选实测 + 当前修正；尚未包含导入固件相对测量固件的差异。")
        self.session.measurements, self.session.targets = self.measurements, self.targets
        self.session.measurement_index = self.measurement_combo.currentIndex()
        self.session.target_index = self.target_combo.currentIndex()
        self.refresh()
        try:
            self.session.save(self.auto_path)
        except OSError as exc:
            self.statusBar().showMessage(f"自动保存失败：{exc}")

    def refresh(self, *_):
        if not hasattr(self, "gains_label"):
            return
        doc = self._preview_document or self.session.document
        writable = bool(self.firmware and self.firmware.profiles)
        for action in self.firmware_actions:
            action.setEnabled(writable)
        queued = ", ".join(p["destination"]+" ← "+p["eq"]["name"] for p in self.session.firmware_plans)
        self.firmware_edits_label.setText("待导出预设："+(queued or "无")+
                                         f" · 元数据修改 {len(self.session.metadata_edits)} 项")
        if self.firmware:
            self.metadata_text.setPlainText(json.dumps({"original": self.firmware.package["summary"],
                "pending_presets": [{"destination": p["destination"], "eq": p["eq"]["name"],
                                     "records": len(p["records"])} for p in self.session.firmware_plans],
                "pending_metadata": self.session.metadata_edits}, ensure_ascii=False, indent=2))
        frequency = np.geomspace(20, 20000, 4096)
        fs = int(self.rate_combo.currentText())
        self.digital_plot.clear_curves()
        raw_doc = copy.deepcopy(doc)
        raw_doc.filters = []
        raw_values = correction(raw_doc, frequency, fs)
        self.digital_plot.zero_line()
        if doc.raw or doc.filters:
            self.digital_plot.plot(frequency, correction(doc, frequency, fs),
                                   color="#efb55a", name="当前修正 RAW + PEQ")
        self._peq_map = [i for i, f in enumerate(doc.filters) if f.enabled]
        record = None
        if self.firmware and self.firmware.profiles and self.path_combo.currentIndex() >= 0:
            bank = self.firmware.profiles
            table = bank["tables"][self.path_combo.currentIndex()]
            name = self.preset_combo.currentText()
            index = 45 if name == "特殊记录 45" else PRESETS[name]+self.state_combo.currentIndex()
            record = bank["profiles"][table["profile_indices"][index]]
            self.digital_plot.plot(frequency, firmware_curve(record, frequency, fs),
                                   color="#67afd1", name="固件滤波链 · 不含整体增益")
            plan = next((p for p in self.session.firmware_plans if p["destination"] == name), None)
            if plan:
                planned = next(c["record"] for c in plan["records"] if c["table"] == table["name"]
                               and c["state"] == self.state_combo.currentIndex())
                self.digital_plot.plot(frequency, firmware_response(planned["filters"], frequency, fs),
                                       color="#32cbb9", name="待导出固件滤波链")
        for name, button in self.preset_buttons.items():
            button.setChecked(name == self.preset_combo.currentText())
            button.setEnabled(self.firmware is not None and self.firmware.profiles is not None)
        label = "未打开固件 · 可直接导入频响或编辑 EQ"
        if self.firmware:
            label = f"{Path(self.firmware.path).name} · {self.firmware.recognition}"
            self.firmware_label.setToolTip(f"{self.firmware.path}\nSHA-256 {self.firmware.sha256}")
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
        self.acoustic_plot.clear_curves()
        acoustic_base = np.zeros_like(frequency)
        relative = self.relative_check.isChecked()
        if relative:
            self.acoustic_plot.zero_line()
        def displayed(curve):
            values = np.asarray(curve.spl_values)
            if relative and curve.frequencies[0] <= 1000 <= curve.frequencies[-1]:
                values = values-np.interp(np.log(1000), np.log(curve.frequencies), values)
            return values
        if self.measurements and self.measurement_combo.currentIndex() >= 0:
            m = self.measurements[self.measurement_combo.currentIndex()]
            x = np.asarray(m.frequencies)
            values = displayed(m)
            acoustic_base = np.interp(np.log(frequency), np.log(x), values)
            if self.curve_checks["original"].isChecked():
                self.acoustic_plot.plot(x, values, color="#759ecb", name="原始实测")
            if self.curve_checks["estimated"].isChecked():
                self.acoustic_plot.plot(frequency, np.interp(np.log(frequency), np.log(x), values)+correction(doc, frequency, fs),
                                        color="#32cbb9", name="实测＋当前修正估计")
        if self.targets and self.target_combo.currentIndex() >= 0 and self.curve_checks["target"].isChecked():
            target = self.targets[self.target_combo.currentIndex()]
            self.acoustic_plot.plot(target.frequencies, displayed(target),
                color="#e3ad55", dashed=True, name="目标频响")

        filters = [asdict(f) for f in doc.filters]
        self.digital_plot.set_editor(label="修正 EQ 与所选固件链", filters=filters, raw=doc.raw,
            nodeBase=np.column_stack((frequency, raw_values)).tolist(), rawBase=[],
            addBase=np.column_stack((frequency, correction(doc, frequency, fs))).tolist(),
            empty="双击添加 PEQ，或导入 EQ。打开固件后可在这里检查两路数字滤波链。")
        self.acoustic_plot.set_editor(label="频响与调音", filters=filters, raw=doc.raw,
            nodeBase=np.column_stack((frequency, acoustic_base+raw_values)).tolist(),
            rawBase=np.column_stack((frequency, acoustic_base)).tolist(),
            addBase=np.column_stack((frequency, acoustic_base+correction(doc, frequency, fs))).tolist(),
            empty="选择或导入原始测量，再调曲线。也可以直接双击添加 PEQ。")

    def closeEvent(self, event):
        if self.workers or self.network_workers:
            self.statusBar().showMessage("正在读取文件，完成后即可关闭窗口。")
            event.ignore()
        else:
            event.accept()
