"""Numeric measurement imports; HAR request headers never enter the result."""

import base64
import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Measurement:
    title: str
    frequencies: list[float]
    spl_values: list[float]
    source: str = "Offline file"
    date: str | None = None
    firmware_version: str | None = None
    measurement_id: str | None = None
    content_version: str | int | None = None

    def validate(self):
        if len(self.frequencies) != len(self.spl_values) or len(self.frequencies) < 2:
            raise ValueError("Measurement arrays must have equal lengths and at least two points")
        previous = 0
        for f, spl in zip(self.frequencies, self.spl_values):
            if not (math.isfinite(f) and math.isfinite(spl) and previous < f):
                raise ValueError("Measurement frequencies must strictly increase; values must be finite")
            previous = f
        return self


def parse_json(data):
    if isinstance(data, dict) and "success" in data:
        if data["success"] is not True:
            raise ValueError("Measurement response did not report success")
        data = data["data"]
    if not isinstance(data, dict):
        raise ValueError("Measurement object expected")
    conditions = data.get("frequencyData")
    if conditions is None:
        conditions = {data.get("title", "Measurement"): data}
    if not isinstance(conditions, dict) or not conditions:
        raise ValueError("No measurement conditions")
    results = []
    for name, condition in conditions.items():
        results.append(Measurement(
            str(condition.get("title", name)), [float(v) for v in condition["frequencies"]],
            [float(v) for v in condition["spl_values"]], str(data.get("sourceName", "Offline file")),
            data.get("lastUpdated"), data.get("firmware_version"),
            condition.get("measurement_id"), condition.get("content_version"),
        ).validate())
    return results


def parse_har(data):
    results = []
    for entry in data["log"]["entries"]:
        content = entry.get("response", {}).get("content", {})
        if "html" not in content.get("mimeType", "").lower():
            continue
        text = content.get("text", "")
        if content.get("encoding") == "base64":
            text = base64.b64decode(text).decode("utf-8")
        match = re.search(r"window\.__INITIAL_DATA__\s*=\s*", text)
        if not match:
            continue
        payload, _ = json.JSONDecoder().raw_decode(text[match.end():].lstrip())
        page = payload.get("Data", {})
        for curve in page.get("data", []):
            title = curve.get("title", "")
            if "B&K5128" not in title.replace(" ", "") or "THD" in title:
                continue
            points = []
            for row in curve["data"]:
                try:
                    f, spl = float(row[0]), float(row[1])
                except (ValueError, TypeError, IndexError):
                    continue
                if f > 0:
                    points.append((f, spl))
            if not points:
                continue
            results.append(Measurement(title, [p[0] for p in points], [p[1] for p in points],
                                       "ReaLab · B&K 5128", str(page.get("time", ""))).validate())
    if not results:
        raise ValueError("No recognized ReaLab frequency response in HAR")
    return results


def load_measurements(path):
    path = Path(path)
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            names = reader.fieldnames or []
            frequency = next((x for x in ("frequency_hz", "frequency", "frequencies") if x in names), None)
            spl = next((x for x in ("spl_db", "spl", "spl_values") if x in names), None)
            if frequency is None or spl is None:
                raise ValueError("CSV needs frequency_hz and spl_db columns")
            points = [(float(r[frequency]), float(r[spl])) for r in reader]
        return [Measurement(path.stem, [p[0] for p in points], [p[1] for p in points]).validate()]
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return parse_har(data) if path.suffix.lower() == ".har" else parse_json(data)
