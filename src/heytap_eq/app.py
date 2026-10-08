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
    if args.smoke_test and args.report is None:
        parser.error("--smoke-test requires --report")
    os.environ["PYQTGRAPH_QT_LIB"] = "PySide6"
    from PySide6 import QtCore, QtWidgets

    from heytap_eq.gui import MainWindow

    app = QtWidgets.QApplication([sys.argv[0]])
    app.setApplicationName("HeyTap Firmware EQ Studio")
    app.setOrganizationName("HeyTapEQStudio")
    auto_path = args.report.parent/"smoke-project.json" if args.smoke_test else None
    window = MainWindow(recover=not args.smoke_test, auto_path=auto_path)
    window.show()
    result = 0
    if args.smoke_test:
        from heytap_eq.eq_formats import Filter, parse_text
        from heytap_eq.measurements import Measurement

        preview = parse_text("GraphicEQ: 20 0; 100 -1; 1000 2; 5000 -2; 20000 0", "Synthetic preview")
        preview.filters.append(Filter(1, 1000, 2, .7))
        window.set_document(preview)
        window.set_measurements([Measurement("Synthetic test fixture", [20, 1000, 20000], [80, 90, 80]).validate()])

        window.set_targets([Measurement("Synthetic target", [20, 1000, 20000], [83, 90, 78]).validate()])
        window.tabs.setCurrentIndex(1)

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
                    "screenshot": image.name, "raw_points": len(window.session.document.raw),
                    "peq_filters": len(window.session.document.filters),
                    "measurements": len(window.measurements), "targets": len(window.targets),
                    "apk_dependency": False,
                    "service_configured": __import__("heytap_eq.service_profile", fromlist=["builtin_authorization"]).builtin_authorization() is not None,
                    "firmware_export_available": callable(getattr(window, "export_to_path", None)),
                    "metadata_editor_available": callable(getattr(window, "set_metadata_edits", None)),
                    "project_schema": "heytap-project-v3",
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
