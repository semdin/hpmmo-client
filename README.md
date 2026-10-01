# PotterMetin MMO (Godot 4.7.2) — Hogwarts Valley Edition

A 3D Wizarding MMO Action RPG inspired by Metin2 mechanics, now rebuilt as a
real explorable world: Hogwarts Castle, Hogsmeade, Forbidden Forest, Black Lake,
Quidditch Pitch, quest NPCs, minimap, boss bars, procedural audio, and true
multiplayer position/spell replication.

> Note: original wizarding setting inspired by folklore + the books' spirit.
> No movie/book ripped assets are used — all models/textures/audio are
> procedural and original (see `assets/textures/`).

## 🎮 How to Play

### Launching
- Double click `play.bat` or run `godot scenes/main/main_menu.tscn`.
- Headless integration test:
  ```powershell
  godot --headless --path . res://scenes/test/test_scenario.tscn
  ```
- Bake real PNG textures (already baked, re-run anytime):
  ```powershell
  godot --headless --path . -s tools/generate_assets.gd
  ```

### Controls (camera-relative — W is always AWAY from camera)
| Key | Action |
| :--- | :--- |
| W A S D | Move (W = forward/away, S = back/toward you) |
| SPACE | Jump (broom glides when mounted) |
| Right Mouse (hold+drag) | Orbit camera / aim |
| Wheel | Zoom |
| Left Click | Cast / talk to NPC / select target |
| Tab | Cycle target |
| 1 Stupefy | Damage + 1.8s stun |
| 2 Incendio | Fire cone, 200% vs Inferi |
| 3 Bombarda | AOE + knockback |
| 4 Expelliarmus | Interrupt + weaken |
| Q Protego | Shield, halves damage, reflects bolts |
| E Ultimate | House burst |
| Shift / Ctrl | Mount Nimbus 2000 |
| Z | Pick up loot |
| F | Talk to nearby NPC |
| I / O | Bag / Ollivander refine |
| Enter | Chat |

### Quest route (6 quests, saved to user://pottermetin_save.json)
1. Talk to Professor Fig at courtyard fountain
2. Kill 4 Acromantulas (west woods)
3. Kill 4 Inferi (use Incendio)
4. Break 1 Dark Monolith (follow purple sky beams)
5. Refine wand to +2 (O)
6. Fly broom to Quidditch Pitch (Shift, then east)

## 🏰 World
- Hogwarts Castle (keep, great hall, 5 towers, glowing windows, gate light)
- Courtyard fountain, stone paths, fences, lamp posts with real lights
- Hogsmeade (7 huts), Black Lake, Quidditch Pitch (6 golden hoops)
- Forbidden Forest (128 trees, spooky light), floating candles, moon, fog
- 4 Dark Monolith world bosses with sky beams + orbiting rune rocks
- 8 leveled mob packs (Lv.5 meadow → Lv.18 deep forest)

## 🧙 Characters (all procedural, no placeholders)
- Wizard: robe + torso + belt + head + hat + swinging arms, walk bob, house scarf
- Acromantula: abdomen + thorax + 8 animated legs + 4 glowing eyes
- Inferi: hunched ghoul with glowing eyes + dangling arms
- Snatcher: cloaked figure with metal mask + hood
- NPCs: Fig, Ollivander, Rosmerta, Hagrid with dialogue + gold ! markers

## 🌐 Real MMORPG networking
- 15 Hz position/rotation/mount/HP broadcast (`rpc_broadcast_state`)
- Spell cast replication (`rpc_broadcast_spell`) — see others' bolts
- Chat, join/leave, remote player interpolation
- Host / Join / Solo via main menu (ENet, default 7777, 32 players)

## 🔊 Audio (100% synthesized, no files)
Procedural `AudioManager`: each spell, hit, loot, level-up, refine win/fail,
quest fanfare — generated as AudioStreamWAV.

## 🛡️ Combat rules: YOU strike first
- Field mobs are **passive (yellow nameplates)** — they wander, warn `!` if you
  touch them, and only retaliate after you hit them (pack defends together).
- **Monolith wave spawns are aggressive (red)** — breaking a monolith is the
  dungeon pull. Training dummies in the courtyard never fight back.

## ✨ MMO skill animations (original art, Metin2-style feel)
`scripts/spells/skill_fx.gd` — procedurally animated, no downloads:
- Wand-arm raise pose on every cast + pulsing bolts with trails
- Stupefy: red ring + orbiting stun stars • Incendio: fire cone + sparks
- Expelliarmus: arc slash • Bombarda/Ultimate: shockwave rings, dust pillar,
  sky beam, camera shake • Protego: bubble + reflect flare
- Practice safely on courtyard dummies, then pull a monolith wave.

## 📦 Assets: own-made + where to get better CC0 ones
- Shipped: procedural models + `assets/textures/*.png` (baked, original).
- I cannot bundle Harry Potter movie assets or Metin2 rips (copyrighted —
  using them risks takedown and won't export legally). Instead:
- Drop CC0 `.glb/.gltf` into `assets/models/` — the game announces them at
  spawn (see `DROP_GLB_HERE.txt`) while procedural rigs keep everything stable.
- Recommended legal sources: **Kenney.nl** (CC0 character/nature packs),
  **Quaternius** (CC0 RPG/nature), **OpenGameArt** (check per-asset license).
- Re-bake textures: `godot --headless --path . -s tools/generate_assets.gd`

## Core systems
- Monolith waves at 75/50/25%, massive loot shower, 30s respawn
- Ollivander +0..+9 (100%→15%, fail can drop tier above +4)
- Nimbus 2000 (+80% speed, mounted casting, wind trail)
- Houses: Gryffindor fire/crit, Slytherin dark, Ravenclaw cooldown/mana, Hufflepuff HP/armor
- Minimap, quest tracker, zone banners, boss bar, dialogue box, low-HP vignette
