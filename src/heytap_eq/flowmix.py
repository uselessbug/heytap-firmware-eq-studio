"""Bounded read-only measurement transport; server payloads remain unconfirmed."""

import argparse
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit

from heytap_eq.apk_config import measurement_authorization

HOSTS = ("fr-api.ykload.cn", "fr-api.ykload.com")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        before, after = urlsplit(req.full_url), urlsplit(newurl)
        if after.scheme != "https" or before.netloc != after.netloc:
            raise ValueError("Redirect across host or to HTTP rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def endpoint(base, *parts):
    url = urlsplit(base)
    if url.scheme != "https" or url.netloc not in HOSTS or url.path not in ("", "/"):
        raise ValueError("Expected an HTTPS Flowmix measurement host")
    return base.rstrip("/")+"/api/"+"/".join(quote(str(p), safe="") for p in parts)


def sources_probe(base="https://fr-api.ykload.cn", authorization=None):
    headers = {"Accept": "application/json", "User-Agent": "okhttp/5.3.2"}
    if authorization:
        if "\r" in authorization or "\n" in authorization:
            raise ValueError("Invalid authorization header")
        headers["Authorization"] = authorization
    req = urllib.request.Request(endpoint(base, "sources"), headers=headers, method="GET")
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
