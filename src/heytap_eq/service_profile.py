"""Build or load a self-use service profile from the pinned official distribution."""

import argparse
import json
import urllib.request
from pathlib import Path

from heytap_eq.apk_config import KNOWN_APK_SHA256, authorization_from_bytes
from heytap_eq.session import atomic_json

OFFICIAL_APK = "https://cos.ykload.com/d/Flowmix/APK/Flowmix-Beta-5-10.apk"
PROFILE_NAME = "_flowmix_profile.json"


def profile_authorization(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    auth = data.get("authorization")
    if (data.get("apk_sha256") != KNOWN_APK_SHA256 or not isinstance(auth, str)
            or not auth.startswith("Bearer ") or len(auth) <= 7
            or "\r" in auth or "\n" in auth):
        raise ValueError("Invalid built-in measurement profile")
    return auth


def builtin_authorization(local_dir=None):
    bundled = Path(__file__).with_name(PROFILE_NAME)
    for path in (bundled, Path(local_dir)/PROFILE_NAME if local_dir else bundled):
        if path.exists():
            return profile_authorization(path)
    return None


def prepare_profile(directory):
    # No credential is present in git. Only the public, hash-pinned APK is fetched.
    with urllib.request.urlopen(OFFICIAL_APK, timeout=30) as response:
        raw = response.read(16*1024*1024+1)
    if len(raw) > 16*1024*1024:
        raise ValueError("Official APK exceeds download limit")
    auth = authorization_from_bytes(raw)
    path = Path(directory)/PROFILE_NAME
    atomic_json(path, {"apk_sha256": KNOWN_APK_SHA256, "authorization": auth})
    return auth


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    prepare_profile(args.directory)
    print("Pinned built-in measurement profile prepared; no APK retained.")


if __name__ == "__main__":
    main()
