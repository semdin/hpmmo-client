# Arcane interface and equipment

Implemented 2026-10-08. The HUD and inventory use a small generated artwork family over Godot controls. Equipment ownership, combat modifiers and refinement are validated by the world authority.

## Playing

- Open the inventory with **I** or **Bag**. Select an item for its details and comparison. Right-click, double-left-click, or drag between the bag and a compatible equipment slot to equip or unequip it.
- Rings use the first empty hand. When both hands are occupied, the replacement menu identifies each worn ring; its tooltip shows that destination's comparison.
- Equipment changes require a living player, no cast or recovery, no transfer, and five seconds without dealing or receiving damage. Changing brooms requires dismounting.
- **Forge / O** refines the equipped wand. The authority supplies its material, price, success chance and resulting tier. Spare wands retain their own tiers.
- **Guide / J** opens the full onboarding checklist and controls. Inventory uses Equipment/Bag tabs on compact canvases; chat expands when typing.

## Ownership and rules

The ten slots are head, chest, hands, feet, main hand, off hand, neck, left ring, right ring and broom. An equipped copy is removed from its bag stack. Stacks merge only when both item ID and tier match. Occupied-slot replacements check the complete resulting bag before applying either side of the swap. Invalid drops do nothing.

`server/world/addons/hpmmo_sim/equipment.gd` and `data/items.json` are canonical. The client receives them through `tools/workspace/sync_sim.py`; edit the server package first. Both gameplay and item comparisons call the same derived-stat calculator. It always starts with explicit base HP/mana, clamps resources after removal, and never heals when a maximum increases. Attack defense is capped at 50%; environmental damage bypasses it. Wand damage is captured when a cast starts. Offensive wand spells and mounting require the corresponding equipped item.

Existing wand, robe and broom values remain in the catalog. Six Apprentice accessories and the Adept Ring supply the requested HP/mana bonuses. Ordinary mobs independently roll a 20% basic-accessory drop, bosses guarantee one, and monoliths additionally roll a 25% Adept Ring drop. Existing loot rolls remain intact.

Reliable equipment intents carry request IDs and an expected inventory revision. Replies include authoritative bag, gear and stats. Replays cannot charge twice; older snapshots cannot restore older ownership. Refinement prices/chances/multipliers/materials live in the shared combat catalog, with only aura colors remaining in client presentation code.

## Persistence and compatibility

Database migration **0005_equipment.sql** creates separate equipped ownership, explicit base maxima, migration version and inventory revision. The migration transfers one owned compatible wand, robe and broom deterministically, applies legacy wand refinement once, and preserves the remaining stacks. Missing gear is never invented. New characters receive their starter gear equipped in the creation transaction. Empty bags are valid saved characters.

The full-state save endpoint requires the service token. Bag, equipment, currency and progression commit together. Equipped copies are unavailable to trades. The world bridge serializes saves per character, retains dirty saves after transient failure, and reloads/reconciles on a revision conflict instead of replaying a stale inventory. Disconnects and maintenance use the same save queue.

Gameplay protocol is **8**. Apply the database migration with the existing service migration command and deploy matching service, world and client builds together. The existing version-mismatch check rejects older gameplay clients. No deployment was performed by this implementation.

## Presentation

`UITheme` installs opt-in `ArcaneCard`, `ArcaneWindow`, `ArcaneButton` and `ArcaneSlot` roles. The four chrome images are in `assets/ui/arcane/`; seven new accessory icons are in `assets/ui/icons/`. Provenance and slicing details are recorded in `assets/ui/arcane/PROVENANCE.md` and file hashes in `assets/manifest.json`.

All button states share the same source geometry. Gold frames, inset surfaces, shadows, rarity marks and cyan selection/focus stay separate from text and dynamic gauges. The minimap retains its circular map mask and clipped markers. The inventory preview uses the existing house-tinted hero and wand prop in its own SubViewport, without a gameplay player; rendering is suspended while closed. Wearable armor meshes and menu redesigns remain outside this release.

## Reproducing checks

From the workspace root, using the installed Python and Godot console executables:

```powershell
client/tools/run_ui_checks.ps1
client/tools/run_game_checks.ps1
python server/tests/integration_api.py
python server/tests/equipment_sim.py
python server/tests/maps_sim.py
python server/tests/maintenance_sim.py
godot --path client res://scenes/test/arcane_showcase.tscn
godot --path client res://scenes/test/arcane_capture.tscn
```

The game-check wrapper now also runs the equipment suite. Use `--fixed-fps 60` for direct headless regression scene runs. Run project imports sequentially. Capture runs require a real renderer.

Verified results:

| Check | Result |
|---|---|
| Existing UI regression | 111 checks, 0 failures |
| Existing gameplay regression | 93 checks, 0 failures |
| Equipment, gestures, ownership and save-queue regression | 257 checks, 0 failures |
| C++ service build | Passed |
| PostgreSQL/service integration, including migration replay and restart | 77 checks, 0 failures |
| Real dedicated world plus two sequential client equipment sessions | Passed equip, refinement, duplicate request, disconnect save and reconnect |
| Existing map transfer, capacity, collision and reconnect suite | 109 checks, 0 failures |
| Existing maintenance drain/save/disconnect suite | 56 checks, 0 failures |
| Shared simulation synchronization | 29 files match |
| Contracts and generated world | 64 contract copies and 356 exported files match their recorded hashes |
| Rendered HUD, combat, inventory and compact bag layouts | 0 geometry failures across the full matrix below |

The generated dedicated world removes UI before child initialization and omits client font/theme startup settings. The network test also rejects any script or resource error in its world-server log.

The two-session network test uses a persistence-service stub; the database transaction, outage, restart and migration tests use PostgreSQL separately. Failure/reconciliation behavior is also exercised through controlled save-bridge responses.

Screenshots are under `tools/downloads/arcane/`: 1280×720, 1920×1080, 2560×1440 and 3440×1440 at UI scales 0.75, 1.0 and 1.75. They include normal HUD, staged combat state, inventory, compact Bag tabs and the component showcase. Layout checks verify equipment access, viewport containment, tooltip containment and separation of combat controls, target/location rows and reward notifications. Representative captures were inspected visually.
