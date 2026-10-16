# AI-generated icon provenance

Created: 2026-10-08. Tool: OpenAI Imagegen. Scope: the 64 `icon_<id>.png` files and
`icons_preview.jpg` under `assets/ui/icons/`, listed with their SHA-256 hashes in
`assets/manifest.json` (`family-icon-set`) and in the pack's own `icon_manifest.json`.

This is a provenance note, not a CC0 dedication and not a replacement for the
project's licence. No third-party icon set was used as an image input in generating
this pack: the images were produced from text prompts describing project ids and
visual directions, then scaled to a common delivery size with the alpha channel
preserved. User-supplied fictional names and visual descriptions guided generation;
this note does not grant rights in third-party names, characters or trademarks.

Retain existing third-party licence notices for assets that remain in use. The
gnola14 CC0 pack this set replaced is no longer distributed: its licence text stays
at `assets/ui/LICENSES/oga-rpg-icons-496.txt` and `assets/manifest.json` records the
pack as superseded. Do not delete those records automatically.

## 2026-10-13 additions (fal.ai)

Tool: fal.ai `fal-ai/nano-banana-2.1` (1K, 1:1), same text-prompt template as the
spell and potion icons. No third-party image was used as an input.

* `icon_menu_{inventory,ollivander,mount,journal,map,settings}.png` - full-bleed
  square paintings for the bottom-right menu cells, resized to 256 px.
* `icon_minimap_{player,mob,boss,npc,monolith,zoom_in,zoom_out}.png` - single
  objects generated on flat white, cut out by `tools/ui/cutout_icons.py`
  (border-connected white removed, soft edge alpha with the white un-mixed),
  trimmed square and resized to 128 px. They replace the previous minimap set.

## 2026-10-16 additions (fal.ai) - broom tiers

Tool: fal.ai `google/nano-banana-2.1/edit` (1K, 1:1). Input image: the project's
own broom concept painting for that tier (generated the same day with
`openai/gpt-image-2.5/sunburst`, kept in `art/brooms/<tier>/views/main.png`);
no third-party image was used.

* `icon_broom_{ashwood,runebound,silverthorn,emberwing,moonveil}.png` - the
  tier's broom shown diagonally on flat white with its aura colour, cut out by
  `tools/ui/cutout_icons.py` (`item_<id>.png` sources) and resized to 512 px to
  match the earlier `icon_broom_*` icons. Sources: `art/brooms/icons_src/`.

## 2026-10-16 additions (fal.ai) - enchantment scrolls

Tool: fal.ai `google/nano-banana-2.1` (1K, 1:1), text prompt only (no input image).

* `icon_scroll_{imbue,reweave}.png` - the Rune of Imbuing (green) and Rune of
  Reweaving (violet) scrolls on flat white, cut out by `tools/ui/cutout_icons.py`
  (`item_<id>.png` sources in `art/enchant/icons_src/`), 512 px.

## 2026-10-16 additions (fal.ai) - cloak tiers

Tool: fal.ai `google/nano-banana-2.1/edit` (1K, 1:1). Input image: the project's own
cloak fabric texture for that tier (generated the same day with
`openai/gpt-image-2.5/sunburst`, shipped as `assets/models/cloaks/cloak_<tier>.png`);
no third-party image was used.

* `icon_cloak_{wool,runed,thornveil,phoenix,moonveil}.png` - the cloak seen from the
  back on flat white, cut out by `tools/ui/cutout_icons.py` (`item_<id>.png` sources
  in `art/cloaks/icons_src/`), 512 px.

## 2026-10-16 additions (fal.ai) - wand tiers

Tool: fal.ai `google/nano-banana-2.1/edit` (1K, 1:1). Input image: the project's own
wand concept for that tier (generated the same day with `openai/gpt-image-2.5/sunburst`,
kept in `art/wands/concepts/`); no third-party image was used.

* `icon_wand_{ashwood,runebound,silverthorn,emberwing,moonveil}.png` - the wand shown
  diagonally on flat white, cut out by `tools/ui/cutout_icons.py` (`item_<id>.png`
  sources in `art/wands/icons_src/`), 512 px. The in-game wand meshes themselves are
  procedural (`art/wands/scripts/build_wands.py`).
