from PySide6 import QtWidgets


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HeyTap Firmware EQ Studio")
        self.resize(1200, 800)
        label = QtWidgets.QLabel("HeyTap Firmware EQ Studio\n打开固件与 EQ 的桌面工作流正在建立。")
        label.setMargin(24)
        self.setCentralWidget(label)
        self.statusBar().showMessage("本地桌面 · Enco X4")
