#!/usr/bin/env python3
"""Extract the network RPC protocol surface into a versioned contract document.

Server repo owns the contract (server/contracts/protocol.md); a generated copy
lives at client/docs/contracts/protocol.md. The surface hash is pinned in
workspace.lock.json so both sides are checked by `dev.ps1 verify-contracts`.

Usage: python extract_protocol.py --client <dir> --server <dir> --root <dir>
"""

import argparse
import hashlib
import json
import os
import re

RPC_DECORATOR = re.compile(r'@rpc\(([^)]*)\)')
FUNC_DECL = re.compile(r'^func\s+(\w+)\(([^)]*)\)')


def sha256_file(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--client", required=True)
    ap.add_argument("--server", required=True)
    ap.add_argument("--root", required=True)
    args = ap.parse_args()

    src = os.path.join(args.client, "scripts", "autoload", "network_manager.gd")
    lines = open(src, encoding="utf-8").read().splitlines()
    rows = []
    pending = None
    for line in lines:
        dec = RPC_DECORATOR.search(line)
        if dec:
            pending = dec.group(1).replace('"', "")
            continue
        fn = FUNC_DECL.match(line)
        if fn and pending is not None:
            rows.append((fn.group(1), pending, fn.group(2).strip() or "-"))
            pending = None
        elif fn:
            pending = None
    body = [
        "# HPMMO Network Protocol Contract",
        "",
        f"Generated from `scripts/autoload/network_manager.gd` (client revision pinned in workspace.lock.json).",
        "Server owns this contract; regenerate with `client/tools/workspace/extract_protocol.py`.",
        "",
        "| RPC | Flags | Parameters |",
        "| --- | --- | --- |",
    ]
    for name, flags, params in rows:
        body.append(f"| `{name}` | `{flags}` | {params} |")
    body += [
        "",
        f"Surface entries: {len(rows)}. Hash of this document is pinned in the workspace lock;",
        "payload schemas for gameplay data live in `contracts/schemas/`.",
        "",
    ]
    text = "\n".join(body)
    surface_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    text += f"\nSurface hash: `{surface_hash}`\n"

    server_dst = os.path.join(args.server, "contracts", "protocol.md")
    client_dst = os.path.join(args.client, "docs", "contracts", "protocol.md")
    for dst in (server_dst, client_dst):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)

    lock_path = os.path.join(args.root, "workspace.lock.json")
    lock = {}
    if os.path.exists(lock_path):
        lock = json.load(open(lock_path, encoding="utf-8"))
    contracts = lock.get("contracts", {})
    contracts["protocol"] = {
        "client": "docs/contracts/protocol.md",
        "server": "contracts/protocol.md",
        "hash": sha256_file(client_dst),
    }
    lock["contracts"] = contracts
    with open(lock_path, "w", encoding="utf-8") as f:
        json.dump(lock, f, indent=1)
    print(f"protocol.md: {len(rows)} RPC entries, surface hash {surface_hash[:12]}...")
    print("written to server/contracts/protocol.md + client/docs/contracts/protocol.md; lock updated")


if __name__ == "__main__":
    main()
