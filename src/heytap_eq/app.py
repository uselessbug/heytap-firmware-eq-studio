"""Desktop entry and a bounded startup probe shared by source and frozen builds."""

import argparse
import json
import os
import sys
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
    from PySide6 import QtCore, QtWidgets

    from heytap_eq.gui import MainWindow

    app = QtWidgets.QApplication([sys.argv[0]])
    app.setApplicationName("HeyTap Firmware EQ Studio")
    app.setOrganizationName("HeyTapEQStudio")
    window = MainWindow()
    window.show()
    result = 0
    if args.smoke_test:
        if args.report is None:
            parser.error("--smoke-test requires --report")

        def probe():
            nonlocal result
            try:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                image = args.report.with_suffix(".png")
                assert window.isVisible() and window.width() >= 600
                assert window.grab().save(str(image))
                assert not any(k.startswith(("PyQt5", "PyQt6", "PySide2")) for k in sys.modules)
                args.report.write_text(json.dumps({
                    "status": "passed", "frozen": bool(getattr(sys, "frozen", False)),
                    "qt": QtCore.qVersion(), "qt_binding": "PySide6",
                    "sha": os.environ.get("HEYTAP_BUILD_SHA"), "window_visible": True,
                    "screenshot": image.name,
                }, indent=2), encoding="utf-8")
            except Exception as exc:
                result = 1
                args.report.write_text(json.dumps({"status": "failed", "error": str(exc)}))
            finally:
                app.quit()

        QtCore.QTimer.singleShot(500, probe)
    app.exec()
    return result


if __name__ == "__main__":
    raise SystemExit(main())
