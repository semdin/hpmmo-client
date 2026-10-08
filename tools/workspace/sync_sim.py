#!/usr/bin/env python3
"""Sync the server-owned simulation package into the client.

the world export exported the world from client -> server. the authority inverts ownership of
everything that decides gameplay: the protocol, the combat/movement/zone rules,
the gameplay data, the authority engine and the network surface now live in
`server/world/addons/hpmmo_sim/`, and the client consumes a byte-identical copy
at a pinned hash. Editing the client copy is a build error, caught by
`--check` / `dev.ps1 verify-contracts`.

Usage:
  python sync_sim.py --client <dir> --server <dir> --root <dir> [--check]
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import date

PACKAGE_REL = os.path.join("world", "addons", "hpmmo_sim")
CLIENT_REL = os.path.join("addons", "hpmmo_sim")
MANIFEST_NAME = "SYNC.json"
# Files kept in the client copy but never produced by the server (generated
# bookkeeping only).
CLIENT_ONLY = {MANIFEST_NAME}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rev(repo):
    try:
        out = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except Exception:
        return "unknown"


def collect(package_dir):
    files = {}
    for root, _dirs, names in os.walk(package_dir):
        for name in sorted(names):
            full = os.path.join(root, name)
            rel = os.path.relpath(full, package_dir).replace("\\", "/")
            if rel in CLIENT_ONLY:
                continue
            if name.endswith(".import") or "__pycache__" in rel:
                continue
            files[rel] = full
    return files


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--server", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--check", action="store_true",
                    help="verify the client copy matches the server package; write nothing")
    args = ap.parse_args()

    package_dir = os.path.join(args.server, PACKAGE_REL)
    client_dir = os.path.join(args.client, CLIENT_REL)
    if not os.path.isdir(package_dir):
        raise SystemExit("server simulation package not found: %s" % package_dir)

    source = collect(package_dir)
    if not source:
        raise SystemExit("server simulation package is empty: %s" % package_dir)

    drift = []
    if args.check:
        for rel, src in source.items():
            dst = os.path.join(client_dir, rel.replace("/", os.sep))
            if not os.path.isfile(dst):
                drift.append("missing: " + rel)
            elif sha256(src) != sha256(dst):
                drift.append("differs: " + rel)
        for rel in collect(client_dir):
            if rel not in source:
                drift.append("client-only: " + rel)
        if drift:
            print("simulation package drift:")
            for d in drift:
                print("  " + d)
            raise SystemExit(1)
        print("simulation package in sync (%d files)" % len(source))
        return

    # Deterministic mirror: wipe the client copy (nothing server-authored may
    # linger after a package file is renamed or deleted) and copy it again.
    if os.path.isdir(client_dir):
        for root, dirs, names in os.walk(client_dir, topdown=False):
            for n in names:
                if n in CLIENT_ONLY:
                    continue
                os.remove(os.path.join(root, n))
            for d in dirs:
                try:
                    os.rmdir(os.path.join(root, d))
                except OSError:
                    pass
    synced = {}
    for rel, src in sorted(source.items()):
        dst = os.path.join(client_dir, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        synced[rel] = sha256(dst)

    manifest = {
        "generated": str(date.today()),
        "source_repository": "hpmmo-server",
        "source_revision": rev(args.server),
        "note": "Generated from server/world/addons/hpmmo_sim by dev.ps1 sync-sim. Never edit these files in the client repository.",
        "files": synced,
    }
    with open(os.path.join(client_dir, MANIFEST_NAME), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)

    lock_path = os.path.join(args.root, "workspace.lock.json")
    lock = {}
    if os.path.exists(lock_path):
        with open(lock_path, encoding="utf-8") as f:
            lock = json.load(f)
    contracts = lock.get("contracts") or {}
    for rel, digest in sorted(synced.items()):
        contracts["sim:" + rel] = {
            "client": CLIENT_REL.replace("\\", "/") + "/" + rel,
            "server": PACKAGE_REL.replace("\\", "/") + "/" + rel,
            "hash": digest,
            "source": "server",
        }
    lock["contracts"] = contracts
    lock["sim_sync_files"] = len(synced)
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=1)

    print("synced %d simulation files into %s" % (len(synced), client_dir))
    print("lock updated at %s" % lock_path)


if __name__ == "__main__":
    main()
