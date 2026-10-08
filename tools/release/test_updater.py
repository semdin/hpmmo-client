#!/usr/bin/env python3
"""Release pipeline native launcher updater tests.

Runs the headless launcher CLI (HPMMO_UpdaterCLI.exe) against a local HTTPS
release server with a self-signed, pinned certificate and fake signed releases.

Covers the plan's exit checks: install from an older version; interrupt/resume;
reject a tampered package (zip bytes and manifest signature); insufficient disk
space (staging quota); repair a deleted/corrupt file; settings preserved across
updates; recover after interruption during activation; maintenance displayed;
incompatible protocol refused without a login loop; plus pinning, the unsafe
archive rules, the running-game guard and launcher self-update.

Usage:
    python client/tools/release/test_updater.py [--launcher PATH]

Prints "UPDATER RESULT: N checks, M failures" and exits non-zero on failure.
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import http.server
import io
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

HERE = Path(__file__).resolve().parent
CLIENT = HERE.parent.parent
DEFAULT_LAUNCHER = CLIENT / "launcher_cpp" / "build" / "HPMMO_UpdaterCLI.exe"
DEFAULT_GUI_LAUNCHER = CLIENT / "launcher_cpp" / "build" / "HPMMO_Launcher.exe"

CHECKS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    CHECKS.append((name, bool(cond), detail))
    status = "ok" if cond else "FAIL"
    line = f"[{status}] {name}"
    if detail and not cond:
        line += f" -- {detail}"
    print(line, flush=True)
    return bool(cond)


# --------------------------------------------------------------- test server --


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "HPMMORelease/1.0"

    def log_message(self, *_args):  # keep the output clean
        pass

    def _send(self, status, body: bytes, headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        srv = self.server
        if not path.startswith("/files/") and path not in ("/manifest.json",
                                                           "/manifest.json.sig",
                                                           "/SHA256SUMS", "/status.json"):
            self._send(404, b"not found")
            return
        if path.startswith("/files/"):
            name = path[len("/files/"):]
            if "/" in name or "\\" in name or name.startswith("."):
                self._send(404, b"not found")
                return
            full = srv.release_root / "files" / name
        else:
            full = srv.release_root / path.lstrip("/")
        if not full.is_file():
            self._send(404, b"not found")
            return
        data = full.read_bytes()
        start = 0
        status = 200
        headers = {"Content-Type": "application/octet-stream"}
        rng = self.headers.get("Range")
        if rng and rng.startswith("bytes="):
            try:
                spec = rng[len("bytes="):].split(",")[0].strip()
                if spec.endswith("-"):
                    start = int(spec[:-1])
                else:
                    a, b = spec.split("-", 1)
                    start = int(a)
                if start < 0 or start > len(data):
                    self._send(416, b"range not satisfiable",
                               {"Content-Range": f"bytes */{len(data)}"})
                    return
                status = 206
                headers["Content-Range"] = f"bytes {start}-{len(data)-1}/{len(data)}"
                srv.range_log.append(start)
            except ValueError:
                start = 0
                status = 200
        body = data[start:]

        # Interruption simulation: announce the full length, send half, close.
        if srv.drop_mode and srv.drop_target == path:
            half = max(1, len(body) // 2)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body[:half])
                self.wfile.flush()
            except OSError:
                pass
            if srv.drop_mode == "once":
                srv.drop_mode = None
            try:
                self.connection.close()
            except OSError:
                pass
            return

        try:
            self._send(status, body, headers)
        except OSError:
            pass


class QuietServer(http.server.ThreadingHTTPServer):
    # WinHTTP closes idle keep-alive sockets; that is not a server error.
    def handle_error(self, request, client_address):
        pass


class ReleaseServer:
    def __init__(self, release_root: Path, certfile: Path, keyfile: Path):
        self.release_root = release_root
        self.httpd = QuietServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(certfile), keyfile=str(keyfile))
        self.httpd.socket = ctx.wrap_socket(self.httpd.socket, server_side=True)
        self.httpd.release_root = release_root
        self.httpd.range_log = []
        self.httpd.drop_target = None
        self.httpd.drop_mode = None
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def port(self) -> int:
        return self.httpd.server_address[1]

    @property
    def base(self) -> str:
        return f"https://127.0.0.1:{self.port}"

    def clear_ranges(self):
        self.httpd.range_log.clear()

    def ranges(self):
        return list(self.httpd.range_log)

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


# ------------------------------------------------------------------ releases --


def make_certificates(tmp: Path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "hpmmo-test")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=30))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(__import__("ipaddress").ip_address("127.0.0.1")),
                 x509.DNSName("localhost")]
            ),
            critical=False,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256())
    )
    certfile = tmp / "server-cert.pem"
    keyfile = tmp / "server-key.pem"
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(
        key.private_bytes(serialization.Encoding.PEM,
                          serialization.PrivateFormat.TraditionalOpenSSL,
                          serialization.NoEncryption())
    )
    spki = cert.public_key().public_bytes(serialization.Encoding.DER,
                                          serialization.PublicFormat.SubjectPublicKeyInfo)
    pin = hashlib.sha256(spki).hexdigest()
    return certfile, keyfile, pin


def build_package(files: dict[str, bytes], bad_entries: list | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name, data in files.items():
            z.writestr(name, data)
        for entry in bad_entries or []:
            z.writestr(entry, b"evil")
    return buf.getvalue()


class Release:
    """Writes a signed manifest + status document into the release root."""

    def __init__(self, root: Path, signing_key: ed25519.Ed25519PrivateKey):
        self.root = root
        self.key = signing_key
        (root / "files").mkdir(parents=True, exist_ok=True)
        self.artifacts: list[dict] = []
        self.sha256sums: list[str] = []

    def add_package(self, filename: str, data: bytes, kind="game", from_version="") -> dict:
        (self.root / "files" / filename).write_bytes(data)
        art = {
            "kind": kind,
            "from_version": from_version,
            "url": f"files/{filename}",
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        self.artifacts.append(art)
        self.sha256sums.append(f"{art['sha256']}  {filename}")
        return art

    def write_manifest(
        self,
        client_version: str,
        *,
        min_launcher_version: str = "0.0.0",
        protocol_version: str = "4",
        protocol_min: str = "4",
        protocol_max: str = "4",
        channel: str = "stable",
        server_version: str = "0.9.0",
        release_notes: str = "Test release",
        content_version: str = "1",
        platform: str = "windows-x86_64",
        artifacts: list[dict] | None = None,
    ) -> bytes:
        manifest = {
            "channel": channel,
            "client_version": client_version,
            "min_launcher_version": min_launcher_version,
            "protocol_version": protocol_version,
            "protocol_min": protocol_min,
            "protocol_max": protocol_max,
            "content_version": content_version,
            "content_sha256": hashlib.sha256(b"content-" + client_version.encode()).hexdigest(),
            "server_version": server_version,
            "schema_version": "4",
            "platform": platform,
            "published_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "release_notes": release_notes,
            "artifacts": artifacts if artifacts is not None else self.artifacts,
        }
        raw = json.dumps(manifest, separators=(",", ":"), sort_keys=False).encode()
        (self.root / "manifest.json").write_bytes(raw)
        sig = self.key.sign(raw)
        (self.root / "manifest.json.sig").write_text(base64.b64encode(sig).decode() + "\n")
        (self.root / "SHA256SUMS").write_text("\n".join(self.sha256sums) + "\n")
        return raw

    def write_status(self, state: str, message: str = "", **extra) -> None:
        doc = {
            "state": state,
            "release": extra.pop("release", "0.9.0"),
            "previous_release": extra.pop("previous_release", ""),
            "since": extra.pop("since", dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
            "message": message,
        }
        doc.update(extra)
        (self.root / "status.json").write_text(json.dumps(doc))


# --------------------------------------------------------------- CLI runner --


def run_cli(args: list[str], timeout: int = 240, env=None, exe=None):
    proc = subprocess.run(
        [str(exe or ARGS.launcher), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    payload = None
    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if lines:
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError:
            payload = None
    return proc.returncode, payload, (proc.stdout or "") + (proc.stderr or "")


def common_args(root: Path, base: str, pin: str, pubkey: str, extra: list[str] | None = None):
    args = [
        "--config", str(root / "client_config.json"),
        "--install-root", str(root),
        "--user-dir", str(root / "user"),
        "--release-base", base,
        "--pinned-spki", pin,
        "--public-key", pubkey,
        "--public-key-id", "hpmmo-test-key",
    ]
    args += extra or []
    return args


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# -------------------------------------------------------------------- tests --


def test_install_and_update(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                            pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)

    pkg_110 = build_package({
        "HPMMO.exe": b"GAME-1.1.0",
        "data/level.pck": b"level-1.1.0" * 200,
    })
    release.add_package("game-1.1.0.zip", pkg_110)
    release.write_manifest("1.1.0")
    release.write_status("ONLINE", "Server is up")

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check"])
    check("check/older: exit 0", rc == 0, log)
    check("check/older: update available", bool(js and js.get("update_available")), log)
    check("check/older: online state", bool(js and js.get("state") == "ONLINE"), log)

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("update/older: exit 0", rc == 0, log)
    check("update/older: activated 1.1.0", bool(js and js.get("installed_version") == "1.1.0"), log)
    active = root / "versions" / "1.1.0" / "HPMMO.exe"
    check("update/older: game files installed", active.is_file() and
          active.read_bytes() == b"GAME-1.1.0", f"missing {active}")
    current = json.loads((root / "current.json").read_text()) if (root / "current.json").is_file() else {}
    check("update/older: current.json points at 1.1.0", current.get("version") == "1.1.0", str(current))

    rc, js, _ = run_cli(common_args(root, server.base, pin, pubkey) + ["--check"])
    check("check/current: no update available", bool(js and not js.get("update_available")), str(js))

    # Now publish 1.2.0 and update from the older version.
    release2 = Release(rel, signer)
    pkg_120 = build_package({
        "HPMMO.exe": b"GAME-1.2.0",
        "data/level.pck": b"level-1.2.0" * 200,
        "data/new.txt": b"brand new",
    })
    release2.add_package("game-1.2.0.zip", pkg_120)
    release2.write_manifest("1.2.0", release_notes="New spells and a repaired castle gate.")
    release2.write_status("ONLINE")

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check"])
    check("check/upgrade: update available from 1.1.0", bool(js and js.get("installed_version") == "1.1.0" and js.get("update_available")), log)

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("update/upgrade: exit 0", rc == 0, log)
    check("update/upgrade: activated 1.2.0", bool(js and js.get("installed_version") == "1.2.0"), log)
    current = json.loads((root / "current.json").read_text())
    check("update/upgrade: previous kept", current.get("previous") == "1.1.0", str(current))
    check("update/upgrade: old version still on disk", (root / "versions" / "1.1.0").is_dir())
    check("update/upgrade: new files correct",
          (root / "versions" / "1.2.0" / "HPMMO.exe").read_bytes() == b"GAME-1.2.0")

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--verify"])
    check("verify: healthy after update", rc == 0 and bool(js and js.get("healthy")), log)

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("update: idempotent when current", rc == 0 and bool(js and js.get("update_available") is False), log)

    rc, js, _ = run_cli(common_args(root, server.base, pin, pubkey) + ["--print-state"])
    check("print-state: reports installed version", rc == 0 and js.get("installed_version") == "1.2.0", str(js))
    check("print-state: launcher version", js.get("launcher_version") == "2.0.0", str(js))


def test_resume(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    blob = os.urandom(6 * 1024 * 1024)
    pkg = build_package({"HPMMO.exe": b"GAME-1.2.0", "data/blob.bin": blob})
    art = release.add_package("game-1.2.0.zip", pkg)
    release.write_manifest("1.2.0")
    release.write_status("ONLINE")

    server.httpd.drop_target = "/files/game-1.2.0.zip"
    server.httpd.drop_mode = "always"
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    parts = list((root / "staging").glob("*.part")) if (root / "staging").is_dir() else []
    check("resume: interrupted download fails cleanly", rc == 13, log)
    check("resume: partial file kept for resume",
          len(parts) == 1 and 0 < parts[0].stat().st_size < art["size"],
          f"parts={parts}")

    server.httpd.drop_mode = None
    server.clear_ranges()
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("resume: second run succeeds", rc == 0, log)
    check("resume: resumed with a Range request",
          any(r > 0 for r in server.ranges()) and
          (root / "versions" / "1.2.0" / "data" / "blob.bin").read_bytes() == blob,
          f"ranges={server.ranges()[:5]}")


def test_tampered(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                  pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    pkg = build_package({"HPMMO.exe": b"GAME-1.2.0"})
    release.add_package("game-1.2.0.zip", pkg)
    release.write_manifest("1.2.0")
    release.write_status("ONLINE")

    # Flip a byte in the package after the manifest hash was recorded.
    zip_path = rel / "files" / "game-1.2.0.zip"
    data = bytearray(zip_path.read_bytes())
    data[len(data) // 2] ^= 0x40
    zip_path.write_bytes(data)

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("tamper/zip: refused with integrity error", rc == 16, log)
    check("tamper/zip: message mentions hash", bool(js and "hash mismatch" in js.get("message", "")), str(js))
    check("tamper/zip: nothing activated", not (root / "current.json").exists())

    # Tampered manifest signature.
    release.write_manifest("1.3.0")
    sig_path = rel / "manifest.json.sig"
    sig = bytearray(base64.b64decode(sig_path.read_text()))
    sig[5] ^= 0x01
    sig_path.write_text(base64.b64encode(bytes(sig)).decode() + "\n")
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check"])
    check("tamper/signature: refused with signature error", rc == 11, log)
    check("tamper/signature: message mentions signature",
          bool(js and "signature" in js.get("message", "").lower()), str(js))


def test_disk_space(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                    pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    release.add_package("game-1.2.0.zip", build_package({"HPMMO.exe": b"G" * (4 << 20)}))
    release.write_manifest("1.2.0")
    release.write_status("ONLINE")

    args = common_args(root, server.base, pin, pubkey) + ["--update", "--staging-quota", "1048576"]
    rc, js, log = run_cli(args)
    check("disk: refused with disk-space code", rc == 14, log)
    check("disk: message explains the shortfall",
          bool(js and "insufficient disk space" in js.get("message", "")), str(js))
    check("disk: nothing was downloaded", not (root / "staging").exists() or
          not list((root / "staging").glob("*.part")))


def test_repair(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    release.add_package("game-1.2.0.zip",
                        build_package({"HPMMO.exe": b"GAME-1.2.0", "data/level.pck": b"level-data"}))
    release.write_manifest("1.2.0")
    release.write_status("ONLINE")
    rc, _, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("repair: baseline install", rc == 0, log)

    (root / "versions" / "1.2.0" / "data" / "level.pck").unlink()
    exe = root / "versions" / "1.2.0" / "HPMMO.exe"
    exe.write_bytes(b"GAME-1.2.0-CORRUPTED")

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--verify"])
    check("repair: verify detects damage", rc == 20 and js.get("healthy") is False, log)
    check("repair: missing file listed", bool(js and "data/level.pck" in js.get("missing", [])), str(js))
    check("repair: corrupt file listed", bool(js and "HPMMO.exe" in js.get("corrupt", [])), str(js))

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--repair"])
    check("repair: exit 0", rc == 0, log)
    check("repair: two files repaired", bool(js and js.get("repaired") == 2), str(js))
    check("repair: file restored",
          (root / "versions" / "1.2.0" / "data" / "level.pck").read_bytes() == b"level-data")
    check("repair: exe hash restored",
          (root / "versions" / "1.2.0" / "HPMMO.exe").read_bytes() == b"GAME-1.2.0")

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--verify"])
    check("repair: verify healthy afterwards", rc == 0 and js.get("healthy") is True, log)


def test_settings_preserved(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                            pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    release.add_package("game-1.1.0.zip", build_package({"HPMMO.exe": b"GAME-1.1.0"}))
    release.write_manifest("1.1.0")
    release.write_status("ONLINE")
    rc, _, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("settings: baseline install", rc == 0, log)

    user = root / "user"
    user.mkdir(parents=True, exist_ok=True)
    settings = user / "settings.json"
    keybinds = user / "keybinds.cfg"
    shot = user / "screenshots" / "first.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text('{"volume":0.42}')
    keybinds.write_text("jump=space\n")
    shot.write_bytes(b"PNG")
    before = {str(p): (p.stat().st_mtime_ns, sha256_file(p)) for p in (settings, keybinds, shot)}

    release2 = Release(rel, signer)
    release2.add_package("game-1.2.0.zip", build_package({"HPMMO.exe": b"GAME-1.2.0"}))
    release2.write_manifest("1.2.0")
    release2.write_status("ONLINE")
    rc, _, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("settings: update succeeded", rc == 0, log)
    after = {str(p): (p.stat().st_mtime_ns, sha256_file(p)) for p in (settings, keybinds, shot)}
    check("settings: user files untouched", before == after, f"{before} vs {after}")
    check("settings: no settings leaked into versions",
          not (root / "versions" / "1.2.0" / "settings.json").exists() and
          not (root / "versions" / "1.2.0" / "keybinds.cfg").exists())
    check("settings: user dir outside versions",
          "versions" not in str(user).split("1.2.0")[0].lower())


def test_activation_recovery(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                             pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    release.add_package("game-1.1.0.zip", build_package({"HPMMO.exe": b"GAME-1.1.0"}))
    release.write_manifest("1.1.0")
    release.write_status("ONLINE")
    rc, _, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("recovery: baseline install", rc == 0, log)

    release2 = Release(rel, signer)
    release2.add_package("game-1.2.0.zip", build_package({"HPMMO.exe": b"GAME-1.2.0"}))
    release2.write_manifest("1.2.0")
    release2.write_status("ONLINE")

    # Stop between staging and the active-version switch.
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update", "--stop-after", "stage"])
    check("recovery: stop-after stage exits 0", rc == 0 and js.get("stage") == "stage", log)
    journal = root / "pending_activation.json"
    check("recovery: journal written", journal.is_file())
    check("recovery: staged dir present", (root / "versions" / "1.2.0.tmp").is_dir())
    current = json.loads((root / "current.json").read_text())
    check("recovery: still active on 1.1.0", current.get("version") == "1.1.0", str(current))

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("recovery: re-run completes activation", rc == 0 and js.get("installed_version") == "1.2.0", log)
    check("recovery: journal cleared", not journal.exists())

    # Harder kill: rename happened, pointer not written.
    release3 = Release(rel, signer)
    release3.add_package("game-1.3.0.zip", build_package({"HPMMO.exe": b"GAME-1.3.0"}))
    release3.write_manifest("1.3.0")
    release3.write_status("ONLINE")
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update", "--stop-after", "stage"])
    check("recovery2: stop-after stage", rc == 0, log)
    os.rename(root / "versions" / "1.3.0.tmp", root / "versions" / "1.3.0")
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    current = json.loads((root / "current.json").read_text())
    check("recovery2: interrupted rename recovered", rc == 0 and current.get("version") == "1.3.0", log + str(current))
    check("recovery2: journal cleared", not journal.exists())


def test_maintenance(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                     pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    release.add_package("game-1.2.0.zip", build_package({"HPMMO.exe": b"GAME-1.2.0"}))
    release.write_manifest("1.2.0")
    release.write_status("MAINTENANCE", "Veritabani yukseltmesi: 20 dk", until="2026-10-04T13:00:00Z")

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check"])
    check("maintenance: check still exits 0", rc == 0, log)
    check("maintenance: state reported", bool(js and js.get("state") == "MAINTENANCE"), str(js))
    check("maintenance: reason shown", bool(js and "Veritabani" in js.get("message", "")), str(js))
    check("maintenance: since/until shown", bool(js and js.get("since") and js.get("until")), str(js))

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check", "--for-launch"])
    check("maintenance: launch refused with code 17", rc == 17, log)
    check("maintenance: release notes available for GUI", bool(js and "release_notes" in js), str(js))

    release.write_status("ONLINE")
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check", "--for-launch"])
    check("maintenance: launch allowed when online", rc == 0, log)


def test_protocol(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                  pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    release.add_package("game-1.2.0.zip", build_package({"HPMMO.exe": b"GAME-1.2.0"}))
    release.write_manifest("1.2.0", protocol_version="4", protocol_min="5", protocol_max="6")
    release.write_status("ONLINE")

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check"])
    check("protocol: mismatch reported", rc == 0 and js.get("protocol_ok") is False, log)
    check("protocol: server protocol echoed", js.get("server_protocol") == "4", str(js))
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check", "--for-launch"])
    check("protocol: launch refused without a login loop", rc == 12, log)
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("protocol: update refuses incompatible build", rc == 12, log)
    check("protocol: nothing downloaded", not (root / "staging" / "files").exists() and
          not list((root / "staging").glob("*.part")) if (root / "staging").is_dir() else True)

    release.write_manifest("1.2.0", protocol_version="4", protocol_min="4", protocol_max="4")
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check", "--for-launch"])
    check("protocol: compatible range accepted", rc == 0, log)


def test_game_running(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                      pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    release.add_package("game-1.1.0.zip", build_package({"HPMMO.exe": b"GAME-1.1.0"}))
    release.write_manifest("1.1.0")
    release.write_status("ONLINE")
    rc, _, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("game-running: baseline install", rc == 0, log)

    release2 = Release(rel, signer)
    release2.add_package("game-1.2.0.zip", build_package({"HPMMO.exe": b"GAME-1.2.0"}))
    release2.write_manifest("1.2.0")
    release2.write_status("ONLINE")

    ping_src = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "ping.exe"
    fake_game = root / "versions" / "1.1.0" / "ping.exe"
    shutil.copy(str(ping_src), str(fake_game))
    proc = subprocess.Popen([str(fake_game), "-n", "120", "127.0.0.1"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.8)
        rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
        check("game-running: update refused", rc == 15, log)
        check("game-running: message names the process",
              bool(js and "game is running" in js.get("message", "")), str(js))
        current = json.loads((root / "current.json").read_text())
        check("game-running: active version untouched", current.get("version") == "1.1.0", str(current))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    time.sleep(0.5)
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("game-running: update proceeds after exit", rc == 0, log)


def test_self_update(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                     pin: str, pubkey: str, gui_launcher: Path):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    if not gui_launcher.is_file():
        check("self-update: GUI launcher present", False, str(gui_launcher))
        return
    running_copy = root / "HPMMO_Launcher.exe"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(str(ARGS.launcher), str(running_copy))

    release = Release(rel, signer)
    new_launcher = gui_launcher.read_bytes()
    release.add_package("launcher-9.9.9.exe", new_launcher, kind="launcher")
    release.write_manifest("9.9.9", min_launcher_version="9.9.9")
    release.write_status("ONLINE")

    args = common_args(root, server.base, pin, pubkey) + ["--update"]
    proc = subprocess.run([str(running_copy), *args], capture_output=True, text=True, timeout=240)
    js = None
    for line in reversed((proc.stdout or "").splitlines()):
        try:
            js = json.loads(line)
            break
        except Exception:
            continue
    check("self-update: exit code 18", proc.returncode == 18, proc.stdout + proc.stderr)
    check("self-update: helper handed off", bool(js and js.get("self_update")), str(js))

    deadline = time.time() + 40
    target = sha256_file(gui_launcher)
    swapped = False
    while time.time() < deadline:
        if sha256_file(running_copy) == target:
            swapped = True
            break
        time.sleep(0.5)
    check("self-update: launcher replaced by the verified new build", swapped,
          f"target hash {sha256_file(running_copy)[:12]} != {target[:12]}")
    log_file = root / "launcher.log"
    check("self-update: logged", log_file.is_file() and
          "self-update" in log_file.read_text(errors="ignore"))


def test_pinning(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                 pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    release.add_package("game-1.2.0.zip", build_package({"HPMMO.exe": b"GAME-1.2.0"}))
    release.write_manifest("1.2.0")
    release.write_status("ONLINE")

    rc, js, log = run_cli(["--install-root", str(root), "--user-dir", str(root / "user"),
                           "--print-cert-pin", server.base + "/manifest.json"])
    check("pin: print-cert-pin works", rc == 0 and js.get("cert_spki_sha256") == pin, log)

    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--check"])
    check("pin: pinned certificate accepted", rc == 0, log)

    rc, js, log = run_cli(common_args(root, server.base, "00" * 32, pubkey) + ["--check"])
    check("pin: wrong pin refused", rc == 11, log)
    check("pin: mismatch named", bool(js and "pin mismatch" in js.get("message", "")), str(js))
    check("pin: nothing trusted from the wrong server", not (root / "launcher_state.json").exists())

    rc, js, log = run_cli(["--config", str(root / "client_config.json"),
                           "--install-root", str(root), "--release-base", server.base,
                           "--pinned-spki", pin, "--check"])
    check("pin: unprovisioned key fails closed", rc == 3, log)
    check("pin: message names the public key", bool(js and "public key" in js.get("message", "")), str(js))


def test_unsafe_archive(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                        pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    release.add_package("game-1.2.0.zip",
                        build_package({"HPMMO.exe": b"GAME"}, bad_entries=["../escape.txt"]))
    release.write_manifest("1.2.0")
    release.write_status("ONLINE")
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("zip-slip: traversal rejected", rc == 16, log)
    check("zip-slip: nothing written outside", not (root.parent / "escape.txt").exists())
    check("zip-slip: no activation", not (root / "current.json").exists())

    # A symlink entry carries its file type in the high 16 bits of
    # external_attr, and archives normally record a UNIX "version made by" host
    # byte (3) to explain that field. Python's zipfile picks the host byte from
    # the machine it runs on (0 = MS-DOS on Windows, 3 = UNIX elsewhere), so a
    # test that leaves it implicit builds a DIFFERENT archive on each platform
    # and one that a launcher gating on the host byte reads differently. Pin
    # both encodings explicitly: "extract a symlink as a regular file" is the
    # failure this must never allow, whatever the host byte says, and the
    # observed intermittent failure (an update that installed an MS-DOS-hosted
    # symlink entry and reported ok:true) came from exactly that gate.
    for host_byte, host in ((0, "ms-dos"), (3, "unix")):
        version = "1.3.%d" % host_byte
        release2 = Release(rel, signer)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("HPMMO.exe", b"GAME")
            info = zipfile.ZipInfo("link.txt")
            info.create_system = host_byte
            info.external_attr = (0o120777 << 16)
            z.writestr(info, b"target")
        release2.add_package("game-%s.zip" % version, buf.getvalue())
        release2.write_manifest(version)
        release2.write_status("ONLINE")
        rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
        where = "host %s" % host
        check("zip-slip: symlink rejected (%s)" % where, rc == 16,
              "rc=%d json=%s\n%s" % (rc, js, log))
        check("zip-slip: message names the entry (%s)" % where,
              bool(js and "symlink" in js.get("message", "")),
              "rc=%d json=%s\n%s" % (rc, js, log))

    release3 = Release(rel, signer)
    release3.add_package("game-1.4.0.zip",
                         build_package({"HPMMO.exe": b"GAME"}, bad_entries=["/abs.txt"]))
    release3.write_manifest("1.4.0")
    release3.write_status("ONLINE")
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("zip-slip: absolute path rejected", rc == 16 and
          bool(js and "absolute" in js.get("message", "")), log)


def test_compression_methods(t: Path, server: ReleaseServer, signer: ed25519.Ed25519PrivateKey,
                             pin: str, pubkey: str):
    root = t / "install"
    rel = t / "rel"
    rel.mkdir()
    server.httpd.release_root = rel
    release = Release(rel, signer)
    stored = os.urandom(200000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("HPMMO.exe", b"GAME-1.2.0")
        zi = zipfile.ZipInfo("data/stored.bin")
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, stored)
        z.writestr("data/fast.bin", b"fast" * 5000, compress_type=zipfile.ZIP_DEFLATED,
                   compresslevel=1)
    release.add_package("game-1.2.0.zip", buf.getvalue())
    release.write_manifest("1.2.0")
    release.write_status("ONLINE")
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("zip-methods: stored + deflate accepted", rc == 0, log)
    check("zip-methods: stored payload intact",
          (root / "versions" / "1.2.0" / "data" / "stored.bin").read_bytes() == stored)

    release2 = Release(rel, signer)
    buf2 = io.BytesIO()
    with zipfile.ZipFile(buf2, "w") as z:
        z.writestr("HPMMO.exe", b"GAME-1.3.0", compress_type=zipfile.ZIP_BZIP2)
    release2.add_package("game-1.3.0.zip", buf2.getvalue())
    release2.write_manifest("1.3.0")
    release2.write_status("ONLINE")
    rc, js, log = run_cli(common_args(root, server.base, pin, pubkey) + ["--update"])
    check("zip-methods: bzip2 rejected", rc == 16, log)
    check("zip-methods: rejection names the method",
          bool(js and "compression method" in js.get("message", "")), str(js))


def test_cleanup_and_usage(t: Path, _server, _signer, _pin, _pubkey):
    rc, js, log = run_cli(["--bogus-flag"])
    check("usage: unknown flag exits 2", rc == 2, log)
    rc, js, log = run_cli(["--print-state", "--install-root", str(t / "nothing")])
    check("print-state: empty install still works", rc == 0 and js.get("has_active_install") is False, log)
    check("print-state: exactly one JSON line",
          len([ln for ln in (log or "").splitlines() if ln.strip().startswith("{")]) == 1, log)

    if ARGS.gui_launcher.is_file():
        rc, js, log = run_cli(["--print-state", "--install-root", str(t / "nothing-gui")],
                              exe=ARGS.gui_launcher)
        check("gui exe: headless print-state works", rc == 0 and bool(js) and
              js.get("command") == "print-state", log)
        check("gui exe: exactly one JSON line",
              len([ln for ln in (log or "").splitlines() if ln.strip().startswith("{")]) == 1, log)
    else:
        check("gui exe present", False, str(ARGS.gui_launcher))


# --------------------------------------------------------------------- main --


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--launcher", default=str(DEFAULT_LAUNCHER))
    parser.add_argument("--gui-launcher", default=str(DEFAULT_GUI_LAUNCHER))
    global ARGS
    ARGS = parser.parse_args()
    ARGS.launcher = Path(ARGS.launcher)
    ARGS.gui_launcher = Path(ARGS.gui_launcher)

    if not ARGS.launcher.is_file():
        print(f"launcher not found: {ARGS.launcher}")
        print("build it first: cmake -S client/launcher_cpp -B client/launcher_cpp/build "
              "-G Ninja -DCMAKE_CXX_COMPILER=clang++ && ninja -C client/launcher_cpp/build")
        return 2

    # Fresh random test key per run: no signing key is ever stored in the tree.
    signer = ed25519.Ed25519PrivateKey.generate()
    pubkey = base64.b64encode(signer.public_key().public_bytes_raw()).decode()

    tests = [
        test_install_and_update,
        test_resume,
        test_tampered,
        test_disk_space,
        test_repair,
        test_settings_preserved,
        test_activation_recovery,
        test_maintenance,
        test_protocol,
        test_game_running,
        test_self_update,
        test_pinning,
        test_unsafe_archive,
        test_compression_methods,
        test_cleanup_and_usage,
    ]

    with tempfile.TemporaryDirectory(prefix="hpmmo-updater-test-") as tmp:
        tmp_path = Path(tmp)
        certfile, keyfile, pin = make_certificates(tmp_path)
        release_root = tmp_path / "release-root"
        release_root.mkdir()
        server = ReleaseServer(release_root, certfile, keyfile)
        try:
            for test in tests:
                case = tmp_path / test.__name__
                case.mkdir()
                work = case / "work"
                work.mkdir()
                server.httpd.drop_mode = None
                server.httpd.drop_target = None
                server.clear_ranges()
                print(f"\n=== {test.__name__} ===", flush=True)
                try:
                    if test is test_self_update:
                        test(work, server, signer, pin, pubkey, ARGS.gui_launcher)
                    else:
                        test(work, server, signer, pin, pubkey)
                except Exception as exc:  # keep going; report as a failure
                    import traceback
                    traceback.print_exc()
                    check(f"{test.__name__}: no exception", False, repr(exc))
        finally:
            server.stop()

    failures = sum(1 for _, ok, _ in CHECKS if not ok)
    print(f"\nUPDATER RESULT: {len(CHECKS)} checks, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
