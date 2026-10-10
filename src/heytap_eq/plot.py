"""Desktop colors shared by the Qt shell and embedded editor."""

DARK_STYLE = """
QMainWindow, QWidget { background: #171d26; color: #dce4ef; font-size: 12px; }
QToolBar { background: #202836; border: 0; spacing: 8px; padding: 5px; }
QToolButton, QPushButton { background: #263243; border: 1px solid #3d4d63;
                          border-radius: 4px; padding: 6px 10px; }
QPushButton:disabled { color: #718197; background: #1d2633; border-color: #293647; }
QPushButton:hover, QToolButton:hover { background: #35475e; }
QPushButton:checked { background: #174b50; border-color: #35c5b7; color: #59e1d3; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { background: #202936;
    border: 1px solid #3d4d63; border-radius: 3px; padding: 4px; }
QTableWidget, QPlainTextEdit { background: #12171e; gridline-color: #2e3b4c;
    border: 1px solid #334256; selection-background-color: #24555c; }
QHeaderView::section { background: #263243; color: #c8d6e7; padding: 5px; border: 0; }
QTabBar::tab { background: #202936; padding: 7px 14px; border: 1px solid #334256; }
QTabBar::tab:selected { background: #174b50; color: #59e1d3; }
QMenu, QMenuBar { background: #202836; color: #dce4ef; }
QMenu::item:selected, QMenuBar::item:selected { background: #35475e; }
QStatusBar { background: #12171e; color: #adbdcf; }
QSplitter::handle { background: #334256; }
QCheckBox { spacing: 5px; }
QScrollBar:vertical { background: #202936; width: 12px; }
"""
