"""Run the actual packaged Windows executable, requiring its event-loop report."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

from heytap_eq.service_profile import builtin_authorization

exe = Path("dist/HeyTapFirmwareEQStudio/HeyTapFirmwareEQStudio.exe").resolve()
report = Path("reports/frozen-startup.json").resolve()
report.parent.mkdir(exist_ok=True)
report.unlink(missing_ok=True)
subprocess.run([str(exe), "--smoke-test", "--report", str(report)], check=True, timeout=60)
data = json.loads(report.read_text())
assert data["status"] == "passed" and data["frozen"] and data["window_visible"]
assert data["sha"] == os.environ["HEYTAP_BUILD_SHA"]
assert data["firmware_export_available"] and data["metadata_editor_available"]
assert data["project_schema"] == "heytap-project-v3"
assert not data["apk_dependency"]
assert data["plot_engine"] == "DSSSP 0.8.0"
assert data["web_editor"]["ready"] and data["web_editor"]["svgPaths"] >= 3
assert data["service_configured"] == (builtin_authorization() is not None)
data["executable_sha256"] = hashlib.sha256(exe.read_bytes()).hexdigest()
report.write_text(json.dumps(data, indent=2))
