# 🏰 HPMMO (Godot 4.7.2) — Wizarding Realm MMORPG

A 3D Wizarding MMO Action RPG inspired by Metin2 mechanics, built with real-time spell combat, Dark Monolith (Metin Stone) wave battles, wand upgrading via Ollivander, broom mounts, and persistent PostgreSQL character progression.

![HPMMO Key Art Banner](assets/branding/hpmmo_banner.jpg)

**2 October 2026 gameplay update:** walkable castle interiors, new animated enemies, coordinated random encounter respawns, smoother combat and flight, live HUD fixes, and resolved startup/shutdown errors. See [new asset credits](assets/ASSET_CREDITS.md). The local update has not been deployed to the VPS; shared server-authoritative encounters remain separate networking work.

---

## ⚡ Key Features

- **Metin2-Style Real-Time Spell Combat & Ballistic Skillshots**: True mouse-aim ground raycast targeting (League of Legends style skillshots) with 3-hit basic wand combo chain (*flick -> swish -> overhead whip*). Cast *Stupefy* (stun shockwave), *Incendio* (flame plume), *Bombarda* (crater explosion AOE), *Expelliarmus* (spell break), *Protego* (reflective shield), and house-specific Ultimates.
- **Mob Packs, Pack Aggro & World Bosses**: Pack coordination (2/3/5 pack formations) with linked aggro pull, 4.0s corpse decay lifecycle with ground sinking before zone respawn, plus dedicated World Bosses (*Corrupted Acromantula Matriarch* with telegraphed AOE ground slam and *Dark Snatcher Commander* with bodyguard enrage).
- **World Boundaries & Broom Flight Safeguards**: 60m tall invisible perimeter collision barriers with magical ward visuals, broom dismount safety ground raycasting (`can_dismount_safely()`), and infinite fall kill-plane teleportation.
- **Walkable Castle & Clear Lighting**: Enter the Great Hall, library and Charms classroom through connected passages. Textured masonry, arches, furnishings, floating candles and batched geometry; fog disabled, restrained bloom and clear daylight.
- **3D Character Selection Podium**: Cinematic stone podium with glowing house runes, directional rim lighting, 2 characters maximum per account, and smooth arrow-key switching.
- **4 Hogwarts Houses & Passives**:
  - **Gryffindor**: +15% Critical Spell Damage.
  - **Slytherin**: +25% Mana Regeneration Rate.
  - **Ravenclaw**: +20% Spell Cast Range.
  - **Hufflepuff**: +20% Maximum HP & Potion Effectiveness.
- **Hybrid Persistence (PostgreSQL + RAM + JSON)**:
  - High-frequency 15 Hz combat and movement calculated in Dedicated Server RAM (no DB I/O lag).
  - ACID persistent accounts and characters stored in PostgreSQL (with SQLite backup) bound to `0.0.0.0:8081`.
  - Solo Offline Mode saves progress locally to `user://hpmmo_character_save.json`.
- **Native C++ Standalone Launcher (`HPMMO_Launcher.exe`)**:
  - Standalone compiled binary (< 1.5 MB) using WinHTTP, WinSock, and GDI+.
  - In-launcher Account Registration & Login with single sign-on credential pass-through.
  - Live VPS Realm Ping monitor (`213.250.145.75:7777` UDP / `8081` HTTP).
  - One-click **⚔️ OYUNA BAŞLA (PLAY NOW)** and **🕹️ ÇEVRİMDIŞI OYNA (SOLO OFFLINE)** modes.

---

## 🎮 How to Play

### 1. Launching
- **Native C++ Launcher**: Launch `HPMMO_Launcher.exe` directly or run `Launcher.bat`.
- **Direct Client Launch**: Double-click `play.bat` or run `godot scenes/main/main_menu.tscn`.
- **Dedicated Server Start**:
  ```powershell
  godot --headless scenes/server/dedicated_server.tscn
  ```
- **In-Engine Automated Test Suite**:
  ```powershell
  godot --headless --path . res://scenes/test/test_scenario.tscn
  ```
- **Spell Animation Viewer** (live preview for tuning spell VFX — caster, effect
  and a human-sized scale reference in one shot):
  ```powershell
  godot --path . res://scenes/test/vfx_viewer.tscn
  # batch evidence: one PNG per stage into tools/downloads, then exit
  godot --path . res://scenes/test/vfx_viewer.tscn -- --quality=high --spell=bombarda --shot
  ```
  `Space` pause · `←/→` spell · `R` replay · `-`/`=` speed · `1/2/3` quality ·
  `O` orbit · `T` reference · `C` PNG · `Esc` quit · drag/wheel orbit and zoom.

### 2. Controls
| Key | Action |
| :--- | :--- |
| **W A S D** | Move (camera-relative) |
| **SPACE** | Jump / Rise on broom |
| **Right Mouse (Hold & Drag)** | Orbit Camera / Free Aim |
| **Wheel** | Camera Zoom |
| **Left Click / 1-4** | Aimed Skillshot Spell / 3-Hit Wand Combo |
| **Left / Right Arrow (Select Screen)** | Rotate Character Podium (Slot 1 / Slot 2) |
| **Tab** | Cycle Target |
| **1 (Stupefy)** | Red energy bolt + 1.8s Stun Shockwave |
| **2 (Incendio)** | Flame cone plume (200% damage vs Inferi) |
| **3 (Bombarda)** | Explosive crater AOE + knockback |
| **4 (Expelliarmus)** | Disarm, interrupt & weaken |
| **Q (Protego)** | Arcane shield, halves incoming damage, reflects bolts |
| **E (Ultimate)** | House-specific celestial aura & burst |
| **Shift** | Mount / Dismount Nimbus 2000 Broom (near ground) |
| **Ctrl** | Descend on broom |
| **Z** | Pick up ground loot |
| **F** | Interact with nearby NPC |
| **I / O** | Bag Inventory / Ollivander Wand Refine (+0 to +9) |
| **Enter** | World / System Chat |

---

## 🚀 Dedicated Server Deployment (Linux VPS: `213.250.145.75`)

1. **Package on Windows**:
   Double click `package_server.bat` (creates `hpmmo_server.tar.gz`).
2. **Send to VPS**:
   ```bash
   scp hpmmo_server.tar.gz root@213.250.145.75:~/
   ```
3. **First-Time Install**:
   ```bash
   bash ~/hpmmo/game/setup_server.sh
   ```
4. **Update Server**:
   ```bash
   bash ~/hpmmo/game/update_server.sh
   ```
5. **Monitor Live Logs**:
   ```bash
   # Dedicated Game Server
   journalctl -u hpmmo -f

   # PostgreSQL & Account API
   journalctl -u hpmmo-db -f
   ```
