#!/usr/bin/env python3
"""HPMMO client release manifest generator.

Takes an artifact built by package_client.py and emits the detached-signed
release manifest the native launcher consumes:

    manifest.json        the document (see server/docs/release-contract.md)
    manifest.json.sig    raw 64-byte Ed25519 signature, base64, ONE line
    manifest.json.keyid  which key signed it (JSON sidecar, see below)
    SHA256SUMS           the manifest set, for `sha256sum -c`

The signature is Ed25519 over the EXACT manifest.json bytes, produced with the
OpenSSL CLI only - no Python crypto dependency anywhere in the pipeline:

    openssl pkeyutl -sign -rawin -inkey release.key.pem -in manifest.json -out sig

Key custody (also spelled out in tools/release/keys/README.md):

  * the private key NEVER lives in a repository - this tool refuses to sign
    with a key found inside a git working tree unless --allow-key-in-repo is
    passed for a disposable test key;
  * the public key is pinned in the launcher;
  * the key id travels with the signature as `manifest.json.keyid`, whose
    `key_id` is the SHA-256 of the key's DER SubjectPublicKeyInfo - the same
    value the launcher derives from its pinned key. A signature under an
    unexpected key id is refused by the launcher, not trusted.

This tool can prove its own output: `--verify` checks the signature over the
exact bytes, the key id, the manifest schema, and (by default) the size and
sha256 of every local artifact.

Usage:
    python gen_manifest.py --artifact dist/hpmmo-client-0.7.0-windows-x86_64.zip \\
        --channel dev --client-version 0.7.0 --min-launcher-version 0.7.0 \\
        --protocol-version 4 --protocol-min 4 --protocol-max 4 \\
        --content-version 2026.10.04-1 --server-version 0.7.0 --schema-version 4 \\
        --base-url https://213.250.145.75:8443/releases \\
        --key /secure/hpmmo-release.key.pem --out dist

    python gen_manifest.py --verify --manifest dist/manifest.json --pubkey release.pub.pem
    python gen_manifest.py --gate --manifest dist/manifest.json \\
        --installed-client 0.7.0 --installed-launcher 0.7.0 --installed-protocol 4

Exit codes: 0 ok, 2 usage, 3 refused / verification failed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import release_common as rc  # noqa: E402  (path set above)

MANIFEST_FIELDS = (
    "channel", "client_version", "min_launcher_version", "protocol_version",
    "protocol_min", "protocol_max", "content_version", "content_sha256",
    "server_version", "schema_version", "platform", "published_at",
    "release_notes", "artifacts",
)
ARTIFACT_FIELDS = ("kind", "from_version", "url", "size", "sha256")


def say(message: str) -> None:
    print("[manifest] %s" % message)


def version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split("."))


# --- content hash ------------------------------------------------------------

def content_sha256_of_artifact(artifact_path: str) -> str:
    """The content hash of a package: sha256 over the sorted lines
    `<sha256>  <path>\\n` for every "game" role file (the payload the server's
    content rules care about - launcher binaries and release metadata are not
    content), taken from the package's own release.json. This is the rule the
    launcher and the server both re-implement; it is defined here once, in the
    writer."""
    release_doc = release_doc_of_artifact(artifact_path)
    files = release_doc.get("files")
    if not isinstance(files, list):
        raise ValueError("release.json has no file list")
    payload = sorted(
        (entry for entry in files
         if isinstance(entry, dict) and entry.get("role", "game") == "game"),
        key=lambda entry: str(entry.get("path", "")),
    )
    if not payload:
        raise ValueError("release.json lists no game payload files")
    lines = "".join("%s  %s\n" % (entry["sha256"], entry["path"]) for entry in payload)
    return rc.sha256_bytes(lines.encode("utf-8"))


def release_doc_of_artifact(artifact_path: str) -> dict:
    """The package's release.json, whether it sits at the archive root or inside
    a single wrapper directory."""
    with zipfile.ZipFile(artifact_path) as archive:
        for name in sorted(archive.namelist()):
            if name == "release.json" or name.endswith("/release.json"):
                return json.loads(archive.read(name).decode("utf-8"))
    raise ValueError("the package has no release.json - was it built by package_client.py?")


def artifact_refusals(artifact_path: str) -> list[tuple[str, str]]:
    """Last gate before signing: the package that is about to be described by a
    signed manifest must not carry user data, editor caches or secrets. The
    packager already refuses these, but a hand-made or edited artifact is
    exactly the case the signature would otherwise bless."""
    findings: list[tuple[str, str]] = []
    with zipfile.ZipFile(artifact_path) as archive:
        for name in archive.namelist():
            if not name or name.endswith("/"):
                continue
            reason = rc.path_refusal(name)
            if reason:
                findings.append((name, reason))
    return findings


# --- signing -----------------------------------------------------------------

def make_manifest(args: argparse.Namespace) -> dict:
    artifacts = []
    for path in args.artifact:
        if not os.path.isfile(path):
            rc.fail("artifact %s does not exist" % path, 2)
        expected = rc.artifact_name(args.client_version, args.platform, args.kind, args.delta_from)
        actual = os.path.basename(path)
        if actual != expected and not args.allow_renamed_artifact:
            rc.fail("artifact %s does not follow the naming convention (expected %s)" % (actual, expected), 3)
        # The package must agree with the manifest about what it is. A mismatch
        # here is the classic way to publish a manifest describing a package
        # nobody built.
        try:
            doc = release_doc_of_artifact(path)
        except (ValueError, zipfile.BadZipFile) as exc:
            rc.fail("%s is not a client package: %s" % (actual, exc), 3)
        for field, wanted in (("client_version", args.client_version),
                              ("content_version", args.content_version),
                              ("platform", args.platform)):
            got = doc.get(field)
            if got is not None and got != wanted:
                rc.fail("%s says %s=%r but the manifest says %r"
                        % (actual, field, got, wanted), 3)
        offenders = artifact_refusals(path)
        if offenders:
            for rel, reason in offenders:
                sys.stderr.write("error: refusing to sign %s: %s (%s)\n" % (actual, rel, reason))
            rc.fail("refusing to sign a package containing user data, a cache or a secret", 3)
        artifacts.append({
            "kind": args.kind,
            "from_version": args.delta_from if args.kind == "delta" else None,
            "url": args.base_url.rstrip("/") + "/" + actual,
            "size": os.path.getsize(path),
            "sha256": rc.sha256_file(path),
        })
    artifacts.sort(key=lambda entry: (entry["kind"], entry["from_version"] or "", entry["url"]))

    if args.kind == "delta" and len(artifacts) != 1:
        rc.fail("a delta publication carries exactly one artifact (from %s)" % args.delta_from, 2)

    content_sha256 = args.content_sha256
    if not content_sha256:
        try:
            content_sha256 = content_sha256_of_artifact(args.artifact[0])
        except (ValueError, zipfile.BadZipFile) as exc:
            rc.fail("cannot compute content_sha256: %s (pass --content-sha256 to override)" % exc, 3)
    if not re.match(r"^[0-9a-f]{64}$", content_sha256 or ""):
        rc.fail("content_sha256 must be 64 lowercase hex characters", 2)

    return {
        "channel": args.channel,
        "client_version": args.client_version,
        "min_launcher_version": args.min_launcher_version,
        "protocol_version": args.protocol_version,
        "protocol_min": args.protocol_min,
        "protocol_max": args.protocol_max,
        "content_version": args.content_version,
        "content_sha256": content_sha256,
        "server_version": args.server_version,
        "schema_version": args.schema_version,
        "platform": args.platform,
        "published_at": args.published_at or rc.utc_now_iso(),
        "release_notes": args.release_notes,
        "artifacts": artifacts,
    }


def sign_manifest(manifest_path: str, key_path: str, key_id: str) -> tuple[str, str]:
    if not os.path.isfile(key_path):
        rc.fail("signing key %s does not exist" % key_path, 2)
    if rc.in_git_working_tree(key_path) and not ALLOW_REPO_KEY:
        rc.fail("refusing to sign with a private key inside a git working tree (%s).\n"
                "       Custody rule #1: the release private key never lives in a repository.\n"
                "       Keep it in a secret store / on removable media outside any checkout,\n"
                "       or pass --allow-key-in-repo for a disposable test key only." % key_path, 3)
    try:
        signature = rc.sign_ed25519(key_path, manifest_path)
    except RuntimeError as exc:
        rc.fail(str(exc), 3)
    derived = rc.spki_sha256(key_path, public=False)
    if key_id and key_id != derived:
        rc.fail("--key-id %s does not match the key's SPKI sha256 (%s)" % (key_id, derived), 3)
    sig_path = manifest_path + ".sig"
    with open(sig_path, "w", encoding="ascii", newline="\n") as handle:
        handle.write(rc.b64_encode(signature) + "\n")
    keyid_path = manifest_path + ".keyid"
    with open(keyid_path, "w", encoding="ascii", newline="\n") as handle:
        handle.write(rc.json_bytes({
            "key_id": derived,
            "algorithm": "ed25519",
            "sig_file": os.path.basename(sig_path),
        }).decode("utf-8"))
    return sig_path, keyid_path


def write_sums(directory: str, names: list[str]) -> str:
    path = os.path.join(directory, "SHA256SUMS")
    lines = []
    for name in sorted(names):
        full = os.path.join(directory, name)
        lines.append("%s  %s\n" % (rc.sha256_file(full), name))
    with open(path, "w", encoding="ascii", newline="\n") as handle:
        handle.writelines(lines)
    return path


# --- verification ------------------------------------------------------------

def load_manifest(manifest_path: str) -> tuple[bytes, dict]:
    with open(manifest_path, "rb") as handle:
        raw = handle.read()
    try:
        doc = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        rc.fail("%s is not valid JSON: %s" % (manifest_path, exc), 3)
    if not isinstance(doc, dict):
        rc.fail("%s is not a JSON object" % manifest_path, 3)
    return raw, doc


def check_schema(doc: dict) -> list[str]:
    problems = []
    missing = [field for field in MANIFEST_FIELDS if field not in doc]
    if missing:
        problems.append("missing field(s): %s" % ", ".join(missing))
    extra = [field for field in doc if field not in MANIFEST_FIELDS]
    if extra:
        problems.append("unexpected field(s): %s" % ", ".join(extra))
    if doc.get("channel") not in rc.CHANNELS:
        problems.append("channel %r is not one of %s" % (doc.get("channel"), "/".join(rc.CHANNELS)))
    for field in ("client_version", "min_launcher_version", "server_version"):
        try:
            rc.validate_version(str(doc.get(field, "")), field)
        except ValueError as exc:
            problems.append(str(exc))
    try:
        rc.validate_content_version(str(doc.get("content_version", "")))
    except ValueError as exc:
        problems.append(str(exc))
    if not re.match(r"^[0-9a-f]{64}$", str(doc.get("content_sha256", ""))):
        problems.append("content_sha256 is not 64 lowercase hex characters")
    for field in ("protocol_version", "protocol_min", "protocol_max", "schema_version"):
        value = doc.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            problems.append("%s must be a non-negative integer" % field)
    if isinstance(doc.get("protocol_min"), int) and isinstance(doc.get("protocol_max"), int):
        if doc["protocol_min"] > doc["protocol_max"]:
            problems.append("protocol_min is greater than protocol_max")
        if not (doc["protocol_min"] <= doc.get("protocol_version", -1) <= doc["protocol_max"]):
            problems.append("protocol_version is outside [protocol_min, protocol_max]")
    if doc.get("platform") not in rc.PLATFORMS:
        problems.append("platform %r is not one of %s" % (doc.get("platform"), "/".join(rc.PLATFORMS)))
    try:
        rc.validate_iso8601_z(str(doc.get("published_at", "")))
    except ValueError as exc:
        problems.append(str(exc))
    artifacts = doc.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        problems.append("artifacts must be a non-empty list")
    else:
        for index, entry in enumerate(artifacts):
            if not isinstance(entry, dict):
                problems.append("artifacts[%d] is not an object" % index)
                continue
            entry_missing = [field for field in ARTIFACT_FIELDS if field not in entry]
            if entry_missing:
                problems.append("artifacts[%d] missing %s" % (index, ", ".join(entry_missing)))
            if entry.get("kind") not in rc.KNOWN_ARTIFACT_KINDS:
                problems.append("artifacts[%d].kind %r is not one of %s"
                                % (index, entry.get("kind"), "/".join(rc.KNOWN_ARTIFACT_KINDS)))
            if entry.get("kind") == "delta" and not entry.get("from_version"):
                problems.append("artifacts[%d] is a delta without from_version" % index)
            if entry.get("kind") == "full" and entry.get("from_version") is not None:
                problems.append("artifacts[%d] is a full artifact with from_version set" % index)
            url = str(entry.get("url", ""))
            if not url.startswith("https://"):
                problems.append("artifacts[%d].url must be https://" % index)
            if not re.match(r"^[0-9a-f]{64}$", str(entry.get("sha256", ""))):
                problems.append("artifacts[%d].sha256 is not 64 lowercase hex characters" % index)
            if not isinstance(entry.get("size"), int) or isinstance(entry.get("size"), bool) or entry.get("size") <= 0:
                problems.append("artifacts[%d].size must be a positive integer" % index)
    return problems


def cmd_verify(args: argparse.Namespace) -> int:
    manifest_path = args.manifest
    if not os.path.isfile(manifest_path):
        rc.fail("no manifest at %s" % manifest_path, 2)
    raw, doc = load_manifest(manifest_path)

    sig_path = manifest_path + ".sig"
    if not os.path.isfile(sig_path):
        rc.fail("no detached signature at %s (a manifest without a signature is not a release)" % sig_path, 3)
    with open(sig_path, encoding="ascii") as handle:
        sig_text = handle.read().strip()
    if "\n" in sig_text:
        rc.fail("%s is not a single line of base64" % sig_path, 3)
    try:
        signature = rc.b64_decode(sig_text)
    except Exception as exc:  # noqa: BLE001 - binascii raises several types
        rc.fail("%s is not valid base64: %s" % (sig_path, exc), 3)
    if len(signature) != 64:
        rc.fail("%s decodes to %d bytes; an Ed25519 signature is 64" % (sig_path, len(signature)), 3)

    ok, reason = rc.verify_ed25519(args.pubkey, manifest_path, signature)
    if not ok:
        rc.fail("signature does NOT verify against %s: %s" % (args.pubkey, reason), 3)
    say("signature verifies over the exact manifest bytes")

    expected_key_id = rc.spki_sha256(args.pubkey, public=True)
    keyid_path = manifest_path + ".keyid"
    if os.path.isfile(keyid_path):
        with open(keyid_path, encoding="utf-8") as handle:
            sidecar = json.load(handle)
        declared = str(sidecar.get("key_id", ""))
        if declared != expected_key_id:
            rc.fail("%s declares key_id %s but the pinned public key is %s"
                    % (keyid_path, declared, expected_key_id), 3)
        say("key id matches the pinned public key (%s)" % expected_key_id[:16] + "...")
    if args.key_id and args.key_id != expected_key_id:
        rc.fail("--key-id %s does not match the pinned public key (%s)" % (args.key_id, expected_key_id), 3)

    problems = check_schema(doc)
    if problems:
        for problem in problems:
            sys.stderr.write("error: manifest: %s\n" % problem)
        rc.fail("the manifest does not satisfy the release contract", 3)
    say("manifest satisfies the release contract (channel=%s client=%s content=%s)"
        % (doc["channel"], doc["client_version"], doc["content_version"]))

    checked = 0
    if not args.no_artifacts:
        directory = args.artifacts or os.path.dirname(os.path.abspath(manifest_path))
        for entry in doc["artifacts"]:
            name = entry["url"].rsplit("/", 1)[-1]
            local = os.path.join(directory, name)
            if not os.path.isfile(local):
                rc.fail("artifact %s (from %s) is not present in %s" % (name, entry["url"], directory), 3)
            size = os.path.getsize(local)
            digest = rc.sha256_file(local)
            if size != entry["size"]:
                rc.fail("artifact %s is %d bytes but the manifest says %d - refusing it" % (name, size, entry["size"]), 3)
            if digest != entry["sha256"]:
                rc.fail("artifact %s hashes to %s but the manifest says %s - refusing it" % (name, digest, entry["sha256"]), 3)
            checked += 1
            say("artifact %s matches its recorded size and sha256" % name)

    print("MANIFEST OK: %s (channel %s, client %s, %d artifact(s) checked)"
          % (os.path.basename(manifest_path), doc["channel"], doc["client_version"], checked))
    return 0


# --- gating ------------------------------------------------------------------

def gate_verdict(doc: dict, installed_client: str, installed_launcher: str,
                 installed_protocol: int | None, installed_content: str | None) -> dict:
    """The compatibility rules from server/docs/release-contract.md, in
    one place so the pipeline can prove them. The launcher implements the same
    rules; this is the reference."""
    reasons: list[str] = []
    client_update = "none"
    if version_tuple(installed_client) < version_tuple(doc["client_version"]):
        client_update = "required"
        reasons.append("installed client %s is older than the %s channel's %s"
                       % (installed_client, doc["channel"], doc["client_version"]))
    elif version_tuple(installed_client) > version_tuple(doc["client_version"]):
        reasons.append("installed client %s is newer than the %s channel offers (%s); keeping it"
                       % (installed_client, doc["channel"], doc["client_version"]))

    launcher_update = "none"
    if version_tuple(installed_launcher) < version_tuple(doc["min_launcher_version"]):
        launcher_update = "required"
        reasons.append("launcher %s is below the required minimum %s"
                       % (installed_launcher, doc["min_launcher_version"]))

    effective_protocol = doc["protocol_version"] if client_update == "required" else (
        installed_protocol if installed_protocol is not None else doc["protocol_version"])
    protocol_compatible = doc["protocol_min"] <= effective_protocol <= doc["protocol_max"]
    if not protocol_compatible:
        reasons.append("protocol %s is outside the server's accepted range [%s, %s]"
                       % (effective_protocol, doc["protocol_min"], doc["protocol_max"]))

    if client_update == "required":
        content_status = "updated_with_client"
    elif installed_content is None:
        content_status = "unknown"
    elif installed_content == doc["content_version"]:
        content_status = "current"
    else:
        # The client is up to date but its content is not: that is a broken or
        # half-applied install, not a version mismatch. Repair, do not download.
        content_status = "repair_required"
        reasons.append("installed content %s does not match the manifest's %s - the install is incomplete"
                       % (installed_content, doc["content_version"]))

    playable = (launcher_update == "none" and client_update == "none"
                and protocol_compatible and content_status in ("current", "unknown"))
    return {
        "client_update": client_update,
        "launcher_update": launcher_update,
        "content_status": content_status,
        "protocol_compatible": protocol_compatible,
        "protocol_effective": effective_protocol,
        "protocol_range": [doc["protocol_min"], doc["protocol_max"]],
        "playable_online": playable,
        "offered": {
            "channel": doc["channel"],
            "client_version": doc["client_version"],
            "content_version": doc["content_version"],
            "server_version": doc["server_version"],
            "schema_version": doc["schema_version"],
            "artifacts": [{"kind": entry["kind"], "url": entry["url"], "sha256": entry["sha256"]}
                          for entry in doc["artifacts"]],
        },
        "reasons": reasons,
    }


def cmd_gate(args: argparse.Namespace) -> int:
    _raw, doc = load_manifest(args.manifest)
    try:
        rc.validate_version(args.installed_client, "installed client version")
        rc.validate_version(args.installed_launcher, "installed launcher version")
    except ValueError as exc:
        rc.fail(str(exc), 2)
    verdict = gate_verdict(doc, args.installed_client, args.installed_launcher,
                           args.installed_protocol, args.installed_content)
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0


# --- main --------------------------------------------------------------------

ALLOW_REPO_KEY = False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate and verify the HPMMO client release manifest")
    parser.add_argument("--artifact", action="append", default=[], help="packaged client zip (repeatable)")
    parser.add_argument("--kind", choices=rc.KINDS, default="full")
    parser.add_argument("--delta-from", default="", help="version a delta patches from")
    parser.add_argument("--channel", choices=rc.CHANNELS, default="dev")
    parser.add_argument("--client-version")
    parser.add_argument("--min-launcher-version")
    parser.add_argument("--protocol-version", type=int)
    parser.add_argument("--protocol-min", type=int)
    parser.add_argument("--protocol-max", type=int)
    parser.add_argument("--content-version")
    parser.add_argument("--content-sha256", default="", help="override the computed content hash (tests only)")
    parser.add_argument("--server-version")
    parser.add_argument("--schema-version", type=int)
    parser.add_argument("--platform", default="windows-x86_64")
    parser.add_argument("--base-url", default="https://213.250.145.75:8443/releases")
    parser.add_argument("--release-notes", default="")
    parser.add_argument("--release-notes-file", default="")
    parser.add_argument("--published-at", default="", help="pin published_at for a reproducible manifest")
    parser.add_argument("--key", default="", help="Ed25519 private key (PEM) - never in a repository")
    parser.add_argument("--key-id", default="", help="expected SPKI sha256 of the signing key")
    parser.add_argument("--allow-key-in-repo", action="store_true",
                        help="disposable test keys only; never for a release")
    parser.add_argument("--out", default="", help="where to write the manifest set (default: artifact dir)")
    parser.add_argument("--verify", action="store_true", help="verify an existing manifest instead of building one")
    parser.add_argument("--manifest", default="", help="manifest to verify (with --verify) or read (with --gate)")
    parser.add_argument("--pubkey", default="", help="pinned public key to verify against")
    parser.add_argument("--artifacts", default="", help="directory holding the artifacts (default: manifest dir)")
    parser.add_argument("--no-artifacts", action="store_true", help="verify the signature only, not artifact hashes")
    parser.add_argument("--gate", action="store_true", help="apply the documented compatibility gate")
    parser.add_argument("--installed-client", default="", help="client version already installed (with --gate)")
    parser.add_argument("--installed-launcher", default="", help="launcher version already installed (with --gate)")
    parser.add_argument("--installed-protocol", type=int, default=None)
    parser.add_argument("--installed-content", default=None)
    return parser


def cmd_build(args: argparse.Namespace) -> int:
    if not args.artifact:
        rc.fail("--artifact is required", 2)
    required = {"--client-version": args.client_version, "--min-launcher-version": args.min_launcher_version,
                "--protocol-version": args.protocol_version, "--protocol-min": args.protocol_min,
                "--protocol-max": args.protocol_max, "--content-version": args.content_version,
                "--server-version": args.server_version, "--schema-version": args.schema_version}
    missing = [name for name, value in required.items() if value is None]
    if missing:
        rc.fail("missing required option(s): %s" % ", ".join(sorted(missing)), 2)
    if args.kind == "delta" and not args.delta_from:
        rc.fail("--delta-from is required when --kind delta", 2)
    if args.protocol_min > args.protocol_version or args.protocol_version > args.protocol_max:
        rc.fail("protocol_version must lie inside [protocol_min, protocol_max]", 2)

    try:
        rc.validate_version(args.client_version, "client version")
        rc.validate_version(args.min_launcher_version, "min_launcher_version")
        rc.validate_version(args.server_version, "server version")
        rc.validate_content_version(args.content_version)
        rc.validate_platform(args.platform)
    except ValueError as exc:
        rc.fail(str(exc), 2)

    if args.release_notes_file:
        with open(args.release_notes_file, encoding="utf-8") as handle:
            args.release_notes = handle.read().strip()
    if args.published_at:
        try:
            rc.validate_iso8601_z(args.published_at)
        except ValueError as exc:
            rc.fail(str(exc), 2)

    manifest = make_manifest(args)

    out_dir = args.out or os.path.dirname(os.path.abspath(args.artifact[0]))
    os.makedirs(out_dir, exist_ok=True)
    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "wb") as handle:
        handle.write(rc.json_bytes(manifest))
    say("wrote %s" % manifest_path)
    for entry in manifest["artifacts"]:
        name = entry["url"].rsplit("/", 1)[-1]
        local = os.path.join(os.path.dirname(os.path.abspath(args.artifact[0])), name)
        if os.path.isfile(local):
            sidecar = local + ".sha256"
            with open(sidecar, "w", encoding="ascii", newline="\n") as handle:
                handle.write("%s  %s\n" % (entry["sha256"], name))
            say("wrote %s" % sidecar)

    if not args.key:
        rc.fail("no --key given: a manifest without a detached signature must not be published", 3)
    sig_path, keyid_path = sign_manifest(manifest_path, args.key, args.key_id)
    say("wrote %s (%s)" % (sig_path, "ed25519"))
    say("wrote %s" % keyid_path)

    sums = write_sums(out_dir, ["manifest.json", os.path.basename(sig_path), os.path.basename(keyid_path)])
    say("wrote %s" % sums)

    # Prove our own output before anyone can publish it.
    import tempfile
    workdir = tempfile.mkdtemp(prefix="hpmmo-selfverify-")
    try:
        args.manifest = manifest_path
        args.pubkey = _public_key_of(args.key, os.path.join(workdir, "release.pub.pem"))
        args.no_artifacts = False
        args.artifacts = args.artifacts or os.path.dirname(os.path.abspath(args.artifact[0]))
        return cmd_verify(args)
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


def _public_key_of(key_path: str, out_path: str) -> str:
    code, out, err = rc.run_openssl(["pkey", "-in", key_path, "-pubout"])
    if code != 0:
        rc.fail("cannot derive the public key from %s: %s" % (key_path, err.decode("utf-8", "replace").strip()), 3)
    with open(out_path, "wb") as handle:
        handle.write(out)
    return out_path


def main(argv: list[str]) -> int:
    global ALLOW_REPO_KEY
    parser = build_parser()
    args = parser.parse_args(argv)
    ALLOW_REPO_KEY = bool(args.allow_key_in_repo)
    if args.verify:
        if not args.manifest or not args.pubkey:
            rc.fail("--verify needs --manifest and --pubkey", 2)
        return cmd_verify(args)
    if args.gate:
        if not args.manifest or not args.installed_client or not args.installed_launcher:
            rc.fail("--gate needs --manifest, --installed-client and --installed-launcher", 2)
        return cmd_gate(args)
    return cmd_build(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
