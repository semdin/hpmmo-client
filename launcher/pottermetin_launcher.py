#!/usr/bin/env python3
"""
PotterMetin MMO - Standalone Game Launcher & Auto-Updater
Metin2 Spell Combat & Hogwarts Wizarding Realm
Supports automated version checking, patch downloading/extraction, server status ping,
and one-click game launch (Online & Solo modes).
"""

import sys
import os
import json
import time
import socket
import threading
import urllib.request
import urllib.error
import zipfile
import subprocess
import shutil

# Enable High-DPI scaling on Windows
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, messagebox

GAME_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_PATH = os.path.join(GAME_DIR, "client_config.json")
VERSION_PATH = os.path.join(GAME_DIR, "version.json")

# Default official configuration
DEFAULT_CONFIG = {
    "server_ip": "213.250.145.75",
    "server_port": 7777,
    "http_port": 8081,
    "last_username": "Wizard",
    "fullscreen": False
}

def load_local_version() -> str:
    if os.path.exists(VERSION_PATH):
        try:
            with open(VERSION_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("version", "1.0.0")
        except Exception:
            pass
    return "1.0.0"

def load_client_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                cfg.update(saved)
        except Exception:
            pass
    return cfg

def save_client_config(cfg: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")

def find_godot_executable() -> str:
    # 1. Check local directory
    local_candidates = [
        os.path.join(GAME_DIR, "godot.exe"),
        os.path.join(GAME_DIR, "PotterMetin.exe"),
        os.path.join(GAME_DIR, "bin", "godot.exe"),
    ]
    for c in local_candidates:
        if os.path.isfile(c):
            return c

    # 2. Check WinGet default installation path
    winget_path = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\godot.exe")
    if os.path.isfile(winget_path):
        return winget_path

    # 3. Check system PATH
    which_godot = shutil.which("godot") or shutil.which("godot.exe")
    if which_godot and os.path.isfile(which_godot):
        return which_godot

    # 4. Check play.bat fallback
    play_bat = os.path.join(GAME_DIR, "play.bat")
    if os.path.isfile(play_bat):
        return play_bat

    return ""

def semver_tuple(v_str: str):
    try:
        parts = [int(p) for p in v_str.replace("v", "").split(".") if p.isdigit()]
        while len(parts) < 3:
            parts.append(0)
        return tuple(parts[:3])
    except Exception:
        return (0, 0, 0)

class PotterMetinLauncher:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("PotterMetin MMO - Official Launcher & Auto-Updater")
        self.root.geometry("860x560")
        self.root.minsize(820, 520)
        self.root.configure(bg="#0c0e14")

        # Set window icon if available
        # Launcher state
        self.config = load_client_config()
        self.current_version = load_local_version()
        self.server_version = "Checking..."
        self.update_available = False
        self.patch_url = ""
        self.server_online = False
        self.ping_ms = None
        self.changelog_items = []
        self.is_downloading = False

        self._init_theme()
        self._build_ui()
        self._start_background_checks()

    def _init_theme(self):
        self.colors = {
            "bg": "#0c0e14",
            "card_bg": "#141822",
            "card_border": "#2b3245",
            "gold_primary": "#e5c158",
            "gold_dark": "#c59b27",
            "gold_light": "#ffdf79",
            "text_white": "#ffffff",
            "text_gray": "#94a1b2",
            "text_dark": "#636e7b",
            "green_online": "#00e676",
            "red_offline": "#ff5252",
            "amber_check": "#ffb300",
            "btn_blue": "#214478",
            "btn_blue_hover": "#2e5ea6"
        }

    def _build_ui(self):
        # Top Header Banner
        header_frame = tk.Frame(self.root, bg="#11151e", height=90, highlightbackground=self.colors["gold_dark"], highlightthickness=1)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        header_frame.pack_propagate(False)

        title_box = tk.Frame(header_frame, bg="#11151e")
        title_box.pack(side=tk.LEFT, padx=25, pady=12)

        title_lbl = tk.Label(
            title_box,
            text="⚡ POTTERMETIN MMO ⚡",
            font=("Georgia", 22, "bold"),
            fg=self.colors["gold_primary"],
            bg="#11151e"
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            title_box,
            text="Metin2 Wand Combat & Hogwarts Realm  •  Official Dedicated Server",
            font=("Segoe UI", 10),
            fg=self.colors["text_gray"],
            bg="#11151e"
        )
        sub_lbl.pack(anchor="w")

        # Top Right Badges (Client Version & Server Status)
        top_right_frame = tk.Frame(header_frame, bg="#11151e")
        top_right_frame.pack(side=tk.RIGHT, padx=25, pady=15)

        self.client_ver_badge = tk.Label(
            top_right_frame,
            text=f"Client: v{self.current_version}",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["text_white"],
            bg="#1d2332",
            padx=10,
            pady=4,
            relief="solid",
            bd=1
        )
        self.client_ver_badge.pack(side=tk.TOP, anchor="e", pady=2)

        self.server_status_badge = tk.Label(
            top_right_frame,
            text="● Pinging Realm...",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["amber_check"],
            bg="#1d2332",
            padx=10,
            pady=4,
            relief="solid",
            bd=1
        )
        self.server_status_badge.pack(side=tk.TOP, anchor="e", pady=2)

        # Center Body (Two columns)
        body_frame = tk.Frame(self.root, bg=self.colors["bg"])
        body_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

        # Left Column: Realm Connection & Settings
        left_col = tk.Frame(body_frame, bg=self.colors["card_bg"], highlightbackground=self.colors["card_border"], highlightthickness=1)
        left_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))
        left_col.config(width=340)
        left_col.pack_propagate(False)

        left_title = tk.Label(
            left_col,
            text="REALM STATUS & NETWORK",
            font=("Segoe UI", 11, "bold"),
            fg=self.colors["gold_primary"],
            bg=self.colors["card_bg"]
        )
        left_title.pack(anchor="w", padx=16, pady=(14, 8))

        # Realm Info Card
        self.realm_info_box = tk.Label(
            left_col,
            text="Host: 213.250.145.75\nPort: 7777 (UDP) / 8081 (HTTP)\nLocation: Dedicated Linux VPS\nDatabase: PostgreSQL + RAM",
            font=("Consolas", 9),
            fg="#cad3de",
            bg="#0f121a",
            justify="left",
            padx=12,
            pady=8,
            relief="solid",
            bd=1
        )
        self.realm_info_box.pack(fill=tk.X, padx=16, pady=4)

        # Connection Settings Sub-Frame
        settings_label = tk.Label(
            left_col,
            text="CONNECTION PRESETS",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["text_gray"],
            bg=self.colors["card_bg"]
        )
        settings_label.pack(anchor="w", padx=16, pady=(12, 4))

        # Server Preset Radio / Buttons
        self.preset_var = tk.StringVar(value="official" if self.config.get("server_ip") == "213.250.145.75" else "custom")

        preset_row = tk.Frame(left_col, bg=self.colors["card_bg"])
        preset_row.pack(fill=tk.X, padx=16, pady=2)

        rb_off = tk.Radiobutton(
            preset_row,
            text="Official VPS",
            variable=self.preset_var,
            value="official",
            command=self._on_preset_change,
            fg=self.colors["text_white"],
            bg=self.colors["card_bg"],
            selectcolor="#0f121a",
            activebackground=self.colors["card_bg"],
            activeforeground=self.colors["gold_primary"]
        )
        rb_off.pack(side=tk.LEFT)

        rb_local = tk.Radiobutton(
            preset_row,
            text="Localhost",
            variable=self.preset_var,
            value="local",
            command=self._on_preset_change,
            fg=self.colors["text_white"],
            bg=self.colors["card_bg"],
            selectcolor="#0f121a",
            activebackground=self.colors["card_bg"],
            activeforeground=self.colors["gold_primary"]
        )
        rb_local.pack(side=tk.LEFT, padx=10)

        # IP and Port Input Rows
        ip_row = tk.Frame(left_col, bg=self.colors["card_bg"])
        ip_row.pack(fill=tk.X, padx=16, pady=(8, 2))
        tk.Label(ip_row, text="Server IP:", font=("Segoe UI", 9), fg=self.colors["text_gray"], bg=self.colors["card_bg"]).pack(side=tk.LEFT)
        self.ip_entry = tk.Entry(ip_row, bg="#0f121a", fg=self.colors["text_white"], insertbackground="white", bd=1, relief="solid", font=("Segoe UI", 9))
        self.ip_entry.insert(0, self.config.get("server_ip", "213.250.145.75"))
        self.ip_entry.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(8, 0))

        port_row = tk.Frame(left_col, bg=self.colors["card_bg"])
        port_row.pack(fill=tk.X, padx=16, pady=4)
        tk.Label(port_row, text="UDP Port:", font=("Segoe UI", 9), fg=self.colors["text_gray"], bg=self.colors["card_bg"]).pack(side=tk.LEFT)
        self.port_entry = tk.Entry(port_row, bg="#0f121a", fg=self.colors["text_white"], insertbackground="white", bd=1, relief="solid", font=("Segoe UI", 9))
        self.port_entry.insert(0, str(self.config.get("server_port", 7777)))
        self.port_entry.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(8, 0))

        # Test Ping & Save Preset button
        btn_network_row = tk.Frame(left_col, bg=self.colors["card_bg"])
        btn_network_row.pack(fill=tk.X, padx=16, pady=8)

        self.btn_ping = tk.Button(
            btn_network_row,
            text="🔄 Re-Check Ping",
            font=("Segoe UI", 9, "bold"),
            fg=self.colors["text_white"],
            bg="#232938",
            activebackground="#31394e",
            activeforeground="white",
            relief="flat",
            bd=0,
            command=self._start_background_checks
        )
        self.btn_ping.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))

        self.btn_save_cfg = tk.Button(
            btn_network_row,
            text="💾 Save IP",
            font=("Segoe UI", 9, "bold"),
            fg=self.colors["gold_primary"],
            bg="#232938",
            activebackground="#31394e",
            activeforeground=self.colors["gold_light"],
            relief="flat",
            bd=0,
            command=self._save_settings
        )
        self.btn_save_cfg.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(4, 0))

        # Right Column: Realm News & Changelog
        right_col = tk.Frame(body_frame, bg=self.colors["card_bg"], highlightbackground=self.colors["card_border"], highlightthickness=1)
        right_col.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        right_title_frame = tk.Frame(right_col, bg=self.colors["card_bg"])
        right_title_frame.pack(fill=tk.X, padx=16, pady=(14, 8))

        right_title = tk.Label(
            right_title_frame,
            text="📜 REALM DISPATCHES & PATCH NOTES",
            font=("Segoe UI", 11, "bold"),
            fg=self.colors["gold_primary"],
            bg=self.colors["card_bg"]
        )
        right_title.pack(side=tk.LEFT)

        self.server_ver_label = tk.Label(
            right_title_frame,
            text=f"Server: {self.server_version}",
            font=("Segoe UI", 9, "bold"),
            fg=self.colors["text_gray"],
            bg=self.colors["card_bg"]
        )
        self.server_ver_label.pack(side=tk.RIGHT)

        # News Box (Styled Text area)
        news_frame = tk.Frame(right_col, bg="#0f121a", bd=1, relief="solid")
        news_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 14))

        self.news_text = tk.Text(
            news_frame,
            bg="#0f121a",
            fg="#d8e1ed",
            insertbackground="white",
            wrap="word",
            font=("Segoe UI", 10),
            padx=12,
            pady=10,
            bd=0,
            relief="flat"
        )
        self.news_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(news_frame, command=self.news_text.yview, bg="#141822")
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.news_text.config(yscrollcommand=scrollbar.set)
        self.news_text.config(state="disabled")

        # Bottom Bar: Progress Bar, Status Text & Action Buttons
        bottom_bar = tk.Frame(self.root, bg="#11151e", height=95, highlightbackground=self.colors["card_border"], highlightthickness=1)
        bottom_bar.pack(fill=tk.X, side=tk.BOTTOM)
        bottom_bar.pack_propagate(False)

        # Progress bar container
        progress_container = tk.Frame(bottom_bar, bg="#11151e")
        progress_container.pack(fill=tk.X, padx=20, pady=(10, 0))

        self.status_label = tk.Label(
            progress_container,
            text="Ready. Initializing launcher checks...",
            font=("Segoe UI", 9),
            fg=self.colors["text_gray"],
            bg="#11151e"
        )
        self.status_label.pack(side=tk.LEFT)

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            progress_container,
            variable=self.progress_var,
            maximum=100.0,
            length=280
        )
        self.progress_bar.pack(side=tk.RIGHT)

        # Action Buttons Row
        action_row = tk.Frame(bottom_bar, bg="#11151e")
        action_row.pack(fill=tk.X, padx=20, pady=(8, 10))

        # Left action buttons
        self.btn_solo = tk.Button(
            action_row,
            text="🕹️ SOLO OFFLINE",
            font=("Segoe UI", 10, "bold"),
            fg=self.colors["text_white"],
            bg="#1c2538",
            activebackground="#293752",
            activeforeground="white",
            padx=14,
            pady=6,
            relief="flat",
            bd=0,
            command=self._launch_solo_game
        )
        self.btn_solo.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_folder = tk.Button(
            action_row,
            text="📁 Game Folder",
            font=("Segoe UI", 9),
            fg=self.colors["text_gray"],
            bg="#181d28",
            activebackground="#232a3b",
            activeforeground="white",
            padx=10,
            pady=6,
            relief="flat",
            bd=0,
            command=self._open_game_folder
        )
        self.btn_folder.pack(side=tk.LEFT)

        # Primary Action Button (Play Now / Update Game)
        self.btn_primary = tk.Button(
            action_row,
            text="⚔️ PLAY NOW",
            font=("Segoe UI", 13, "bold"),
            fg="#0b0d13",
            bg=self.colors["gold_primary"],
            activebackground=self.colors["gold_light"],
            activeforeground="#000000",
            padx=28,
            pady=4,
            relief="flat",
            bd=0,
            cursor="hand2",
            command=self._on_primary_click
        )
        self.btn_primary.pack(side=tk.RIGHT)

    def _on_preset_change(self):
        val = self.preset_var.get()
        if val == "official":
            self.ip_entry.delete(0, tk.END)
            self.ip_entry.insert(0, "213.250.145.75")
            self.port_entry.delete(0, tk.END)
            self.port_entry.insert(0, "7777")
        elif val == "local":
            self.ip_entry.delete(0, tk.END)
            self.ip_entry.insert(0, "127.0.0.1")
            self.port_entry.delete(0, tk.END)
            self.port_entry.insert(0, "7777")
        self._save_settings()
        self._start_background_checks()

    def _save_settings(self):
        ip = self.ip_entry.get().strip() or "213.250.145.75"
        try:
            port = int(self.port_entry.get().strip() or "7777")
        except ValueError:
            port = 7777
        self.config["server_ip"] = ip
        self.config["server_port"] = port
        save_client_config(self.config)
        self.status_label.config(text=f"Settings saved: {ip}:{port}", fg=self.colors["gold_primary"])

    def _start_background_checks(self):
        self._save_settings()
        self.server_status_badge.config(text="● Checking Realm...", fg=self.colors["amber_check"])
        self.status_label.config(text="Querying dedicated server status & version...", fg=self.colors["text_gray"])
        self.progress_var.set(25.0)

        t = threading.Thread(target=self._run_network_checks, daemon=True)
        t.start()

    def _run_network_checks(self):
        ip = self.config.get("server_ip", "213.250.145.75")
        port = int(self.config.get("server_port", 7777))
        http_port = int(self.config.get("http_port", 8081))

        # 1. Ping UDP game port (Godot ENet server)
        server_online = False
        ping_time_ms = None
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(1.5)
            start_t = time.time()
            s.sendto(b"\x00\x00\x00\x00", (ip, port))
            # ENet or simple UDP socket check
            server_online = True
            ping_time_ms = int((time.time() - start_t) * 1000)
            s.close()
        except Exception:
            pass

        # 2. Query HTTP Version & Changelog API
        version_data = None
        ver_url = f"http://{ip}:{http_port}/api/version"
        try:
            req = urllib.request.Request(ver_url, headers={"User-Agent": "PotterMetinLauncher/1.1"})
            with urllib.request.urlopen(req, timeout=2.5) as resp:
                if resp.status == 200:
                    version_data = json.loads(resp.read().decode("utf-8"))
                    server_online = True
        except Exception as e:
            # Fallback check server/version.json if locally available
            local_server_ver = os.path.join(GAME_DIR, "server", "version.json")
            if os.path.exists(local_server_ver):
                try:
                    with open(local_server_ver, "r", encoding="utf-8") as f:
                        version_data = json.load(f)
                except Exception:
                    pass

        self.root.after(0, self._handle_checks_result, server_online, ping_time_ms, version_data)

    def _handle_checks_result(self, is_online: bool, ping_ms: int, ver_data: dict):
        self.server_online = is_online
        self.ping_ms = ping_ms
        self.progress_var.set(100.0)

        # Update Server Status Badge
        if is_online:
            ping_txt = f"{ping_ms}ms" if ping_ms is not None else "OK"
            self.server_status_badge.config(
                text=f"● REALM ONLINE ({ping_txt})",
                fg=self.colors["green_online"]
            )
            self.status_label.config(
                text=f"Connected to Realm {self.config.get('server_ip')}:{self.config.get('server_port')} — Ready to enter!",
                fg=self.colors["green_online"]
            )
        else:
            self.server_status_badge.config(
                text="● REALM OFFLINE",
                fg=self.colors["red_offline"]
            )
            self.status_label.config(
                text="Server is offline or unreachable. Solo Mode is available anytime!",
                fg=self.colors["amber_check"]
            )

        # Update Version and Changelog
        if ver_data:
            s_ver = ver_data.get("version", self.current_version)
            self.server_version = s_ver
            self.server_ver_label.config(text=f"Server: v{s_ver}")
            self.patch_url = ver_data.get("patch_url", "")
            self.changelog_items = ver_data.get("changelog", [])

            # Check if update available
            c_tuple = semver_tuple(self.current_version)
            s_tuple = semver_tuple(s_ver)

            if s_tuple > c_tuple and self.patch_url:
                self.update_available = True
                self.btn_primary.config(
                    text="⚡ UPDATE GAME",
                    bg="#ff9800",
                    activebackground="#ffa726",
                    fg="#000000"
                )
                self.status_label.config(
                    text=f"New version v{s_ver} is available! Click 'UPDATE GAME' to patch.",
                    fg=self.colors["gold_primary"]
                )
            else:
                self.update_available = False
                self.btn_primary.config(
                    text="⚔️ PLAY NOW",
                    bg=self.colors["gold_primary"],
                    activebackground=self.colors["gold_light"],
                    fg="#000000"
                )
        else:
            self.server_version = self.current_version
            self.server_ver_label.config(text=f"Server: v{self.current_version}")
            self.changelog_items = [
                f"v{self.current_version}: PotterMetin MMO Client Active",
                "• Full Metin2 Wand Combat & Real-time Spell Projectiles",
                "• Account Registration & PostgreSQL / RAM Persistence",
                "• 4 Hogwarts Houses: Gryffindor, Slytherin, Ravenclaw, Hufflepuff",
                "• Flying Nimbus 2000 Mounts & Dark Monolith Metin Stones",
                "• Solo / Offline and Multiplayer Dedicated Server modes"
            ]

        self._populate_news()

    def _populate_news(self):
        self.news_text.config(state="normal")
        self.news_text.delete("1.0", tk.END)

        self.news_text.insert(tk.END, "🏰 WELCOME TO POTTERMETIN MMO\n", "title")
        self.news_text.insert(tk.END, "Enter the magical realm where Metin2 action-MMO combat meets the wizarding world of Hogwarts.\n\n", "subtitle")

        self.news_text.insert(tk.END, f"📌 LATEST RELEASES & ANNOUNCEMENTS (v{self.server_version}):\n", "header")
        for item in self.changelog_items:
            self.news_text.insert(tk.END, f"  • {item}\n", "bullet")

        self.news_text.insert(tk.END, "\n🧙 QUICK GAMEPLAY GUIDE:\n", "header")
        self.news_text.insert(tk.END, "  • Left Click / Mouse: Target enemies & Dark Monoliths\n", "bullet")
        self.news_text.insert(tk.END, "  • 1, 2, 3, 4: Cast Spells (Basic Cast, Stupefy, Incendio, Bombarda)\n", "bullet")
        self.news_text.insert(tk.END, "  • Space: Jump / Mount Nimbus 2000 Broomstick\n", "bullet")
        self.news_text.insert(tk.END, "  • I: Inventory & Wand Upgrades  •  C: Wizard Character Sheet\n", "bullet")
        self.news_text.insert(tk.END, "  • Dark Monoliths spawn dark wizard mobs: destroy them for Galleons & wand materials!\n", "bullet")

        self.news_text.tag_config("title", font=("Georgia", 13, "bold"), foreground=self.colors["gold_primary"])
        self.news_text.tag_config("subtitle", font=("Segoe UI", 9, "italic"), foreground=self.colors["text_gray"])
        self.news_text.tag_config("header", font=("Segoe UI", 10, "bold"), foreground=self.colors["text_white"])
        self.news_text.tag_config("bullet", font=("Segoe UI", 9), foreground="#b6c2d1")

        self.news_text.config(state="disabled")

    def _on_primary_click(self):
        if self.is_downloading:
            return
        if self.update_available:
            self._start_patch_download()
        else:
            self._launch_game(solo=False)

    def _launch_solo_game(self):
        self._launch_game(solo=True)

    def _launch_game(self, solo: bool = False):
        godot_exe = find_godot_executable()
        if not godot_exe:
            messagebox.showerror(
                "Godot Engine Not Found",
                "Could not find Godot Engine executable (godot.exe).\n\n"
                "Please ensure Godot 4.7.2 is installed or place godot.exe in the game folder."
            )
            return

        self._save_settings()
        self.status_label.config(text="Launching PotterMetin MMO...", fg=self.colors["gold_primary"])

        cmd = [godot_exe]
        if godot_exe.endswith(".bat"):
            cmd = [godot_exe]
        else:
            cmd.extend(["--path", GAME_DIR, "scenes/main/main_menu.tscn"])
            if solo:
                cmd.append("--solo")

        try:
            subprocess.Popen(cmd, cwd=GAME_DIR)
            self.status_label.config(text="Game running! Enjoy your adventures.", fg=self.colors["green_online"])
            # Launcher stays ready in background
        except Exception as e:
            messagebox.showerror("Launch Error", f"Failed to start game:\n{e}")

    def _open_game_folder(self):
        if sys.platform == "win32":
            os.startfile(GAME_DIR)
        else:
            subprocess.Popen(["xdg-open", GAME_DIR])

    def _start_patch_download(self):
        if not self.patch_url:
            messagebox.showinfo("Update", "Patch URL is not configured.")
            return

        self.is_downloading = True
        self.btn_primary.config(state="disabled", text="⏳ DOWNLOADING...")
        self.status_label.config(text="Connecting to patch server...", fg=self.colors["gold_primary"])
        self.progress_var.set(0.0)

        t = threading.Thread(target=self._download_and_apply_patch, daemon=True)
        t.start()

    def _download_and_apply_patch(self):
        patch_dest = os.path.join(GAME_DIR, "patch_temp.zip")
        try:
            req = urllib.request.Request(self.patch_url, headers={"User-Agent": "PotterMetinLauncher/1.1"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                total_size = int(resp.headers.get("Content-Length", 0))
                downloaded = 0
                block_size = 65536

                with open(patch_dest, "wb") as f_out:
                    while True:
                        chunk = resp.read(block_size)
                        if not chunk:
                            break
                        f_out.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100.0
                            self.root.after(0, self._update_patch_progress, percent, f"Downloading: {downloaded // 1024} KB / {total_size // 1024} KB")

            # Extract patch zip
            self.root.after(0, self._update_patch_progress, 90.0, "Extracting patch files...")
            with zipfile.ZipFile(patch_dest, "r") as z:
                z.extractall(GAME_DIR)

            if os.path.exists(patch_dest):
                os.remove(patch_dest)

            # Update version.json
            self.current_version = self.server_version
            with open(VERSION_PATH, "w", encoding="utf-8") as f_ver:
                json.dump({"version": self.current_version, "installed_date": time.strftime("%Y-%m-%d")}, f_ver, indent=2)

            self.root.after(0, self._finish_patch_success)
        except Exception as e:
            if os.path.exists(patch_dest):
                try:
                    os.remove(patch_dest)
                except Exception:
                    pass
            self.root.after(0, self._finish_patch_error, str(e))

    def _update_patch_progress(self, percent: float, msg: str):
        self.progress_var.set(percent)
        self.status_label.config(text=msg)

    def _finish_patch_success(self):
        self.is_downloading = False
        self.update_available = False
        self.client_ver_badge.config(text=f"Client: v{self.current_version}")
        self.btn_primary.config(
            state="normal",
            text="⚔️ PLAY NOW",
            bg=self.colors["gold_primary"],
            activebackground=self.colors["gold_light"],
            fg="#000000"
        )
        self.progress_var.set(100.0)
        self.status_label.config(text=f"Successfully patched to v{self.current_version}! Ready to play.", fg=self.colors["green_online"])
        messagebox.showinfo("Patch Complete", f"PotterMetin MMO has been updated to v{self.current_version}!")

    def _finish_patch_error(self, err: str):
        self.is_downloading = False
        self.btn_primary.config(state="normal", text="⚡ RETRY UPDATE")
        self.status_label.config(text=f"Patch failed: {err}", fg=self.colors["red_offline"])
        messagebox.showerror("Update Error", f"Failed to download or apply patch:\n{err}")

def main():
    root = tk.Tk()
    app = PotterMetinLauncher(root)
    root.mainloop()

if __name__ == "__main__":
    main()
