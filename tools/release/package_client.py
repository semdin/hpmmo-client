#!/usr/bin/env python3
"""HPMMO client packager (plan.md Phase 7).

Builds the zip a launcher installs, from a *build directory* laid out as:

    <build>/
      client/           required. The Godot export payload (HPMMO.exe, HPMMO.pck,
                        and any data the export writes next to them).
      launcher/         optional. The native launcher executable and its assets
                        (this is what a launcher self-update consumes).

Nothing else may sit at the top level. The artifact:

    hpmmo-client-<client_version>-<platform>.zip
      HPMMO.exe          the game payload, FLAT at the archive root
      HPMMO.pck
      launcher/...       the launcher payload, kept in its own directory
      release.json       format, versions, and the size+sha256 of every file

The game payload is flat because the launcher extracts a package straight into
its version directory and resolves the executable as `<versionDir>/HPMMO.exe`
(with a configurable override and a short candidate list). Nesting the game
under a wrapper directory would install a build the launcher could not launch.
The launcher payload keeps a directory of its own so it can never collide with
a game file name.

The zip is DETERMINISTIC: entries are sorted by path, every entry is stamped
with a fixed timestamp, and the same input tree always produces the same bytes.
That is what lets CI publish an immutable artifact whose hash is recorded in
the signed manifest.

Refused (fail closed, exit 3), by `release_common.path_refusal`:

  * user data  - settings/, keybinds/, logs/, screenshots/, saves/ and the
                 known user-data file names. User data lives beside the
                 installed versions and must survive an update;
  * caches     - .godot/, .git/, __pycache__/, *.pyc, *.uid;
  * secrets    - *.pem, *.key, id_ed25519, .env, credentials*, known_hosts,
                 and file *contents* that look like a private key or a
                 service token.

Usage:
    python package_client.py --build-dir build --client-version 0.7.0 \\
        --content-version 2026.10.04-1 --out dist
    python package_client.py --check --build-dir build     # validate only
Environment:
    HPMMO_OPENSSL  openssl binary (default: openssl)
Exit codes: 0 ok, 2 usage, 3 the input tree or the output is not acceptable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import release_common as rc  # noqa: E402  (path set above)

FORMAT_VERSION = 1
#: A fixed timestamp for every zip entry. 1980-01-01 is the earliest value the
#: zip format can store, so the same tree always hashes to the same bytes.
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
ALLOWED_TOP_LEVEL = {"client", "launcher"}


def say(message: str) -> None:
    print("[package] %s" % message)


def archive_name(relpath: str) -> str:
    """Maps a build-directory path to its path inside the artifact: the game
    payload is flattened to the archive root, everything else keeps its place."""
    relpath = relpath.replace("\\", "/")
    if relpath.startswith("client/"):
        return relpath[len("client/"):]
    return relpath


def collect_tree(root: str) -> list[tuple[str, str]]:
    """Returns [(arcname, abs path)] sorted by arcname."""
    entries: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, root).replace("\\", "/")
            entries.append((rel, full))
    entries.sort(key=lambda item: item[0])
    return entries


def validate_build_dir(build_dir: str) -> None:
    if not os.path.isdir(build_dir):
        rc.fail("build directory %s does not exist" % build_dir)
    top = sorted(os.listdir(build_dir))
    unknown = [name for name in top if name not in ALLOWED_TOP_LEVEL]
    if unknown:
        rc.fail("unexpected top-level entries in %s: %s (only %s are allowed)"
                % (build_dir, ", ".join(unknown), ", ".join(sorted(ALLOWED_TOP_LEVEL))))
    client = os.path.join(build_dir, "client")
    if not os.path.isdir(client):
        rc.fail("%s has no client/ directory - there is nothing to install" % build_dir)
    client_files = [name for name in os.listdir(client) if os.path.isfile(os.path.join(client, name))]
    if not any(name.lower().endswith(".pck") for name in client_files):
        rc.fail("client/ contains no .pck (the exported game payload is missing)")
    if not any(name.lower().endswith(".exe") for name in client_files):
        rc.fail("client/ contains no .exe (the game executable is missing)")

    findings = rc.check_tree(build_dir)
    if findings:
        for rel, reason in findings:
            sys.stderr.write("error: refusing to package %s: %s\n" % (rel, reason))
        rc.fail("refused: %d path(s) in %s must never be inside a client package" % (len(findings), build_dir))


def write_zip(build_dir: str, out_path: str, release_doc: dict) -> None:
    """Writes the artifact with the layout documented at the top of this file."""
    tmp = out_path + ".partial"
    if os.path.exists(tmp):
        os.unlink(tmp)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    entries = [(archive_name(rel), full) for rel, full in collect_tree(build_dir)]
    entries.append(("release.json", None))
    entries.sort(key=lambda item: item[0])
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for arcname, full in entries:
            info = zipfile.ZipInfo(arcname, date_time=FIXED_ZIP_TIME)
            info.external_attr = (0o644 & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            if full is None:
                archive.writestr(info, rc.json_bytes(release_doc))
            else:
                with open(full, "rb") as handle:
                    archive.writestr(info, handle.read())
    os.replace(tmp, out_path)


def build_release_doc(build_dir: str, client_version: str, content_version: str, platform: str) -> dict:
    files = []
    for rel, full in collect_tree(build_dir):
        files.append({
            "path": archive_name(rel),
            "role": "game" if rel.startswith("client/") else "launcher",
            "size": os.path.getsize(full),
            "sha256": rc.sha256_file(full),
        })
    files.sort(key=lambda entry: entry["path"])
    return {
        "format": FORMAT_VERSION,
        "client_version": client_version,
        "content_version": content_version,
        "platform": platform,
        "version_dir": rc.version_dir_name(client_version, platform),
        "files": files,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Package an HPMMO client build")
    parser.add_argument("--build-dir", required=True, help="build directory (client/ and optional launcher/)")
    parser.add_argument("--client-version", required=True, help="the version this build actually is")
    parser.add_argument("--content-version", required=True, help="content version shipped inside this build")
    parser.add_argument("--platform", default="windows-x86_64")
    parser.add_argument("--out", default="dist", help="output directory (default: dist)")
    parser.add_argument("--check", action="store_true", help="validate the build directory only; write nothing")
    args = parser.parse_args(argv)

    try:
        client_version = rc.validate_version(args.client_version, "client version")
        content_version = rc.validate_content_version(args.content_version)
        platform = rc.validate_platform(args.platform)
    except ValueError as exc:
        rc.fail(str(exc), 2)

    say("validating %s" % args.build_dir)
    validate_build_dir(args.build_dir)
    if args.check:
        say("check passed: %s is packageable (nothing was written)" % args.build_dir)
        return 0

    release_doc = build_release_doc(args.build_dir, client_version, content_version, platform)
    out_name = rc.artifact_name(client_version, platform)
    out_path = os.path.join(args.out, out_name)
    say("writing %s (%d files)" % (out_path, len(release_doc["files"])))
    write_zip(args.build_dir, out_path, release_doc)

    # Re-open the artifact and prove what we just wrote is what the manifest
    # will describe: a launchable flat payload, and nothing forbidden.
    with zipfile.ZipFile(out_path) as archive:
        names = archive.namelist()
        for required in ("release.json",):
            if required not in names:
                rc.fail("the artifact is missing %s" % required)
        if not any(name.lower() in ("hpmmo.exe", "hpmmo_game.exe", "game.exe", "godot.exe")
                   for name in names):
            rc.fail("the artifact has no game executable at the archive root - "
                    "the launcher resolves <versionDir>/HPMMO.exe and would install an unlaunchable build")
        for rel in names:
            reason = rc.path_refusal(rel)
            if reason:
                rc.fail("the artifact contains %s: %s" % (rel, reason))

    size = os.path.getsize(out_path)
    digest = rc.sha256_file(out_path)
    say("wrote %s (%d bytes)" % (out_path, size))
    say("sha256 %s" % digest)
    print(json.dumps({"artifact": out_path, "size": size, "sha256": digest,
                      "version_dir": rc.version_dir_name(client_version, platform)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
