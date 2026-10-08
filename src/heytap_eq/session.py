"""Atomic projects; validate a recovery fully before changing the current session."""

import json
import os
import tempfile
from pathlib import Path

from heytap_eq.eq_formats import EQDocument


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
        self._undo = []
        self._redo = []

    def replace(self, doc):
        data = doc.to_dict()
        before = self.document.to_dict()
        if before == data:
            return
        self._undo.append(before)
        self._undo = self._undo[-100:]
        self._redo.clear()
        self.document = EQDocument.from_dict(data)

    def undo(self):
        if self._undo:
            self._redo.append(self.document.to_dict())
            self.document = EQDocument.from_dict(self._undo.pop())

    def redo(self):
        if self._redo:
            self._undo.append(self.document.to_dict())
            self.document = EQDocument.from_dict(self._redo.pop())

    def save(self, path):
        atomic_json(path, {"schema": "heytap-project-v1", "firmware_sha256": self.firmware_sha256,
                           "firmware_path": self.firmware_path, "eq": self.document.to_dict()})

    def restore(self, path, expected_sha=None):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data["schema"] != "heytap-project-v1":
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
        self.document = doc
        self.firmware_sha256 = digest
        self.firmware_path = firmware_path
        self._undo.clear()
        self._redo.clear()
