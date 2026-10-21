#!/usr/bin/env python3
"""Reuse the published launcher when launcher_cpp/ has not changed.

The launcher version is the time of the last commit touching launcher_cpp/,
so a release whose version equals the live manifest's launcher_version would
rebuild (and on macOS re-test) byte-for-byte the same sources. This copies the
live release's launcher files instead; a release that changed the launcher, a
missing manifest or any download error falls back to a full build.

The launcher artifact is checked against the sha256 in the live manifest.
Prints <key>=true|false (key: --key, default hit), also to $GITHUB_OUTPUT
when set.

Usage:
  reuse_launcher.py --base https://github.com/OWNER/REPO/releases/latest/download \\
      --manifest manifest-macos.json --version 3.0.<ts> --out DIR \\
      HPMMO_Launcher-macos HPMMO_Launcher-macos.zip
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.request


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def reuse(base: str, manifest_name: str, version: str, out_dir: str, names: list[str]) -> bool:
    base = base.rstrip("/")
    try:
        doc = json.loads(fetch(base + "/" + manifest_name))
    except Exception as exc:  # no release yet, network error: build instead
        print("[reuse] cannot read the live %s (%s): building" % (manifest_name, exc))
        return False
    live = doc.get("launcher_version")
    if live != version:
        print("[reuse] live launcher %s != %s: building" % (live, version))
        return False
    expected = {os.path.basename(a["url"]): a["sha256"]
                for a in doc.get("artifacts", []) if a.get("kind") == "launcher"}
    os.makedirs(out_dir, exist_ok=True)
    for name in names:
        try:
            data = fetch(base + "/" + name)
        except Exception as exc:
            print("[reuse] cannot download %s (%s): building" % (name, exc))
            return False
        if name in expected and hashlib.sha256(data).hexdigest() != expected[name]:
            print("[reuse] %s does not match the live manifest: building" % name)
            return False
        path = os.path.join(out_dir, name)
        with open(path, "wb") as handle:
            handle.write(data)
        os.chmod(path, 0o755)
    print("[reuse] launcher %s unchanged: reused %s" % (version, ", ".join(names)))
    return True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the latest release's download URL")
    parser.add_argument("--manifest", required=True, help="the platform's manifest file name")
    parser.add_argument("--version", required=True, help="the launcher version this run would build")
    parser.add_argument("--out", required=True)
    parser.add_argument("--key", default="hit", help="the step output's name")
    parser.add_argument("names", nargs="+", help="release assets to copy")
    args = parser.parse_args(argv)
    hit = reuse(args.base, args.manifest, args.version, args.out, args.names)
    line = "%s=%s" % (args.key, "true" if hit else "false")
    print(line)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
