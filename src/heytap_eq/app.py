"""Desktop entry and a bounded startup probe shared by source and frozen builds."""

import argparse
import json
import os
import sys
from pathlib import Path

from heytap_eq.runtime import is_packaged, packager


def main(argv=None):
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--smoke-test", action="store_true")
    mode.add_argument("--benchmark", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if (args.smoke_test or args.benchmark) and args.report is None:
        parser.error("--smoke-test and --benchmark require --report")
    if args.benchmark:
        from heytap_eq.benchmark import run_benchmark

        return run_benchmark(args.report)
    from PySide6 import QtCore, QtWidgets

    from heytap_eq.gui import MainWindow
    from heytap_eq.web_plot import initialize_web_engine

    initialize_web_engine()
    app = QtWidgets.QApplication([sys.argv[0]])
    app.setApplicationName("HeyTap Firmware EQ Studio")
    app.setOrganizationName("HeyTapEQStudio")
    # Fusion draws style sheets and palettes the same way on every platform and theme.
    app.setStyle("Fusion")
    translator = QtCore.QTranslator(app)
    translated = translator.load(QtCore.QLocale("zh_CN"), "qtbase", "_",
                                 QtCore.QLibraryInfo.path(QtCore.QLibraryInfo.LibraryPath.TranslationsPath))
    if translated:
        app.installTranslator(translator)
    auto_path = args.report.parent/"smoke-project.json" if args.smoke_test else None
    window = MainWindow(recover=not args.smoke_test, auto_path=auto_path)
    app.aboutToQuit.connect(window.deleteLater)
    window.show()
    result = 0
    if args.smoke_test:
        from heytap_eq.eq_formats import parse_text
        from heytap_eq.estimation import builtin_reference
        from heytap_eq.measurements import Measurement, parse_table

        preview = parse_text("GraphicEQ: 20 0; 100 -1; 1000 2; 5000 -2; 20000 0", "Synthetic preview")
        # Exercise the integrated parsers inside both actual frozen executables.
        imported = parse_text("Preamp: -6.2 dB\n"
                              "Filter 1: ON LSC Fc 105 Hz Gain 6.4 dB Q 0.7\n"
                              "Filter 2: OFF PK Fc 2000 Hz Gain -3.1 dB Q 1.41")
        assert imported.metadata["PREAMP_DB"] == "-6.2"
        assert imported.filters[0].kind == "LS" and not imported.filters[1].enabled
        preview.filters = imported.filters
        preview.metadata = imported.metadata
        table_samples = ("frequency,raw\n20,80\n1000,90\n20000,82",
                         "* REW\n20 80 0\n1000 90 0\n20000 82 0",
                         "Frequency [Hz];SPL [dB]\n20;80\n1000;90\n20000;82")
        assert all(parse_table(text, "Synthetic import").spl_values == [80, 90, 82]
                   for text in table_samples)
        window.set_document(preview)
        assert "-6.2" in window.eq_import_warning.text() and "未应用" in window.eq_import_warning.text()
        window.set_measurements([Measurement("Synthetic test fixture", [20, 1000, 20000], [80, 90, 80]).validate()])

        window.set_targets([Measurement("Synthetic target", [20, 1000, 20000], [83, 90, 78]).validate()])

        # Source and both actual EXEs exercise persistent dialog preferences and live restyling.
        from heytap_eq.preferences import FileDialogMemory

        for kind in ("eq_import", "project_open"):
            folder = (args.report.parent/"dialog-memory-probe"/kind).resolve()
            folder.mkdir(parents=True, exist_ok=True)
            window.file_memory.remember(kind, folder/"sample.txt")
        restored_memory = FileDialogMemory(window.file_memory.path)
        assert restored_memory.directory("eq_import") != restored_memory.directory("project_open")
        assert all(restored_memory.directory(kind) == window.file_memory.directory(kind)
                   for kind in ("eq_import", "project_open"))
        window.set_rail_expanded(True)
        theme_steps = [("dark", "violet", "standard"), ("light", "amber", "high"),
                       ("dark", "blue", "standard")]
        theme_layouts = []
        attempts = 0
        paint_ready = False

        def probe():
            nonlocal result
            nonlocal attempts
            attempts += 1
            if not window.digital_plot.is_ready or not window.acoustic_plot.is_ready:
                if attempts < 200:
                    QtCore.QTimer.singleShot(100, probe)
                    return
                result = 1
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps({"status": "failed", "error": "Web editor did not initialize"}))
                app.quit()
                return
            try:
                viewport = window.rail.viewport()
                assert window.rail.widget().width() == viewport.width()
                assert window.rail.horizontalScrollBar().maximum() == 0
                for card in window.cards.values():
                    point = card.mapTo(viewport, QtCore.QPoint())
                    assert point.x() >= 0 and point.x()+card.width() <= viewport.width()
                width = window.rail.width()
                if theme_layouts:
                    assert abs(width-theme_layouts[0]["rail_width"]) <= 2
                theme_layouts.append({"mode": window.theme["mode"], "accent": window.theme["accent"],
                                      "contrast": window.theme["contrast"], "rail_width": width,
                                      "body_width": window.rail.widget().width(), "viewport_width": viewport.width()})
                if theme_steps:
                    mode, accent, contrast = theme_steps.pop(0)
                    window.set_appearance(mode=mode, accent=accent, contrast=contrast)
                    QtCore.QTimer.singleShot(100, probe)
                    return
                window.acoustic_plot.inspect(finish_probe)
            except Exception as exc:
                result = 1
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(json.dumps({"status": "failed", "error": str(exc),
                                                   "theme_layouts": theme_layouts}))
                app.quit()

        def finish_probe(web):
            nonlocal result
            nonlocal attempts, paint_ready
            attempts += 1
            matches = web and web.get("theme") == window.theme["mode"] \
                and web.get("contrast") == window.theme["contrast"]
            if attempts < 200 and (not matches or not paint_ready):
                paint_ready = bool(matches)
                # DOM inspection can precede WebEngine's compositor repaint, especially
                # in frozen Windows builds. Allow it to paint before grabbing the window.
                QtCore.QTimer.singleShot(250, lambda: window.acoustic_plot.inspect(finish_probe))
                return
            try:
                assert matches and paint_ready, "Web editor did not paint the final theme"
                args.report.parent.mkdir(parents=True, exist_ok=True)
                image = args.report.with_suffix(".png")
                assert window.isVisible() and window.width() >= 600
                assert window.grab().save(str(image))
                assert web and web["ready"] and web["svgPaths"] >= 3, web
                assert web["height"] >= 250, web
                reference = builtin_reference()
                assert reference and len(reference["presets"]) == 6
                assert not any(k.startswith(("PyQt5", "PyQt6", "PySide2")) for k in sys.modules)
                # Packaged builds must ship what the themed shell loads at run time.
                from PySide6 import QtGui

                from heytap_eq.widgets import write_icons

                icons = write_icons(window.theme, args.report.parent/"theme-icons")
                svg_icons = all(not QtGui.QPixmap(path).isNull() for path in icons.values())
                args.report.write_text(json.dumps({
                    "status": "passed", "frozen": is_packaged(), "packager": packager(),
                    "qt": QtCore.qVersion(), "qt_binding": "PySide6",
                    "sha": os.environ.get("HEYTAP_BUILD_SHA"), "window_visible": True,
                    "screenshot": image.name, "raw_points": len(window.session.document.raw),
                    "peq_filters": len(window.session.document.filters),
                    "measurements": len(window.measurements), "targets": len(window.targets),
                    "apk_dependency": False,
                    "service_configured": __import__("heytap_eq.service_profile", fromlist=["builtin_authorization"]).builtin_authorization() is not None,
                    "firmware_export_available": callable(getattr(window, "export_to_path", None)),
                    "metadata_editor_available": callable(getattr(window, "set_metadata_edits", None)),
                    "project_schema": "heytap-project-v4",
                    "single_plot": window.digital_plot is window.acoustic_plot,
                    "reference_template_presets": len(reference["presets"]),
                    "plot_engine": "DSSSP 0.8.0", "web_editor": web,
                    "svg_icons": svg_icons, "qt_translation_zh_CN": translated,
                    "blas_threads": os.environ.get("OPENBLAS_NUM_THREADS"),
                    "third_party_imports": True, "imported_preamp_applied": False,
                    "theme_layout_validated": True, "theme_layouts": theme_layouts,
                    "file_dialog_memory_validated": True,
                }, indent=2), encoding="utf-8")
            except Exception as exc:
                result = 1
                args.report.write_text(json.dumps({"status": "failed", "error": str(exc)}))
            finally:
                app.quit()

        QtCore.QTimer.singleShot(1000, probe)
    else:
        QtCore.QTimer.singleShot(0, window.connect_flowmix)
    app.exec()
    # Flush window/page destruction while QApplication is still alive.
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    return result


if __name__ == "__main__":
    raise SystemExit(main())

