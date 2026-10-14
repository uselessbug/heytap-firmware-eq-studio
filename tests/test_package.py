import subprocess
import sys


def test_core_import_does_not_load_qt():
    subprocess.run([sys.executable, "-c", (
        "import sys, heytap_eq; assert not any(k.startswith(('PySide', 'PyQt')) "
        "for k in sys.modules)"
    )], check=True)
