# Localization

The game ships in Turkish (default) and English. Players pick the language on
the login screen (top right, under the server status) or in game under
**Settings > General > Language**. The choice is per machine
(`<install>/userdata/language.cfg`, or `user://` in the editor), so the login
screen already knows it before anyone signs in.

## How it works

- **English is the source language.** Every English string in the code, the
  scenes and the data JSON is its own message id. English needs no catalogue.
- **One gettext catalogue per language**: `locale/<code>.po`, listed under
  `internationalization/locale/translations` in `project.godot`.
  `locale/messages.pot` is the template every catalogue is merged from.
- **`I18n` autoload** (`scripts/autoload/i18n.gd`) owns the locale: it applies
  the saved choice at startup, lists the languages the build can show
  (`I18n.languages()`), switches them (`I18n.set_language(code)`) and holds the
  helpers below. The dedicated server always runs in English.

## Writing translatable code

| Where | Write |
|---|---|
| Text in a node / object method | `tr("Inventory")` |
| Formatted text | `tr("Level %d") % level` - translate the pattern, then format |
| Static functions | `I18n.t("Refused")` |
| A value from the data JSON (item, mob, quest, map, spell name) | `I18n.t(String(item.name))` at the place it is shown |
| Text the world server composed (chat replies, boss and monolith lines, dungeon messages, creature names) | `I18n.from_server(text)` / `I18n.mob_name(name)`; a composed pattern goes into `I18n.COMPOSED` |
| Upper case | `I18n.upper(text)` - `to_upper()` turns Turkish "i" into "I" instead of "İ" |
| Window titles | pass English to `HudWindow.new("Settings", ...)` / `super._init(...)` / `set_title(...)`; the window translates it |
| A const table of names | put `# i18n-begin` / `# i18n-end` around it (or `# i18n` at the end of one line) and translate where it is used: `tr(String(NAMES[key]))` |

Never translate ids, keys, node names or anything compared against another
string - only what the player reads. Keep NPC names, quest targets and item ids
in English in the code; translate them where they are displayed.

## The catalogue tool

```bash
python tools/i18n/i18n.py extract
```

Collects every message (scripts, scenes, the data JSON listed in `DATA_RULES`)
into `locale/messages.pot` and merges it into every `.po`. Run it after adding or
changing text; new messages appear untranslated, removed ones are kept at the
end (`#~`) and come back if the text returns.

```bash
python tools/i18n/i18n.py status
```

Translated / missing count per language, and a check that every translation
keeps the `%s` / `%d` specifiers of its source (a mismatch breaks
`tr(...) % args` at runtime; the command then exits 1).

```bash
python tools/i18n/i18n.py missing tr
python tools/i18n/i18n.py apply tr translations.json
```

`missing` prints the untranslated ids as JSON (`{"id": ""}`), `apply` writes a
filled-in file of that shape back - the round trip for handing a batch to a
translator. The `.po` files also open in any gettext editor (Poedit, Weblate).

## Adding a language

```bash
python tools/i18n/i18n.py add-language de
```

creates `locale/de.po` from the template and registers it in `project.godot`.
Add the language's own name to `NATIVE_NAMES` in `scripts/autoload/i18n.gd` if
it is not there yet, translate the catalogue, and the pickers list it on the
next start.

## Testing

`--lang=<code>` on the command line overrides the saved choice (also for
headless runs), e.g.:

```powershell
godot --path client res://scenes/main/main_menu.tscn --solo --lang=en
```

Changing the language in game rebuilds nothing on its own: new text appears in
the new language, and the settings row offers **Change character now**, which
rebuilds the whole interface through the normal leave countdown.
