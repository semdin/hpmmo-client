#!/usr/bin/env python3
"""Export the server world copy from the client Godot project.

The server repository owns the authoritative world; until the authority inverts
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
# Client-owned content contracts. The gameplay contracts (spells, safe zones)
# are server-owned since the authority handover and pinned by sync_sim.py instead.
CONTRACTS = [
    "data/json/houses.json",
    "data/json/quests.json",
]
# Server-authored trees inside the exported world. They are never produced from
# the client and must survive the deterministic wipe below.
SERVER_OWNED_TREES = ("addons", "server")


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
    # Server-authored trees (the simulation package and the world-server entry)
    # are preserved - they are not generated from the client.
    def protected(rel):
        if rel == "WORLD_EXPORT.json":
            return True
        head = rel.split("/", 1)[0]
        return head in SERVER_OWNED_TREES

    if os.path.isdir(world):
        for root, dirs, names in os.walk(world, topdown=False):
            rel_root = os.path.relpath(root, world).replace("\\", "/")
            if rel_root == ".":
                dirs[:] = [d for d in dirs if d not in SERVER_OWNED_TREES]
            for n in names:
                p = os.path.join(root, n)
                if protected(os.path.relpath(p, world).replace("\\", "/")):
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

    # The world boots the authoritative server entry point (server-owned, in the
    # preserved `server/` tree), not the client menu. Read/write with newline=""
    # so the file's existing line endings survive the patch (a rewrite here would
    # desync the recorded hash from git's checkout).
    entry = "res://server/world_server.tscn"
    if not os.path.isfile(os.path.join(world, "server", "world_server.tscn")):
        raise SystemExit("server-owned entry missing: %s (expected under server/world/server/)" % entry)
    pg = os.path.join(world, "project.godot")
    with open(pg, "r", encoding="utf-8", newline="") as f:
        text = f.read()
    text = re.sub(r'run/main_scene="[^"]*"',
                  'run/main_scene="%s"' % entry, text)
    with open(pg, "w", encoding="utf-8", newline="") as f:
        f.write(text)

    # The preserved trees are build inputs, not export products: fail loudly if
    # a wipe rule ever eats them (this is how the simulation package would
    # silently disappear from the server).
    for tree in SERVER_OWNED_TREES:
        if not os.path.isdir(os.path.join(world, tree)):
            raise SystemExit("server-owned tree missing after export: world/%s" % tree)

    # Hash the EXPORTED copies (identical to the sources except project.godot,
    # which this tool patches) so a fresh clone re-hashes to zero drift.
    exported = {rel: sha256(os.path.join(world, rel.replace("/", os.sep))) for rel in wanted}

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
    # Keep entries this tool does not own: the protocol document and everything
    # the server publishes to the client (simulation package, pinned by
    # sync_sim.py). Only the client-owned content contracts are rebuilt here.
    existing = {k: v for k, v in (lock.get("contracts") or {}).items()
                if k == "protocol" or v.get("source") == "server"}
    lock["contracts"] = dict(contracts, **existing)
    lock["world_export_files"] = len(exported)
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=1)

    print(f"exported {len(exported)} files to {world}")
    print(f"contracts pinned: {len(contracts)}; lock updated at {lock_path}")


if __name__ == "__main__":
    main()
