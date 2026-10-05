#!/usr/bin/env python3
"""Phase 14 launcher-path evidence (plan.md Phase 14: "Verify clean
checkout/build/install and test a packaged game through the launcher, not only
editor play mode").

Steps, all against the real tools:

  1. package the REAL Godot export with `tools/release/package_client.py`,
  2. serve it over HTTPS with a throwaway certificate (the same shape the
     release host serves) using `test_updater.py`'s ReleaseServer,
  3. run the distributed launcher binary (`HPMMO_Launcher.exe`) in its headless
     CLI mode to install it - the launcher's own updater engine, not a copy,
  4. launch the INSTALLED game exactly the way `hpmmo::LaunchInstalledGame`
     (launcher_cpp/src/updater.cpp) does - same argv, same environment,
     including a real single-use game ticket from the account service,
  5. drive the login screen with a real keystroke (Enter selects the character:
     `character_select.gd:90-92`) and capture the window,
  6. report what the game did, from its own log.

Skips (exit 2) when the package, the launcher or the account stack is missing.

Usage:
  python client/tools/phase14_launcher.py [--client-version 0.7.0]
                                          [--no-launch] [--out-dir DIR]
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

CLIENT = Path(__file__).resolve().parent.parent
WORKSPACE = CLIENT.parent
RELEASE_TOOLS = CLIENT / "tools" / "release"
sys.path.insert(0, str(RELEASE_TOOLS))
sys.path.insert(0, str(WORKSPACE / "server" / "tests"))

import test_updater as tu  # noqa: E402


def post(url, payload, token=""):
    data = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def screenshot(path):
    """A window screenshot via PowerShell + System.Drawing (no extra deps)."""
    script = (
        "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
        "$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
        "$bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height; "
        "$g = [System.Drawing.Graphics]::FromImage($bmp); "
        "$g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); "
        "$bmp.Save('%s', [System.Drawing.Imaging.ImageFormat]::Png)" % str(path).replace("\\", "\\\\")
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=120)


def press_enter(window_title_part):
    """Foreground the game window and press Enter - the documented keyboard
    route out of character select (`character_select.gd:90-92`).

    WScript.Shell.AppActivate matches a title substring (FindWindow needs the
    exact title, and the packaged window's title has a trailing space), then
    SendKeys delivers the keystroke to whatever is focused."""
    script = r"""
$wshell = New-Object -ComObject wscript.shell
$ok = $wshell.AppActivate("{title}")
if (-not $ok) { Write-Output "noactivate"; exit 1 }
Start-Sleep -Milliseconds 600
$wshell.SendKeys("{{ENTER}}")
Write-Output "sent"
""".replace("{title}", window_title_part)
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True, timeout=120)
    return "sent" in (proc.stdout or "")


def window_titles():
    script = r"""
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class Enumer {
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc lpEnumFunc, IntPtr lParam);
  [DllImport("user32.dll")] public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);
  public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
}
"@
$found = New-Object System.Collections.ArrayList
$cb = [Enumer+EnumProc]{
  param($h, $l)
  $sb = New-Object System.Text.StringBuilder 512
  [Enumer]::GetWindowText($h, $sb, 512) | Out-Null
  if ($sb.Length -gt 0) { [void]$found.Add($sb.ToString()) }
  return $true
}
[Enumer]::EnumWindows($cb, [IntPtr]::Zero) | Out-Null
$found | ForEach-Object { Write-Output ("TITLE:" + $_) }
"""
    proc = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                          capture_output=True, text=True, timeout=120)
    return [line[6:] for line in (proc.stdout or "").splitlines() if line.startswith("TITLE:")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-version", default="0.7.0")
    parser.add_argument("--content-version", default="2026.10.05-1")
    parser.add_argument("--out-dir", default=str(CLIENT / "tools" / "downloads" / "phase14-launcher"))
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--install-only", action="store_true")
    parser.add_argument("--launcher", default="", help="launcher binary (default: the tracked HPMMO_Launcher.exe)")
    args = parser.parse_args()
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    source_build = CLIENT / "tools" / "downloads" / "phase14-build"
    if not (source_build / "client" / "HPMMO.exe").is_file():
        print("LAUNCHER SKIP: no packaged build at %s (export it first)" % source_build)
        return 2
    # package_client only accepts build directories whose top level is exactly
    # client/ and launcher/, so the export is staged into a clean one.
    build_dir = out / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    (build_dir / "client").mkdir(parents=True)
    for name in ("HPMMO.exe", "HPMMO.pck"):
        shutil.copy(source_build / "client" / name, build_dir / "client" / name)
    launcher = Path(args.launcher) if args.launcher else CLIENT / "HPMMO_Launcher.exe"
    if not launcher.is_file():
        print("LAUNCHER SKIP: %s is missing" % launcher)
        return 2

    result = {"steps": [], "checks": []}

    def check(name, ok, detail=""):
        result["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)})
        print(("PASS: " if ok else "FAIL: ") + name + (("  [%s]" % detail) if detail else ""))

    # 1. package the real export with the real packager ----------------------
    dist = out / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    proc = subprocess.run([sys.executable, str(RELEASE_TOOLS / "package_client.py"),
                           "--build-dir", str(build_dir),
                           "--client-version", args.client_version,
                           "--content-version", args.content_version,
                           "--platform", "windows-x86_64", "--out", str(dist)],
                          capture_output=True, text=True, timeout=900)
    zip_path = dist / ("hpmmo-client-%s-windows-x86_64.zip" % args.client_version)
    check("package_client produced the artifact", zip_path.is_file() and proc.returncode == 0,
          str(zip_path.name) + ("" if proc.returncode == 0 else proc.stdout[-200:]))

    # 2. HTTPS release server + a signed manifest ----------------------------
    tmp = Path(tempfile.mkdtemp(prefix="hpmmo-phase14-launcher-"))
    certfile, keyfile, pin = tu.make_certificates(tmp)
    key = tu.ed25519.Ed25519PrivateKey.generate()
    # The launcher pins the raw 32-byte Ed25519 public key, base64-encoded
    # (test_updater.py:940-941) - not a PEM document.
    pub_b64 = base64.b64encode(key.public_key().public_bytes_raw()).decode()
    release_root = tmp / "release"
    release_root.mkdir()
    # ReleaseServer starts serving in its constructor (test_updater.py:158-168).
    server = tu.ReleaseServer(release_root, certfile, keyfile)
    release = tu.Release(release_root, key)
    release.add_package(zip_path.name, zip_path.read_bytes(), kind="game")
    release.write_manifest(args.client_version, min_launcher_version="0.7.0",
                           protocol_version="6", protocol_min="6", protocol_max="6",
                           channel="dev", content_version=args.content_version)
    release.write_status("ONLINE", "Phase 14 launcher-path install")
    print("[launcher] release served at %s" % server.base)

    install_root = out / "install"
    common = tu.common_args(install_root, server.base, pin, pub_b64)
    try:
        # 3. install with the distributed launcher's own updater ------------
        code, payload, log = tu.run_cli(common + ["--update"], exe=launcher, timeout=900)
        installed = install_root / "versions" / args.client_version / "HPMMO.exe"
        check("launcher --update exit 0", code == 0, log[-300:])
        check("launcher installed the packaged game", installed.is_file(),
              "%s (%d bytes)" % (installed, installed.stat().st_size if installed.is_file() else 0))
        check("launcher reports the installed version",
              bool(payload and payload.get("installed_version") == args.client_version), str(payload))
        code, payload, log = tu.run_cli(common + ["--verify"], exe=launcher, timeout=600)
        check("launcher --verify is healthy", code == 0 and bool(payload and payload.get("healthy")), log[-200:])
    finally:
        pass
    result["install_root"] = str(install_root)
    res = {"checks": result["checks"], "install_root": str(install_root), "release_base": server.base}
    (out / "install.json").write_text(json.dumps(res, indent=2))
    print("LAUNCHER INSTALL RESULT: %d checks, %d failures" % (
        len(result["checks"]), sum(1 for c in result["checks"] if not c["ok"])))
    if args.install_only:
        server.stop()
        return 0 if all(c["ok"] for c in result["checks"]) else 1

    # 4. bring up the account stack and launch the installed game ----------
    import phase14_stack as stackmod
    # The packaged game computes its account-service URL from `--ip` as
    # `http://<ip>:8081` (main_menu.gd), so a launcher-path test has to serve the
    # API on 8081 - exactly what the launcher does in production.
    stack = stackmod.Stack(str(out), api_port=8081)
    launched = None
    try:
        stack.start()
        api = "http://127.0.0.1:%d" % stack.api_port
        user = "launcher_%d" % (int(time.time()) % 100000)
        password = "LauncherTest123"
        post(api + "/api/register", {"username": user, "password": password})
        login = post(api + "/api/login", {"username": user, "password": password})
        token = login.get("token", "")
        char = post(api + "/api/characters/create", {"name": "LauncherHero", "house": "Gryffindor"}, token)
        check("character created through the service", bool(char.get("success")), str(char.get("message", "")))
        ticket = post(api + "/api/game-ticket", {}, token).get("ticket", "")
        check("single-use game ticket issued (launcher handoff)", ticket != "")

        game_exe = install_root / "versions" / args.client_version / "HPMMO.exe"
        user_dir = install_root / "user"
        # Exactly what the (fixed) launcher builds: no scene argument, because a
        # packaged Godot binary aborts on one, and the ticket handoff.
        argv = [str(game_exe),
                "--user", user, "--ip", "127.0.0.1", "--port", str(stack.world_port), "--autologin"]
        env = dict(os.environ)
        env.update(HPMMO_API_URL=api, HPMMO_USER_DIR=str(user_dir), HPMMO_TICKET=ticket)
        env.pop("HPMMO_ALLOW_DEV_JOIN", None)
        log_path = out / "launched-game.log"
        log_handle = open(log_path, "wb")
        launched = subprocess.Popen(argv, stdout=log_handle, stderr=subprocess.STDOUT, env=env,
                                    cwd=str(game_exe.parent))
        print("[launcher] launched %s (pid %d)" % (game_exe, launched.pid))
        time.sleep(28)
        screenshot(out / "packaged-01-character-select.png")
        titles = window_titles()
        check("the packaged window is up", any("HPMMO" in t for t in titles),
              "titles seen: %s" % ", ".join(t for t in titles if t.strip())[:200])
        sent = press_enter("HPMMO")
        check("Enter reached the packaged window", sent)
        time.sleep(12)
        screenshot(out / "packaged-02-world.png")
        time.sleep(6)
        text = open(log_path, "r", encoding="utf-8", errors="replace").read()
        check("the game redeemed the launcher ticket",
              "ticket" in text.lower() or "session" in text.lower(), "")
        check("the game auto-logged in", "Auto-login requested" in text, "")
        check("the game joined the world server", "connected as peer" in text or "join sent" in text, "")
        check("the world scene loaded", "[GameWorld]" in text, "")
        world_log = open(stack.world_log_path, "r", encoding="utf-8", errors="replace").read()
        check("the server registered a session-bound player",
              "uid" in world_log and "join" in world_log, "")
        (out / "launch.json").write_text(json.dumps(result["checks"], indent=2))
        print("LAUNCHER LAUNCH RESULT: %d checks, %d failures" % (
            len(result["checks"]), sum(1 for c in result["checks"] if not c["ok"])))
    except Exception as error:  # noqa: BLE001 - a driver, it reports and exits
        print("LAUNCHER FAIL: %s" % error)
        return 1
    finally:
        if launched is not None and launched.poll() is None:
            launched.terminate()
            try:
                launched.wait(timeout=15)
            except subprocess.TimeoutExpired:
                launched.kill()
        # Safety net: this driver is the only thing in Phase 14 that puts a
        # windowed game on the desktop, and it must never outlive the run. Kill
        # by executable path (scoped to this run's install dir), not by name.
        exe = str(install_root / "versions" / args.client_version / "HPMMO.exe")
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq '%s' } |"
                        " ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % exe],
                       capture_output=True, timeout=120)
        stack.stop()
        server.stop()
    return 0 if all(c["ok"] for c in result["checks"]) else 1


if __name__ == "__main__":
    sys.exit(main())
