"""Remember explicit browser choices; match only confirmed device identities."""

import json
import re
from pathlib import Path

from heytap_eq.session import atomic_json

FILE_DIALOG_KINDS = frozenset({"project_open", "project_save", "firmware_open", "firmware_export",
                               "eq_import", "eq_export", "measurement_import", "target_import",
                               "mapping_import"})


class FileDialogMemory:
    """Application preferences: independent directories, never project or undo state."""

    def __init__(self, path):
        self.path = Path(path)
        self.directories = {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))["directories"]
            self.directories = {key: value for key, value in data.items()
                                if key in FILE_DIALOG_KINDS and isinstance(value, str)
                                and len(value) <= 8192 and Path(value).is_absolute()}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass

    def directory(self, kind, fallback=""):
        if kind not in FILE_DIALOG_KINDS:
            raise ValueError("Unknown file dialog category")
        for candidate in (self.directories.get(kind, ""), fallback):
            try:
                if candidate and Path(candidate).is_dir():
                    return str(candidate)
            except OSError:
                pass
        return ""

    def remember(self, kind, selected):
        if kind not in FILE_DIALOG_KINDS:
            raise ValueError("Unknown file dialog category")
        if selected:
            self.directories[kind] = str(Path(selected).absolute().parent)
            atomic_json(self.path, {"directories": self.directories})


def normalized(value):
    return re.sub(r"[^\w]", "", value.casefold()).replace("_", "")


def unique_match(entries, names):
    wanted = {normalized(x) for x in names}
    matches = [e for e in entries if normalized(e["name"]) in wanted
               or normalized(e["display"]) in wanted]
    return matches[0]["name"] if len(matches) == 1 else None


def device_identity(firmware):
    if firmware.profiles and firmware.package["summary"]["product_id"] == "06EC10":
        return {"brand": ["OPPO"], "model": ["OPPO Enco X4", "Enco X4"],
                "key": "product:06EC10"}
    return {"key": "sha256:"+firmware.sha256}


def validate_selection(value):
    if not isinstance(value, dict) or set(value) - {"source", "brand", "headphone"}:
        raise ValueError("Invalid measurement selection")
    if any(v is not None and (not isinstance(v, str) or len(v) > 1024)
           for v in value.values()):
        raise ValueError("Invalid measurement selection value")
    return {key: value.get(key) for key in ("source", "brand", "headphone")}


class BrowserMemory:
    def __init__(self, path):
        self.path = Path(path)
        self.last = {}
        self.devices = {}
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.last = validate_selection(data.get("last", {}))
                self.devices = {k: validate_selection(v) for k, v in data.get("devices", {}).items()
                                if isinstance(k, str)}
            except (OSError, ValueError, TypeError, AttributeError):
                self.last, self.devices = {}, {}

    def selection(self, key=None):
        return dict(self.devices.get(key, {}) if key else self.last)

    def remember(self, value, key=None):
        value = validate_selection(value)
        self.last = value
        if key:
            self.devices[key] = value
        atomic_json(self.path, {"last": self.last, "devices": self.devices})

