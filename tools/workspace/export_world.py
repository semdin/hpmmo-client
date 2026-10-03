#!/usr/bin/env python3
"""Export the server world copy from the client Godot project (plan.md Phase 3).

The server repository owns the authoritative world; until Phase 5 inverts
ownership, the world is an EXPORTED, hash-pinned snapshot of the client
project (never a manual copy): this tool copies the declared file set from
client/ into server/world/, writes WORLD_EXPORT.json with per-file sha256 and
the source revision, and refreshes workspace.lock.json.

Usage: python export_world.py --client <dir> --server <dir> --root <dir>
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
FILE_LIST = os.path.join(HERE, "world_files.txt")
CONTRACTS = [
    "data/json/spells.json",
    "data/json/items.json",
    "data/json/houses.json",
    "data/json/quests.json",
    "data/json/safe_zones.json",
]


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--server", required=True)
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    with open(FILE_LIST, encoding="utf-8") as f:
        wanted = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    world = os.path.join(args.server, "world")
    # Deterministic export: wipe previous contents (including Godot import
    # artifacts extracted next to models) so removed sources never linger.
    if os.path.isdir(world):
        for root, dirs, names in os.walk(world, topdown=False):
            for n in names:
                p = os.path.join(root, n)
                if os.path.relpath(p, world).replace("\\", "/") == "WORLD_EXPORT.json":
                    continue
                os.remove(p)
            for d in dirs:
                try:
                    os.rmdir(os.path.join(root, d))
                except OSError:
                    pass
    exported = {}
    missing = []
    for rel in wanted:
        src = os.path.join(args.client, rel.replace("/", os.sep))
        if not os.path.isfile(src):
            missing.append(rel)
            continue
        dst = os.path.join(world, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        exported[rel] = sha256(src)
    if missing:
        raise SystemExit("missing source files:\n  " + "\n  ".join(missing))

    # The world boots the dedicated server, not the client menu.
    pg = os.path.join(world, "project.godot")
    text = open(pg, encoding="utf-8").read()
    text = re.sub(r'run/main_scene="[^"]*"',
                  'run/main_scene="res://scenes/server/dedicated_server.tscn"', text)
    with open(pg, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

    manifest = {
        "generated": str(date.today()),
        "source_repository": "hpmmo-client",
        "source_revision": rev(args.client),
        "note": "Exported world snapshot consumed by the server repo. Regenerate with dev.ps1 sync-world; hashes pinned in workspace.lock.json.",
        "files": exported,
    }
    with open(os.path.join(world, "WORLD_EXPORT.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)

    # Contracts live in BOTH repos (server owns them); pin both copies in the lock.
    contracts = {}
    for rel in CONTRACTS:
        cfile = os.path.join(args.client, rel.replace("/", os.sep))
        server_rel = "contracts/schemas/" + os.path.basename(rel)
        sfile = os.path.join(args.server, server_rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(sfile), exist_ok=True)
        shutil.copy2(cfile, sfile)
        contracts[rel] = {"client": rel, "server": server_rel, "hash": sha256(cfile)}

    lock_path = os.path.join(args.root, "workspace.lock.json")
    lock = {}
    if os.path.exists(lock_path):
        with open(lock_path, encoding="utf-8") as f:
            lock = json.load(f)
    lock["client_revision"] = rev(args.client)
    lock["server_revision"] = rev(args.server)
    lock["godot_version"] = lock.get("godot_version", "4.7.2.stable.official.ed1daf0bf")
    existing = {k: v for k, v in (lock.get("contracts") or {}).items() if k == "protocol"}
    lock["contracts"] = dict(contracts, **existing)
    lock["world_export_files"] = len(exported)
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=1)

    print(f"exported {len(exported)} files to {world}")
    print(f"contracts pinned: {len(contracts)}; lock updated at {lock_path}")


if __name__ == "__main__":
    main()
