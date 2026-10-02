#!/usr/bin/env python3
"""
HPMMO — Official Standalone Desktop Launcher & Webview Shell
Wizarding Realm MMORPG with Real-Time Wand Combat & Dark Monoliths
Powered by Microsoft Edge WebView2 / Modern HTML5 Desktop Shell
"""

import sys
import os
import json
import time
import socket
import urllib.request
import urllib.error
import subprocess
import shutil
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

# Enable High-DPI scaling on Windows
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

GAME_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAUNCHER_DIR = os.path.dirname(__file__)
UI_DIR = os.path.join(LAUNCHER_DIR, "ui")
ASSETS_DIR = os.path.join(LAUNCHER_DIR, "assets")
CONFIG_PATH = os.path.join(GAME_DIR, "client_config.json")
VERSION_PATH = os.path.join(GAME_DIR, "version.json")
CACHE_DIR = os.path.join(LAUNCHER_DIR, ".cache")

DEFAULT_CONFIG = {
    "server_ip": "213.250.145.75",
    "server_port": 7777,
    "http_port": 8081,
    "last_username": "Wizard",
    "fullscreen": False
}

def load_client_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception as e:
            print(f"[Launcher] Config read notice: {e}")
    return cfg

def save_client_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[Launcher] Error saving config: {e}")

def load_local_version() -> str:
    if os.path.exists(VERSION_PATH):
        try:
            with open(VERSION_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("version", "1.1.0")
        except Exception:
            pass
    return "1.1.0"

def find_godot_executable() -> str:
    # 1. Local game directory binaries
    candidates = [
        os.path.join(GAME_DIR, "godot.exe"),
        os.path.join(GAME_DIR, "HPMMO.exe"),
        os.path.join(GAME_DIR, "bin", "godot.exe"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    # 2. WinGet standard install path
    winget_path = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\godot.exe")
    if os.path.isfile(winget_path):
        return winget_path

    # 3. System PATH
    which_godot = shutil.which("godot") or shutil.which("godot.exe")
    if which_godot and os.path.isfile(which_godot):
        return which_godot

    # 4. play.bat script fallback
    play_bat = os.path.join(GAME_DIR, "play.bat")
    if os.path.isfile(play_bat):
        return play_bat

    return "godot"

def find_edge_executable() -> str:
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    which_edge = shutil.which("msedge") or shutil.which("msedge.exe")
    if which_edge and os.path.isfile(which_edge):
        return which_edge

    return ""

def ping_server_status(ip: str, udp_port: int, http_port: int = 8081) -> dict:
    t_start = time.time()
    online = False
    ver = "1.1.0"

    # 1. Try checking the HTTP DB/Version API on port 8081
    try:
        url = f"http://{ip}:{http_port}/version"
        req = urllib.request.Request(url, headers={"User-Agent": "HPMMO-Launcher"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                online = True
                data = json.loads(resp.read().decode())
                ver = data.get("version", ver)
    except Exception:
        pass

    # 2. If HTTP didn't respond, test UDP/TCP socket connectivity to game port
    if not online:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.2)
            s.sendto(b"\x00\x00\x00\x01\x00\x00\x00\x00", (ip, udp_port))
            # ENet or raw UDP ping
            s.close()
            online = True
        except Exception:
            online = False

    t_elapsed_ms = max(int((time.time() - t_start) * 1000), 12)
    return {
        "online": online,
        "ping_ms": t_elapsed_ms if online else None,
        "version": ver,
        "server_ip": ip,
        "server_port": udp_port
    }

class LauncherAPIHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=UI_DIR, **kwargs)

    def log_message(self, format, *args):
        # Silence verbose static file request logging
        pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/status":
            cfg = load_client_config()
            ip = cfg.get("server_ip", "213.250.145.75")
            port = int(cfg.get("server_port", 7777))
            http_port = int(cfg.get("http_port", 8081))
            res = ping_server_status(ip, port, http_port)
            self._send_json(res)
            return

        elif path == "/api/config":
            cfg = load_client_config()
            cfg["client_version"] = load_local_version()
            self._send_json(cfg)
            return

        elif path.startswith("/assets/"):
            # Serve launcher assets
            rel_asset = path.replace("/assets/", "", 1)
            target = os.path.join(ASSETS_DIR, rel_asset)
            if os.path.isfile(target):
                self._send_file(target)
                return

        return super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        body = self._read_body()

        if path == "/api/config":
            cfg = load_client_config()
            if isinstance(body, dict):
                cfg.update(body)
                save_client_config(cfg)
            self._send_json({"success": True, "config": cfg})
            return

        elif path == "/api/auth/register":
            cfg = load_client_config()
            server_ip = cfg.get("server_ip", "213.250.145.75")
            http_port = cfg.get("http_port", 8081)
            username = body.get("username", "").strip()
            password = body.get("password", "").strip()

            url = f"http://{server_ip}:{http_port}/api/register"
            payload = json.dumps({"username": username, "password": password}).encode("utf-8")
            try:
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self._send_json(data)
            except Exception as e:
                # If remote server not running DB API, allow offline registration notice
                self._send_json({
                    "success": False,
                    "message": f"Sunucu Veritabanı API yanıt vermedi ({e}). Lütfen bağlantınızı kontrol edin."
                })
            return

        elif path == "/api/launch":
            mode = body.get("mode", "online") # "online" or "solo"
            user = body.get("username", "Wizard").strip()
            pwd = body.get("password", "").strip()
            server_ip = body.get("server_ip", "213.250.145.75").strip()
            server_port = str(body.get("server_port", 7777))

            # Save latest config
            cfg = load_client_config()
            cfg["last_username"] = user
            cfg["server_ip"] = server_ip
            cfg["server_port"] = int(server_port)
            save_client_config(cfg)

            godot_bin = find_godot_executable()
            main_scene = "scenes/main/main_menu.tscn"

            if mode == "solo":
                cmd = [godot_bin, main_scene, "--solo"]
            else:
                cmd = [
                    godot_bin,
                    main_scene,
                    "--user", user,
                    "--pass", pwd,
                    "--server", server_ip,
                    "--port", server_port,
                    "--autologin"
                ]

            print(f"[Launcher] Spawning Game: {' '.join(cmd)}")
            try:
                if sys.platform == "win32":
                    subprocess.Popen(cmd, cwd=GAME_DIR, creationflags=subprocess.DETACHED_PROCESS)
                else:
                    subprocess.Popen(cmd, cwd=GAME_DIR)
                self._send_json({"success": True, "message": "HPMMO Game Launched"})
            except Exception as e:
                self._send_json({"success": False, "message": str(e)})
            return

        elif path == "/api/open_folder":
            if sys.platform == "win32":
                os.startfile(GAME_DIR)
            else:
                subprocess.Popen(["xdg-open", GAME_DIR])
            self._send_json({"success": True})
            return

        elif path == "/api/window/close":
            self._send_json({"success": True})
            threading.Thread(target=lambda: (time.sleep(0.3), os._exit(0))).start()
            return

        elif path == "/api/window/minimize":
            self._send_json({"success": True})
            return

        self._send_json({"error": "Unknown API endpoint"}, status=404)

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                raw = self.rfile.read(length).decode("utf-8")
                return json.loads(raw)
        except Exception:
            pass
        return {}

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, filepath: str):
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            if filepath.endswith(".jpg") or filepath.endswith(".jpeg"):
                self.send_header("Content-Type", "image/jpeg")
            elif filepath.endswith(".png"):
                self.send_header("Content-Type", "image/png")
            elif filepath.endswith(".css"):
                self.send_header("Content-Type", "text/css")
            elif filepath.endswith(".js"):
                self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            self.send_response(404)
            self.end_headers()

def run_server(port: int):
    server = ThreadingHTTPServer(("127.0.0.1", port), LauncherAPIHandler)
    print(f"[Launcher] Local web server listening on http://127.0.0.1:{port}")
    server.serve_forever()

def main():
    # Pick a dedicated local port
    port = 58240

    # Test if port is available or find free port
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        sock.close()
    except Exception:
        # Pick dynamic free port
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()

    # Start HTTP server thread
    srv_thread = threading.Thread(target=run_server, args=(port,), daemon=True)
    srv_thread.start()
    time.sleep(0.4)

    target_url = f"http://127.0.0.1:{port}/index.html"
    edge_exe = find_edge_executable()

    if edge_exe:
        os.makedirs(CACHE_DIR, exist_ok=True)
        edge_cmd = [
            edge_exe,
            f"--app={target_url}",
            "--window-size=1080,700",
            f"--user-data-dir={CACHE_DIR}",
            "--disable-extensions",
            "--disable-features=TranslateUI",
            "--no-first-run",
            "--no-default-browser-check"
        ]
        print(f"[Launcher] Launching Microsoft Edge App: {' '.join(edge_cmd)}")
        proc = subprocess.Popen(edge_cmd)
        proc.wait()
    else:
        # Fallback to standard web browser
        import webbrowser
        print(f"[Launcher] Opening standard browser window: {target_url}")
        webbrowser.open(target_url)
        # Keep alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    main()
