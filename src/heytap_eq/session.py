"""Atomic projects; validate a recovery fully before changing the current session."""

import copy
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from heytap_eq.eq_formats import EQDocument
from heytap_eq.firmware_edit import plan_shape
from heytap_eq.measurements import Measurement


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name+".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Session:
    def __init__(self):
        self.document = EQDocument()
        self.firmware_sha256 = None
        self.firmware_path = None
        self.measurements = []
        self.targets = []
        self.measurement_index = -1
        self.target_index = -1
        self.online_selection = {}
        self.firmware_plans = []
        self.metadata_edits = {}
        self._undo = []
        self._redo = []

    def replace(self, doc):
        data = doc.to_dict()
        if self.document.to_dict() == data:
            return
        self._checkpoint()
        self.document = EQDocument.from_dict(data)

    def snapshot(self):
        return {"eq": self.document.to_dict(), "firmware_plans": copy.deepcopy(self.firmware_plans),
                "metadata_edits": dict(self.metadata_edits)}

    def _checkpoint(self):
        self._undo.append(self.snapshot())
        self._undo = self._undo[-100:]
        self._redo.clear()

    def _apply_snapshot(self, data):
        self.document = EQDocument.from_dict(data["eq"])
        self.firmware_plans = copy.deepcopy(data["firmware_plans"])
        self.metadata_edits = dict(data["metadata_edits"])

    def stage_plan(self, plan):
        plan_shape(plan)
        if plan["firmware_sha256"] != self.firmware_sha256:
            raise ValueError("Firmware plan is bound to another firmware")
        self._checkpoint()
        self.firmware_plans = [p for p in self.firmware_plans if p["destination"] != plan["destination"]]
        self.firmware_plans.append(copy.deepcopy(plan))

    def set_metadata(self, edits):
        if edits != self.metadata_edits:
            self._checkpoint()
            self.metadata_edits = dict(edits)

    def clear_firmware_edits(self):
        if self.firmware_plans or self.metadata_edits:
            self._checkpoint()
            self.firmware_plans, self.metadata_edits = [], {}

    def undo(self):
        if self._undo:
            self._redo.append(self.snapshot())
            self._apply_snapshot(self._undo.pop())

    def redo(self):
        if self._redo:
            self._undo.append(self.snapshot())
            self._apply_snapshot(self._redo.pop())

    def save(self, path):
        atomic_json(path, {"schema": "heytap-project-v3", "firmware_sha256": self.firmware_sha256,
                           "firmware_path": self.firmware_path, "eq": self.document.to_dict(),
                           "measurements": [asdict(m.validate()) for m in self.measurements],
                           "targets": [asdict(m.validate()) for m in self.targets],
                           "measurement_index": self.measurement_index,
                           "target_index": self.target_index,
                           "online_selection": self.online_selection,
                           "firmware_plans": self.firmware_plans,
                           "metadata_edits": self.metadata_edits})

    def restore(self, path, expected_sha=None):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data["schema"] not in ("heytap-project-v1", "heytap-project-v2", "heytap-project-v3"):
            raise ValueError("Unsupported project format")
        if expected_sha is not None and data["firmware_sha256"] != expected_sha:
            raise ValueError("Project is bound to a different firmware SHA-256")
        doc = EQDocument.from_dict(data["eq"])
        digest = data["firmware_sha256"]
        if digest is not None and (not isinstance(digest, str) or len(digest) != 64
                                   or any(x not in "0123456789abcdef" for x in digest)):
            raise ValueError("Invalid project firmware SHA-256")
        firmware_path = data["firmware_path"]
        if firmware_path is not None and not isinstance(firmware_path, str):
            raise ValueError("Invalid project firmware path")
        curves = {}
        for key in ("measurements", "targets"):
            values = data.get(key, [])
            if not isinstance(values, list) or len(values) > 500:
                raise ValueError("Invalid project measurements")
            curves[key] = [Measurement(**v).validate() for v in values]
        indices = {}
        for key, values in curves.items():
            name = "measurement_index" if key == "measurements" else "target_index"
            value = data.get(name, -1)
            if type(value) is not int or not -1 <= value < max(1, len(values)):
                raise ValueError("Invalid project curve selection")
            if not values and value != -1:
                raise ValueError("Selected measurement is missing")
            indices[name] = value
        selection = data.get("online_selection", {})
        if (not isinstance(selection, dict) or set(selection) - {"source", "brand", "headphone"}
                or any(v is not None and not isinstance(v, str) for v in selection.values())):
            raise ValueError("Invalid project browser selection")
        plans = data.get("firmware_plans", [])
        if not isinstance(plans, list) or len(plans) > 5:
            raise ValueError("Invalid project firmware plans")
        destinations = set()
        for plan in plans:
            plan_shape(plan)
            if plan["firmware_sha256"] != digest or plan["destination"] in destinations:
                raise ValueError("Invalid project firmware binding or duplicate preset")
            destinations.add(plan["destination"])
        edits = data.get("metadata_edits", {})
        if (not isinstance(edits, dict) or len(edits) > 250 or
                any(not isinstance(k, str) or not isinstance(v, str) or
                    any(ord(c) < 32 or ord(c) > 126 for c in v) for k, v in edits.items())):
            raise ValueError("Invalid project metadata edits")
        if (plans or edits) and digest is None:
            raise ValueError("Firmware edits must bind to an input SHA-256")
        self.document = doc
        self.firmware_sha256 = digest
        self.firmware_path = firmware_path
        self.measurements, self.targets = curves["measurements"], curves["targets"]
        self.measurement_index, self.target_index = indices.values()
        self.online_selection = selection
        self.firmware_plans = copy.deepcopy(plans)
        self.metadata_edits = dict(edits)
        self._undo.clear()
        self._redo.clear()
