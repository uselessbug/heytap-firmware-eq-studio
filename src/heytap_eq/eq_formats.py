"""Strict, lossless numeric import of GraphicEQ and Flowmix RAW plus PEQ."""

import hashlib
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

KINDS = ("PEAK", "LS", "HS", "LP", "HP", "NOTCH", "BAND_PASS", "ALL_PASS")
ALIASES = {"PK": "PEAK", "LOW_SHELF": "LS", "HIGH_SHELF": "HS",
           "LOW_PASS": "LP", "HIGH_PASS": "HP", "AP": "ALL_PASS", "BP": "BAND_PASS"}


@dataclass
class Filter:
    id: int
    frequency: float
    gain: float
    q: float
    kind: str = "PEAK"
    enabled: bool = True

    def validate(self):
        if type(self.id) is not int or self.id < 0 or type(self.enabled) is not bool:
            raise ValueError("Invalid PEQ ID or enabled flag")
        if self.kind not in KINDS:
            raise ValueError(f"Unsupported PEQ type: {self.kind}")
        if not all(math.isfinite(x) for x in (self.frequency, self.gain, self.q)):
            raise ValueError("PEQ values must be finite")
        if not (0 < self.frequency < 22050 and abs(self.gain) <= 60 and .01 <= self.q <= 100):
            raise ValueError("PEQ frequency / gain / Q outside supported preview range")


@dataclass
class EQDocument:
    name: str = "Untitled"
    raw: list[list[float]] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)
    source_sha256: str | None = None

    def validate(self):
        if not isinstance(self.name, str) or not isinstance(self.metadata, dict):
            raise ValueError("Invalid EQ name or metadata")
        if any(not isinstance(k, str) or not re.fullmatch(r"[A-Z_0-9]+", k)
               or not isinstance(v, str) or "\n" in v or "\r" in v
               for k, v in self.metadata.items()):
            raise ValueError("Invalid EQ metadata fields")
        if len(self.raw) == 1:
            raise ValueError("GraphicEQ needs at least two points")
        previous = 0
        for point in self.raw:
            if len(point) != 2 or not all(math.isfinite(x) for x in point):
                raise ValueError("Invalid GraphicEQ point")
            frequency, gain = point
            if not (previous < frequency < 22050 and abs(gain) <= 60):
                raise ValueError("GraphicEQ frequencies must strictly increase; gains within ±60 dB")
            previous = frequency
        seen = set()
        for f in self.filters:
            f.validate()
            if f.id in seen:
                raise ValueError(f"Duplicate PEQ ID: {f.id}")
            seen.add(f.id)

    def to_dict(self):
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        obj = cls(**{**data, "filters": [Filter(**f) for f in data["filters"]]})
        obj.validate()
        return obj


def parse_text(text: str, name="Imported EQ") -> EQDocument:
    doc = EQDocument(name=name)
    graphic_seen = False
    started = False
    metadata = {}
    for original in text.lstrip("\ufeff").splitlines():
        line = original.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if not started and not line.startswith("[") and not line.lower().startswith("graphiceq:"):
            continue  # Flowmix exports include a decorative preamble before the first section.
        started = True
        if line.startswith("["):
            if line.upper() not in ("[RAW]", "[PEQ]", "[METADATA]"):
                raise ValueError(f"Unsupported section: {line}")
            continue
        if ":" not in line:
            raise ValueError(f"Malformed EQ line: {line[:80]}")
        key, value = (s.strip() for s in line.split(":", 1))
        key = key.upper()
        if key == "GRAPHICEQ":
            if graphic_seen:
                raise ValueError("Duplicate GraphicEQ line")
            graphic_seen = True
            for pair in value.split(";"):
                if pair.strip():
                    fields = pair.split()
                    if len(fields) != 2:
                        raise ValueError("GraphicEQ point must be frequency and gain")
                    doc.raw.append([float(x) for x in fields])
        elif re.fullmatch(r"PEQ\d+", key):
            fields = value.split()
            if len(fields) not in (3, 4):
                raise ValueError("PEQ requires frequency, gain, Q, and optional type")
            kind = fields[3].upper() if len(fields) == 4 else "PEAK"
            kind = ALIASES.get(kind, kind)
            doc.filters.append(Filter(int(key[3:]), *[float(x) for x in fields[:3]], kind))
        elif key.startswith("PEQ") and key != "PEQ_COUNT":
            raise ValueError("Malformed PEQ key")
        else:
            if key in metadata:
                raise ValueError(f"Duplicate metadata: {key}")
            metadata[key] = value
    if not doc.raw and not doc.filters:
        raise ValueError("No EQ points or filters found")
    for key, count in (("RAW_BANDS", len(doc.raw)), ("PEQ_COUNT", len(doc.filters))):
        if key in metadata and int(metadata[key]) != count:
            raise ValueError(f"{key} does not match actual entries")
    doc.metadata = metadata
    doc.validate()
    return doc


def load_eq(path):
    path = Path(path)
    raw = path.read_bytes()
    doc = parse_text(raw.decode("utf-8-sig"), path.stem)
    doc.source_sha256 = hashlib.sha256(raw).hexdigest()
    return doc


def dump_eq(doc):
    doc.validate()
    if not doc.raw and not doc.filters:
        raise ValueError("No EQ points or filters to export")
    if any(not f.enabled for f in doc.filters):
        raise ValueError("Flowmix text has no confirmed disabled-filter syntax; enable or remove filters")
    graphic = "; ".join(f"{f:.9g} {g:.9g}" for f, g in doc.raw)
    lines = ["[RAW]", "GraphicEQ: " + graphic, "", "[PEQ]"]
    lines += [f"PEQ{f.id}: {f.frequency:.9g} {f.gain:.9g} {f.q:.9g} {f.kind}" for f in doc.filters]
    meta = {**doc.metadata, "RAW_BANDS": str(len(doc.raw)), "PEQ_COUNT": str(len(doc.filters))}
    lines += ["", "[METADATA]"] + [f"{k}: {v}" for k, v in meta.items()]
    return "\n".join(lines) + "\n"
