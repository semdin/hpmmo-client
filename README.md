# PotterMetin MMO (Godot 4.7.2)

A 3D Wizarding MMO Action RPG inspired by the gameplay mechanics of **Metin2**, translated into the **Harry Potter** universe.

Built on **Godot 4.7.2** with dedicated networking, real-time wand combat, Metin-style Dark Monoliths, Ollivander's +1 to +9 wand refinement system, and broomstick mounts.

---

## 🎮 How to Play

### Launching the Game
- **Quick Launch**: Double click `play.bat` or run `godot scenes/main/main_menu.tscn`.
- **In Godot Editor**: Open Godot 4.7.2 and select this project folder.
- **Run Headless Integration Test**:
  ```powershell
  godot_console --headless scenes/test/test_scenario.tscn
  ```

### Controls
| Key / Input | Action |
| :--- | :--- |
| **W, A, S, D** | Move Character |
| **Right Mouse Button (Hold & Drag)** | 3rd Person Orbit Camera / Aim |
| **Mouse Wheel** | Zoom Camera In / Out |
| **Left Mouse Button** | Basic Wand Cast / Target Click |
| **Tab** | Cycle Nearest Target (Enemy / Dark Monolith) |
| **1** | Cast **Stupefy** (Stuns target for 1.8s) |
| **2** | Cast **Incendio** (Flame cone AOE, 200% damage to Inferi) |
| **3** | Cast **Bombarda** (Explosive shockwave AOE with knockback) |
| **4** | Cast **Expelliarmus** (Disarming charm + knockback) |
| **Q** | Cast **Protego** (Dome shield, reflects enemy projectiles & halves damage) |
| **E** | Cast **House Ultimate** (High burst damage) |
| **Shift / Ctrl** | **Mount / Dismount Nimbus 2000** (+80% movement speed & mounted spellcasting) |
| **Z / `** | **Pick Up Nearby Loot** (Metin2 pickup key: Galleons, materials, potions) |
| **I** | Toggle **Inventory** (Equip gear, drink Wiggenweld/Pepperup potions) |
| **O** | Toggle **Ollivander's Wand Crafting** (+0 to +9 wand refinement) |
| **Enter** | Open **MMO Chat** |

---

## 🧙‍♂️ Core Gameplay Systems

### 1. Metin Stones $\to$ Dark Monoliths
Corrupted spires manifested in the open world. As wizards attack and chip away at the Monolith:
- **75% HP**: Triggers **Wave 1** (Swarm of Acromantulas + Inferi Ghouls).
- **50% HP**: Triggers **Wave 2** (Pack of Inferi + Ranged Dark Snatchers).
- **25% HP**: Triggers **Wave 3** (Elite Dark Swarm).
- **Destruction**: Monolith shatters in a dark explosion, showering the ground with Galleons, Phoenix Ash, Dragon Heartstrings, Thestral Hair, and rare catalyst cores!

### 2. Ollivander's Wand Refinement (+0 to +9)
Just like the legendary Metin2 Blacksmith:
- Wands can be refined from **+0 to +9** using Galleons and magical crafting components.
- **+0 to +3**: 100% Success.
- **+4 to +6**: Shimmering arcane blue mist aura, moderate success chance.
- **+7 to +8**: Crackling golden lightning & ember trails, high risk.
- **+9 (MAX)**: Brilliant radiant Phoenix fire aura radiating from the wand and wizard!
- *Risk*: Higher tier failures can degrade the wand tier, preserving the classic Metin2 refinement thrill.

### 3. Mount System (Nimbus 2000)
Pressing `Shift` or `Ctrl` summons your racing broom:
- +80% movement speed.
- Golden wind trail VFX.
- Full mounted spellcasting capability (just like Metin2 horseback combat).

### 4. Hogwarts House Factions & Traits
- **Gryffindor**: Bravery (+15% Fire Spell damage & +10% Critical strike chance).
- **Slytherin**: Ambition (+20% Dark Magic damage & Life Leech).
- **Ravenclaw**: Wisdom (-20% Spell cooldowns & +25% Max Mana).
- **Hufflepuff**: Loyalty (+25% Max Health & +15% Armor).

### 5. Multiplayer ENet Architecture
- **Host Realm**: Start your own world server and invite peers over LAN or IP.
- **Join Realm**: Connect to a remote server IP and port (default 7777).
- Synchronized positions, spell projectiles, chat channel, mob aggro, and monolith states.
