#!/usr/bin/env python3
"""Shared naming, hashing and refusal rules for the HPMMO client release tools.

Used by:
    package_client.py   builds the zip a launcher installs
    gen_manifest.py     signs the manifest that describes that zip

Everything in here is deliberately dependency-free (standard library only).
The release pipeline must run with nothing but Python, the OpenSSL CLI and
(optionally) the Godot engine available.

The refusal rules are the ones the Phase 7 exit checks depend on:

  * USER DATA (settings, keybinds, logs, screenshots, saves) must never be
    inside a package - it lives beside the installed versions and survives an
    update;
  * EDITOR CACHES (.godot/) and VCS metadata must never be inside a package;
  * SECRETS must never be inside a package, by file name or by content.

Naming convention (one version directory per release, exactly what the
launcher's "versioned installation directories + atomic active-version switch"
needs):

    hpmmo-client-<client_version>-<platform>            version directory
    hpmmo-client-<client_version>-<platform>.zip        full artifact
    hpmmo-client-<client_version>-from-<from>-<platform>.zip   delta artifact
"""

from __future__ import annotations

import binascii
import datetime as _dt
import hashlib
import json
import os
import re
import sys

# --- versions and names ------------------------------------------------------

VERSION_RE = re.compile(r"^[0-9]+(\.[0-9]+){1,3}$")
CHANNELS = ("dev", "beta", "release")
PLATFORMS = ("windows-x86_64",)
#: What this pipeline publishes today. Deltas are accepted by the tooling but
#: the plan's order is full packages first.
KINDS = ("full", "delta")
#: Every artifact kind the launcher understands. `launcher` is the optional
#: launcher self-update payload (the launcher's own selector skips it when
#: choosing what to install); it is reserved here so the verifier does not
#: reject a future publication, and documented in phase7-release-contract.md.
KNOWN_ARTIFACT_KINDS = ("full", "delta", "launcher")

#: The prefix every artifact, version directory and manifest belongs to.
ARTIFACT_PREFIX = "hpmmo-client"


def validate_version(value: str, what: str = "version") -> str:
    if not isinstance(value, str) or not VERSION_RE.match(value):
        raise ValueError("%s %r is not a dotted numeric version (for example 0.7.0)" % (what, value))
    return value


def validate_content_version(value: str) -> str:
    # content versions are date-stamped (2026.10.04-1) and intentionally not
    # the same shape as client versions - they version game content, not code.
    if not isinstance(value, str) or not re.match(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}(-[0-9]+)?$", value):
        raise ValueError("content version %r must look like 2026.10.04-1" % (value,))
    return value


def validate_platform(value: str) -> str:
    if value not in PLATFORMS:
        raise ValueError("platform %r is not one of: %s" % (value, ", ".join(PLATFORMS)))
    return value


def version_dir_name(client_version: str, platform: str) -> str:
    return "%s-%s-%s" % (ARTIFACT_PREFIX, client_version, platform)


def artifact_name(client_version: str, platform: str, kind: str = "full", from_version: str = "") -> str:
    if kind == "delta":
        if not from_version:
            raise ValueError("a delta artifact needs the version it patches from")
        base = "%s-%s-from-%s-%s" % (ARTIFACT_PREFIX, client_version, from_version, platform)
    else:
        base = version_dir_name(client_version, platform)
    return base + ".zip"


# --- time --------------------------------------------------------------------

def utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_iso8601_z(value: str) -> str:
    if not isinstance(value, str) or not re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$", value):
        raise ValueError("published_at %r must be an ISO8601 UTC timestamp (2026-10-04T12:00:00Z)" % (value,))
    return value


# --- hashing -----------------------------------------------------------------

def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(obj) -> bytes:
    """The canonical on-disk form of every JSON document this toolchain
    publishes: two-space indent, ASCII-escaped, one trailing newline. The
    manifest is signed over exactly these bytes, so the encoding is part of the
    contract and may not drift."""
    return (json.dumps(obj, indent=2, ensure_ascii=True, sort_keys=False) + "\n").encode("utf-8")


# --- refusal rules -----------------------------------------------------------

# Directory names user data is allowed to live under. Matched as any path
# segment, case-insensitively.
USER_DATA_DIRS = {
    "settings", "keybinds", "logs", "log", "screenshots", "screenshot",
    "userdata", "user_data", "user", "saves", "save", "savegames", "savegames_backup",
}

# File names that are user data or local configuration, matched on the basename.
USER_DATA_FILES = {
    "client_config.json",
    "launcher.log",
    "hpmmo_save.json",
    "hpmmo_character_save.json",
    "pottermetin_save.json",
    "pottermetin_character_save.json",
    "settings.cfg",
    "keybinds.cfg",
}
USER_DATA_FILE_PATTERNS = (
    re.compile(r"(?i)^.*\.log$"),
    re.compile(r"(?i)^.*\.tmp$"),
    re.compile(r"(?i)^save[-_]?[0-9]*\.json$"),
    re.compile(r"(?i)^.*\.save$"),
)

# Editor/VCS metadata that must never ship.
CACHE_DIRS = {".godot", ".git", ".svn", ".hg", "__pycache__", ".cache", "node_modules"}
CACHE_FILE_PATTERNS = (
    re.compile(r"(?i)^.*\.pyc$"),
    re.compile(r"(?i)^.*\.pyo$"),
    re.compile(r"(?i)^.*\.uid$"),
    re.compile(r"(?i)^\.DS_Store$"),
    re.compile(r"(?i)^Thumbs\.db$"),
)

# Secrets, matched on the basename.
SECRET_FILE_PATTERNS = (
    re.compile(r"(?i)^.*\.pem$"),
    re.compile(r"(?i)^.*\.key$"),
    re.compile(r"(?i)^.*\.p12$"),
    re.compile(r"(?i)^.*\.pfx$"),
    re.compile(r"(?i)^.*\.ppk$"),
    re.compile(r"(?i)^.*\.token$"),
    re.compile(r"(?i)^id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),
    re.compile(r"(?i)^\.env(\..*)?$"),
    re.compile(r"(?i)^.*\.env$"),
    re.compile(r"(?i)^hpmmo\.env.*$"),
    re.compile(r"(?i)^credentials(\..*)?$"),
    re.compile(r"(?i)^secrets?(\..*)?$"),
    re.compile(r"(?i)^known_hosts$"),
    re.compile(r"(?i)^\.netrc$"),
    re.compile(r"(?i)^shadow$"),
)

# Content signatures: a text file that contains one of these is a secret that
# was about to be published. Kept short and unambiguous to avoid false hits.
SECRET_CONTENT_SIGNATURES = (
    b"-----BEGIN PRIVATE KEY-----",
    b"-----BEGIN OPENSSH PRIVATE KEY-----",
    b"-----BEGIN RSA PRIVATE KEY-----",
    b"-----BEGIN EC PRIVATE KEY-----",
    b"HPMMO_SERVICE_TOKEN=",
    b"HPMMO_DB_PASSWORD=",
    b"PGPASSWORD=",
    b"DATABASE_URL=postgres",
)


def path_refusal(relpath: str) -> str:
    """Returns a human-readable reason this relative path may not be packaged,
    or an empty string when the path is allowed."""
    norm = relpath.replace("\\", "/").strip("/")
    if not norm:
        return "empty path"
    parts = norm.split("/")
    for part in parts[:-1]:
        if part.lower() in USER_DATA_DIRS:
            return "user data directory '%s' (settings/keybinds/logs/screenshots/saves never ship)" % part
        if part.lower() in CACHE_DIRS:
            return "editor/VCS cache directory '%s' (for example .godot/ or .git/)" % part
    name = parts[-1]
    if name.lower() in CACHE_DIRS:
        return "editor/VCS cache directory '%s'" % name
    if name.lower() in USER_DATA_FILES:
        return "user data file '%s'" % name
    for pattern in USER_DATA_FILE_PATTERNS:
        if pattern.match(name):
            return "user data file '%s'" % name
    for pattern in CACHE_FILE_PATTERNS:
        if pattern.match(name):
            return "editor/VCS metadata file '%s'" % name
    for pattern in SECRET_FILE_PATTERNS:
        if pattern.match(name):
            return "secret-shaped file name '%s'" % name
    return ""


def content_refusal(path: str) -> str:
    """Returns a reason when a *file* contains something that must never be
    published (a private key, a service token). Reads at most 512 KiB."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(512 * 1024)
    except OSError as exc:
        return "unreadable (%s)" % exc
    if b"\x00" in head[:4096] and not head.startswith(b"-----"):
        return ""  # binary payload; the name rules already applied
    for signature in SECRET_CONTENT_SIGNATURES:
        if signature in head:
            return "contains %s" % signature.decode("ascii", "replace")
    return ""


def check_tree(root: str, skip: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """Walks a directory tree and returns [(relpath, reason)] for everything
    that must not be packaged. `skip` is a tuple of relative names to ignore."""
    findings: list[tuple[str, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in list(dirnames):
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/")
            if rel in skip or name in skip:
                dirnames.remove(name)
                continue
            reason = path_refusal(rel)
            if reason:
                # report the directory once and do not walk into it: one
                # refusal is actionable, four hundred are noise.
                findings.append((rel + "/", reason))
                dirnames.remove(name)
        for name in sorted(filenames):
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/")
            if rel in skip or (dirpath == root and name in skip):
                continue
            reason = path_refusal(rel) or content_refusal(os.path.join(dirpath, name))
            if reason:
                findings.append((rel, reason))
    return findings


# --- openssl helpers ---------------------------------------------------------

def openssl_binary() -> str:
    return os.environ.get("HPMMO_OPENSSL", "openssl")


def run_openssl(args: list[str], stdin: bytes | None = None) -> tuple[int, bytes, bytes]:
    import subprocess
    proc = subprocess.run(
        [openssl_binary()] + args,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.returncode, proc.stdout, proc.stderr


def spki_sha256(key_path: str, public: bool = True) -> str:
    """SHA-256 of the DER SubjectPublicKeyInfo of a key file. This is the value
    the launcher pins: it is stable across re-encodings of the key and does not
    expose the key itself."""
    args = ["pkey", "-in", key_path, "-pubout", "-outform", "DER"]
    if public:
        args.insert(1, "-pubin")
    code, out, err = run_openssl(args)
    if code != 0:
        raise RuntimeError("openssl could not read %s: %s" % (key_path, err.decode("utf-8", "replace").strip()))
    return hashlib.sha256(out).hexdigest()


def sign_ed25519(key_path: str, message_path: str) -> bytes:
    code, out, err = run_openssl(
        ["pkeyutl", "-sign", "-rawin", "-inkey", key_path, "-in", message_path])
    if code != 0:
        raise RuntimeError("openssl could not sign: %s" % err.decode("utf-8", "replace").strip())
    if len(out) != 64:
        raise RuntimeError("expected a raw 64-byte Ed25519 signature, openssl returned %d bytes" % len(out))
    return out


def verify_ed25519(pubkey_path: str, message_path: str, signature: bytes) -> tuple[bool, str]:
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".sig") as handle:
        handle.write(signature)
        sig_path = handle.name
    try:
        code, _out, err = run_openssl(
            ["pkeyutl", "-verify", "-rawin", "-pubin", "-inkey", pubkey_path,
             "-in", message_path, "-sigfile", sig_path])
    finally:
        try:
            os.unlink(sig_path)
        except OSError:
            pass
    if code == 0:
        return True, ""
    return False, err.decode("utf-8", "replace").strip() or "signature verification failed"


def b64_encode(data: bytes) -> str:
    return binascii.b2a_base64(data, newline=False).decode("ascii")


def b64_decode(text: str) -> bytes:
    return binascii.a2b_base64(text.strip())


def in_git_working_tree(path: str) -> bool:
    """True when `path` is inside a git working tree. Used to refuse signing
    with a private key that lives in a repository - custody rule #1."""
    current = os.path.abspath(path)
    if not os.path.isdir(current):
        current = os.path.dirname(current)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return True
        parent = os.path.dirname(current)
        if parent == current:
            return False
        current = parent


def warn(message: str) -> None:
    sys.stderr.write("warning: %s\n" % message)


def fail(message: str, code: int = 3) -> "None":
    sys.stderr.write("error: %s\n" % message)
    raise SystemExit(code)
