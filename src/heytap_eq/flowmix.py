"""Read-only measurement transport and numeric caches for the live Flowmix API."""

import argparse
import hashlib
import json
import urllib.error
import urllib.request
import zipfile
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote, urlsplit

from heytap_eq.apk_config import measurement_authorization
from heytap_eq.measurements import Measurement, parse_json
from heytap_eq.session import atomic_json

HOSTS = ("fr-api.ykload.cn", "fr-api.ykload.com")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = urlsplit(req.full_url), urlsplit(newurl)
        if after.scheme != "https" or before.netloc != after.netloc:
            raise ValueError("Redirect across host or to HTTP rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def endpoint(base, *parts):
    url = urlsplit(base)
    if (url.scheme != "https" or url.netloc not in HOSTS or url.path not in ("", "/")
            or url.query or url.fragment):
        raise ValueError("Expected an HTTPS Flowmix measurement host")
    return base.rstrip("/")+"/api/"+"/".join(quote(str(p), safe="") for p in parts)


def request_response(parts, base="https://fr-api.ykload.cn", authorization=None):
    headers = {"Accept": "application/json", "User-Agent": "okhttp/5.3.2"}
    if authorization:
        if "\r" in authorization or "\n" in authorization:
            raise ValueError("Invalid authorization header")
        headers["Authorization"] = authorization
    req = urllib.request.Request(endpoint(base, *parts), headers=headers, method="GET")
    opener = urllib.request.build_opener(SafeRedirect())
    try:
        response = opener.open(req, timeout=30)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        body = response.read(2*1024*1024+1)
        if len(body) > 2*1024*1024:
            raise ValueError("Response exceeds 2 MiB diagnostic limit")
        text = body.decode("utf-8", errors="replace")
        if authorization:
            text = text.replace(authorization, "[REDACTED]")
            text = text.replace(authorization.split(" ", 1)[-1], "[REDACTED]")
        return {"http_status": response.code, "content_type": response.headers.get("Content-Type"),
                "body": text, "host": urlsplit(base).netloc,
                "authentication": "APK measurement Bearer" if authorization else "anonymous"}


def sources_probe(base="https://fr-api.ykload.cn", authorization=None):
    return request_response(("sources",), base, authorization)


def index_entries(kind, payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("Flowmix did not report a successful data response")
    data = payload.get("data")
    if not isinstance(data, list) or payload.get("count", len(data)) != len(data):
        raise ValueError("Invalid Flowmix index or count")
    result = []
    for item in data:
        if kind == "sources" and isinstance(item, dict):
            name, display = item.get("name"), item.get("displayName")
        elif kind == "brands" and isinstance(item, str):
            name = display = item
        elif kind == "headphones" and isinstance(item, dict):
            name, display = item.get("fileName"), item.get("originalName")
        elif kind == "targets" and isinstance(item, dict):
            name, display = item.get("fileName"), item.get("name")
        else:
            raise ValueError("Invalid Flowmix index entry")
        if not isinstance(name, str) or not name or not isinstance(display, str):
            raise ValueError("Invalid Flowmix name")
        result.append({"name": name, "display": display})
    return result


class FlowmixClient:
    """Keep authentication in memory; caches contain whitelisted data only."""

    def __init__(self, authorization=None, cache_dir=None, base="https://fr-api.ykload.cn"):
        endpoint(base, "sources")
        self._authorization = authorization
        self.base = base
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.from_cache = False

    def _json(self, parts):
        response = request_response(parts, self.base, self._authorization)
        if response["http_status"] != 200:
            raise ValueError(f"Flowmix HTTP {response['http_status']}")
        payload = json.loads(response["body"])
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise ValueError("Flowmix did not report successful data")
        return payload

    def _cache(self, parts):
        key = hashlib.sha256(endpoint(self.base, *parts).encode()).hexdigest()
        return self.cache_dir/(key+".json") if self.cache_dir else None

    def _load(self, parts, parse, restore):
        path = self._cache(parts)
        self.from_cache = False
        try:
            result = parse(self._json(parts))
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
            if not path or not path.exists():
                raise
            result = restore(json.loads(path.read_text(encoding="utf-8")))
            self.from_cache = True
            return result
        if path:
            data = [asdict(v) if isinstance(v, Measurement) else v for v in result]
            try:
                atomic_json(path, data)
            except OSError:
                pass  # Live data still works if the local cache cannot be written.
        return result

    def _index(self, kind, parts):
        def restore(data):
            if not isinstance(data, list) or any(not isinstance(x, dict)
                    or set(x) != {"name", "display"} or not all(isinstance(v, str) for v in x.values())
                    for x in data):
                raise ValueError("Invalid Flowmix index cache")
            return data
        return self._load(parts, lambda p: index_entries(kind, p), restore)

    def sources(self):
        return self._index("sources", ("sources",))

    def brands(self, source):
        return self._index("brands", ("sources", source, "brands"))

    def headphones(self, source, brand):
        return self._index("headphones", ("sources", source, "brands", brand, "headphones"))

    def targets(self):
        return self._index("targets", ("targets",))

    def target(self, name):
        curves = self._curves(("targets", name))
        for curve in curves:
            curve.source = "Flowmix targets"
        return curves

    def match_device(self, identity, sources, cancelled=None):
        from heytap_eq.preferences import unique_match

        for source in sources:
            if cancelled and cancelled.is_set():
                raise InterruptedError("Device matching cancelled")
            try:
                brand = unique_match(self.brands(source["name"]), identity["brand"])
                if not brand:
                    continue
                phone = unique_match(self.headphones(source["name"], brand), identity["model"])
                if phone:
                    return {"source": source["name"], "brand": brand, "headphone": phone}
            except (OSError, ValueError, urllib.error.URLError):
                continue
        return {}

    def measurements(self, source, brand, headphone):
        return self._curves(("sources", source, "brands", brand, "headphones", headphone))

    def _curves(self, parts):
        def restore(data):
            if not isinstance(data, list):
                raise ValueError("Invalid Flowmix measurement cache")
            return [Measurement(**v).validate() for v in data]
        return self._load(parts, parse_json, restore)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Flowmix sources diagnostic; never prints credentials")
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--base", default="https://fr-api.ykload.cn")
    parser.add_argument("--output", type=Path, default=Path("flowmix-sources-diagnostic.json"))
    args = parser.parse_args(argv)
    try:
        auth = measurement_authorization(args.apk) if args.apk else None
        result = sources_probe(args.base, auth)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"HTTP {result['http_status']} · {result['content_type']} · {args.output}")
        return 0 if result["http_status"] == 200 else 2
    except (OSError, ValueError, urllib.error.URLError, zipfile.BadZipFile) as exc:
        print(f"Diagnostic failed: {type(exc).__name__}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
