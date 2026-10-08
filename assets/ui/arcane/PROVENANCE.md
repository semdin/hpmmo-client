# Arcane chrome and equipment icons

Generated for this project with OpenAI Imagegen on 2026-10-08. The supplied
Arcane UI Components pack informed the midnight-blue and aged-gold direction.
The new chrome was generated as separate, simpler components with no baked text.

Chrome: `window.png`, `button.png`, `slot.png`, `minimap.png`.
Equipment icons: `icon_hat_apprentice.png`, `icon_gloves_apprentice.png`,
`icon_boots_apprentice.png`, `icon_focus_apprentice.png`,
`icon_pendant_apprentice.png`, `icon_ring_apprentice.png`, `icon_ring_adept.png`
in the adjacent `icons` directory. File hashes are recorded in `assets/manifest.json`.

ArcaneSkin measures visible alpha at 0.25 to exclude faint transparent padding,
then normalizes the artwork once at logical UI resolution. Window/slot corners
use ten-pixel slices. Button corners use twelve pixels horizontally and five
vertically. The minimap bezel keeps its aspect ratio and is never nine-sliced.
All button states share one source geometry with code-driven tint and focus.

This records provenance; it does not assign a third-party asset-pack license.
