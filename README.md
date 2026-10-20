# HPMMO — Wizarding Realm MMORPG

An online 3D wizarding action RPG: real-time spell combat, monster packs and bosses, dungeons, broom flight, quests and Hogwarts houses.

![HPMMO](assets/branding/hpmmo_banner.jpg)

## Download

Download the launcher for your system. It installs the game, keeps it up to date and starts it.

| System | Download |
|---|---|
| Windows 10/11 (64-bit) | [HPMMO_Launcher.exe](https://github.com/semdin/hpmmo-client/releases/latest/download/HPMMO_Launcher.exe) |
| macOS 11+ (Apple Silicon or Intel) | [HPMMO_Launcher-macos.zip](https://github.com/semdin/hpmmo-client/releases/latest/download/HPMMO_Launcher-macos.zip) |
| Linux (x86_64) | [HPMMO_Launcher-x86_64.AppImage](https://github.com/semdin/hpmmo-client/releases/latest/download/HPMMO_Launcher-x86_64.AppImage) |

**First start:**

- **Windows:** if SmartScreen warns you, click **More info → Run anyway**.
- **macOS:** unzip the file and open **HPMMO Launcher**. If macOS blocks it, go to **System Settings → Privacy & Security** and click **Open Anyway**.
- **Linux:** make the file executable (`chmod +x HPMMO_Launcher-x86_64.AppImage`), then run it.

The game is about 1 GB. Updates download only what changed.

## Join the game

1. Open the launcher and wait until the game is installed and up to date.
2. Click **PLAY**.
3. On the login screen, open **HESAP OLUŞTUR**, pick a username (3–24 characters) and a password (at least 8 characters, letters and numbers), and create your account.
4. Log in with **OYUNA GİR**, create a character, choose your house and enter the world.

The server status ("Sunucu çevrimiçi" = online) is shown on the login screen. During maintenance you can log in again once it finishes.

## Controls

| Key | Action |
|---|---|
| W A S D | Move |
| Right mouse (hold) | Turn camera / aim |
| Mouse wheel | Zoom |
| Left click, 1–4 | Wand attack / spells |
| Q / E | Protego shield / house ultimate |
| Space | Jump, rise on broom |
| Shift / Ctrl | Mount or dismount broom / descend |
| Tab | Next target |
| F | Talk to NPC |
| Z | Pick up loot |
| F1–F4 | Potion quick slots |
| I / C / V | Inventory / character / skills |
| M / B / J | Map / bestiary / guide |
| O | Ollivander (wand upgrade) |
| Enter | Chat (start with `!` to shout to everyone) |
| Esc | Menu: settings, change character, quit |

## Problems?

- **The game won't start or crashes:** update your graphics drivers (Windows and Linux need Vulkan support), then click **Dosyaları onar** (repair files) in the launcher.
- **Bug reports:** send the log file along with what happened:
  - Windows: `%APPDATA%\Godot\app_userdata\HPMMO\logs`
  - macOS: `~/Library/Application Support/Godot/app_userdata/HPMMO/logs`
  - Linux: `~/.local/share/godot/app_userdata/HPMMO/logs`

## For developers

Godot 4.7.2 project. Releases are published automatically on every push to `main`.

- Development cycle: [docs/dev-cycle.md](docs/dev-cycle.md)
- Launcher, releases and maintenance: [docs/launcher-and-releases.md](docs/launcher-and-releases.md)
- Asset credits: [assets/ASSET_CREDITS.md](assets/ASSET_CREDITS.md)
