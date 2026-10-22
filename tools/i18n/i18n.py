#!/usr/bin/env python3
"""Localisation catalogue tool: collect the game's English text and keep every
language's gettext catalogue (locale/<code>.po) in step with it.

The source language is English and every English string is its own message id
(see scripts/autoload/i18n.gd and docs/localization.md). This tool finds them:

  * scripts (scripts/**, addons/hpmmo_sim/*.gd): `tr("...")`, `I18n.t("...")`
    (and the simulation's `_t("...")`) with an optional second argument as
    the context, window titles
    (`HudWindow.new("...")`, `super._init("...")`), every literal on a line
    ending in `# i18n`, and every literal that is not a dictionary key between
    `# i18n-begin` and `# i18n-end` lines (for const tables of names);
  * scenes (scenes/**, not scenes/test): text / placeholder_text / tooltip_text;
  * the data JSON: the player-facing fields listed in DATA_RULES.

Commands (run from anywhere):
  i18n.py extract                 rewrite locale/messages.pot, merge it into every .po
  i18n.py status                  translated / missing count per language
  i18n.py missing <code> [-n N]   untranslated message ids as JSON ({id: ""})
  i18n.py apply <code> <file>     fill translations from a JSON {id: text} file
                                  (a context goes in front: "ctx\\u0004id")
  i18n.py add-language <code>     new catalogue from the template + register it

Obsolete translations are kept at the end of a catalogue (#~) and come back on
their own if the text returns.
"""

import argparse
import glob
import json
import os
import re
import sys

CLIENT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOCALE_DIR = os.path.join(CLIENT, "locale")
POT = os.path.join(LOCALE_DIR, "messages.pot")
PROJECT = os.path.join(CLIENT, "project.godot")
CTX_SEP = "\u0004"

SCRIPT_GLOBS = ["scripts/**/*.gd", "addons/hpmmo_sim/*.gd"]
SCRIPT_SKIP = ("scripts/test/",)
SCENE_GLOBS = ["scenes/**/*.tscn"]
SCENE_SKIP = ("scenes/test/",)
SCENE_PROPS = ("text", "placeholder_text", "tooltip_text")
# Scene text the game always overwrites before it is seen (level badges, the
# editor's sample names): never offered for translation.
SCENE_TEXT_SKIP = re.compile(r"^\[Lv\.|\(Lv\.\d+\)|^\[[A-Z][a-z]+\]$|^[^A-Za-z]*$")

# Data files and the fields a player reads. A rule's keys apply at any depth;
# "@keys" also takes the object's own keys (quest place names).
DATA_RULES = [
    ("addons/hpmmo_sim/data/items.json", ("name", "desc")),
    ("addons/hpmmo_sim/data/mobs.json", ("display", "name_prefix")),
    ("addons/hpmmo_sim/data/spawn_tables.json", ("display", "name")),
    ("addons/hpmmo_sim/data/maps.json", ("display", "label")),
    ("addons/hpmmo_sim/data/spells.json", ("name", "desc")),
    ("addons/hpmmo_sim/data/dungeons.json", ("display", "message", "name")),
    ("addons/hpmmo_sim/data/travel.json", ("label", "prompt")),
    ("addons/hpmmo_sim/data/quests.json", ("title", "name", "desc", "chapter", "giver")),
    ("addons/hpmmo_sim/data/quests.json#places", ("@keys",)),
    ("addons/hpmmo_sim/data/combat.json", ("desc", "label", "titles")),
    ("data/json/houses.json", ("trait",)),
    ("assets/castle/castle_layout.json", ("label",)),
    ("data/json/quests.json", ("title", "desc", "npc")),
]

STR = r'"((?:[^"\\\n]|\\.)*)"'
CALL = re.compile(r'(?:(?<![\w.])(?:tr|atr|_t|I18n\.t)|super\._init|HudWindow\.new)\(\s*' + STR + r'(?:\s*,\s*' + STR + r')?')
LITERAL = re.compile(STR + r'(\s*:)?')


def unescape(s):
    return (s.replace("\\\\", "\0").replace('\\"', '"').replace("\\n", "\n")
            .replace("\\t", "\t").replace("\0", "\\"))


def escape(s):
    return (s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
            .replace("\t", "\\t"))


def rel(path):
    return os.path.relpath(path, CLIENT).replace("\\", "/")


class Catalogue:
    """Ordered (context, id) -> {refs, comments} collected from the sources."""

    def __init__(self):
        self.entries = {}

    def add(self, msgid, ref, context=""):
        if not msgid.strip() or not re.search(r"[A-Za-z]", msgid):
            return
        key = (context, msgid)
        entry = self.entries.setdefault(key, {"refs": []})
        if ref not in entry["refs"]:
            entry["refs"].append(ref)


def scan_scripts(cat):
    for pattern in SCRIPT_GLOBS:
        for path in sorted(glob.glob(os.path.join(CLIENT, pattern), recursive=True)):
            r = rel(path)
            if r.startswith(SCRIPT_SKIP):
                continue
            in_block = False
            with open(path, encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("#") and "i18n-begin" in stripped:
                        in_block = True
                        continue
                    if stripped.startswith("#") and "i18n-end" in stripped:
                        in_block = False
                        continue
                    if stripped.startswith("#"):
                        continue
                    for m in CALL.finditer(line):
                        cat.add(unescape(m.group(1)), r, unescape(m.group(2) or ""))
                    if in_block or re.search(r"#\s*i18n\s*$", line):
                        code = line.split("#")[0] if not in_block else line
                        for m in LITERAL.finditer(code):
                            if m.group(2) or re.fullmatch(r"[a-z0-9_]+", m.group(1)):
                                continue  # a dictionary key or an id
                            cat.add(unescape(m.group(1)), r)


def scan_scenes(cat):
    prop = re.compile(r'^(%s) = "((?:[^"\\]|\\.)*)"' % "|".join(SCENE_PROPS), re.S | re.M)
    for pattern in SCENE_GLOBS:
        for path in sorted(glob.glob(os.path.join(CLIENT, pattern), recursive=True)):
            r = rel(path)
            if r.startswith(SCENE_SKIP):
                continue
            with open(path, encoding="utf-8") as f:
                text = f.read()
            for m in prop.finditer(text):
                value = unescape(m.group(2))
                if SCENE_TEXT_SKIP.search(value):
                    continue
                cat.add(value, r)


def scan_data(cat):
    for spec, keys in DATA_RULES:
        file, _, sub = spec.partition("#")
        path = os.path.join(CLIENT, file)
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if sub:
            data = data.get(sub, {})

        def walk(node):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k.startswith("_"):
                        continue
                    if "@keys" in keys:
                        cat.add(k, file)
                        continue
                    if k in keys and isinstance(v, str):
                        cat.add(v, file)
                    elif k in keys and isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                cat.add(item, file)
                            else:
                                walk(item)
                    else:
                        walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)


def collect():
    cat = Catalogue()
    scan_scripts(cat)
    scan_scenes(cat)
    scan_data(cat)
    return cat


# ---------------------------------------------------------------- .po files

def parse_po(path):
    """[(context, id) -> {"str": text, "flags": [...]}], header text, obsolete."""
    entries, obsolete, header = {}, {}, ""
    if not os.path.isfile(path):
        return entries, header, obsolete
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    cur, field, flags, is_obsolete = {}, None, [], False

    def flush():
        nonlocal cur, field, flags, is_obsolete, header
        if "msgid" in cur:
            key = (cur.get("msgctxt", ""), cur["msgid"])
            if key == ("", ""):
                header = cur.get("msgstr", "")
            else:
                (obsolete if is_obsolete else entries)[key] = {
                    "str": cur.get("msgstr", ""), "flags": flags}
        cur, field, flags, is_obsolete = {}, None, [], False

    for raw in lines + [""]:
        line = raw
        if not line.strip():
            flush()
            continue
        if line.startswith("#~"):
            is_obsolete = True
            line = line[2:].strip()
            if not line:
                continue
        elif line.startswith("#,"):
            flags = [x.strip() for x in line[2:].split(",")]
            continue
        elif line.startswith("#"):
            continue
        m = re.match(r'^(msgctxt|msgid|msgstr)\s+"(.*)"\s*$', line)
        if m:
            if m.group(1) in cur and m.group(1) != "msgstr":
                flush()
            field = m.group(1)
            cur[field] = unescape(m.group(2))
            continue
        m = re.match(r'^"(.*)"\s*$', line)
        if m and field:
            cur[field] += unescape(m.group(1))
    return entries, header, obsolete


def header_for(code):
    plural = "nplurals=2; plural=(n > 1);" if code == "tr" else "nplurals=2; plural=(n != 1);"
    lines = [
        "Project-Id-Version: HPMMO",
        "Language: " + code,
        "MIME-Version: 1.0",
        "Content-Type: text/plain; charset=UTF-8",
        "Content-Transfer-Encoding: 8bit",
        "Plural-Forms: " + plural,
    ]
    return "".join(l + "\n" for l in lines)


def entry_text(key, msgstr, refs=None, flags=None, obsolete=False):
    context, msgid = key
    out = []
    if refs:
        out.append("#: " + " ".join(refs[:6]))
    if flags:
        out.append("#, " + ", ".join(flags))
    p = "#~ " if obsolete else ""
    if context:
        out.append(p + 'msgctxt "%s"' % escape(context))
    out.append(p + 'msgid "%s"' % escape(msgid))
    out.append(p + 'msgstr "%s"' % escape(msgstr))
    return "\n".join(out)


def write_po(path, code, ordered, translations, obsolete):
    blocks = ['msgid ""\nmsgstr ""\n' + "".join('"%s"\n' % escape(l + "\n") for l in header_for(code).splitlines())]
    blocks[0] = blocks[0].rstrip("\n")
    for key, info in ordered:
        msgstr = translations.get(key, {}).get("str", "") if translations is not None else ""
        blocks.append(entry_text(key, msgstr, info["refs"]))
    for key, info in sorted(obsolete.items()):
        if info.get("str"):
            blocks.append(entry_text(key, info["str"], obsolete=True))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n\n".join(blocks) + "\n")


def languages():
    return sorted(os.path.splitext(os.path.basename(p))[0]
                  for p in glob.glob(os.path.join(LOCALE_DIR, "*.po")))


def merge(code, ordered):
    path = os.path.join(LOCALE_DIR, code + ".po")
    current, _, obsolete = parse_po(path)
    live = {k for k, _ in ordered}
    translations = dict(current)
    for key, info in obsolete.items():  # a returning string gets its old text back
        if key in live and not translations.get(key, {}).get("str"):
            translations[key] = info
    gone = {k: v for k, v in {**obsolete, **current}.items() if k not in live and v.get("str")}
    write_po(path, code, ordered, translations, gone)
    done = sum(1 for k in live if translations.get(k, {}).get("str"))
    return done, len(live)


def cmd_extract(_args):
    os.makedirs(LOCALE_DIR, exist_ok=True)
    cat = collect()
    ordered = list(cat.entries.items())
    write_po(POT, "", ordered, None, {})
    print("messages.pot: %d messages" % len(ordered))
    for code in languages():
        done, total = merge(code, ordered)
        print("%s.po: %d / %d translated" % (code, done, total))


FORMAT = re.compile(r"%[-+0#]*\d*(?:\.\d+)?[sdfxX%]")


def placeholders(text):
    """The format specifiers a translation must keep, in order (%% excluded)."""
    return [m[-1] for m in FORMAT.findall(text) if m != "%%"]


def cmd_status(_args):
    bad = 0
    for code in languages():
        entries, _, _ = parse_po(os.path.join(LOCALE_DIR, code + ".po"))
        done = sum(1 for v in entries.values() if v["str"])
        print("%s: %d / %d translated, %d missing" % (code, done, len(entries), len(entries) - done))
        # A translation that drops, adds or reorders a %s / %d breaks the
        # game's `tr("...") % args` at runtime.
        for (ctx, msgid), v in entries.items():
            if v["str"] and "%" in msgid + v["str"] and placeholders(msgid) != placeholders(v["str"]):
                bad += 1
                print("  format mismatch: %r -> %r" % (msgid[:70], v["str"][:70]))
    if bad:
        sys.exit(1)


def cmd_missing(args):
    entries, _, _ = parse_po(os.path.join(LOCALE_DIR, args.code + ".po"))
    out = {}
    for (ctx, msgid), v in entries.items():
        if not v["str"]:
            out[(ctx + CTX_SEP if ctx else "") + msgid] = ""
            if args.n and len(out) >= args.n:
                break
    json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
    print()


def cmd_apply(args):
    path = os.path.join(LOCALE_DIR, args.code + ".po")
    entries, _, obsolete = parse_po(path)
    with open(args.file, encoding="utf-8") as f:
        given = json.load(f)
    applied, unknown = 0, []
    for k, text in given.items():
        ctx, _, msgid = k.rpartition(CTX_SEP)
        key = (ctx, msgid)
        if key not in entries:
            unknown.append(msgid)
            continue
        if text:
            entries[key] = {"str": text, "flags": []}
            applied += 1
    cat = collect()
    ordered = list(cat.entries.items())
    write_po(path, args.code, ordered, entries, {k: v for k, v in obsolete.items() if k not in entries})
    print("applied %d translations to %s.po" % (applied, args.code))
    if unknown:
        print("%d ids not in the catalogue (run extract first?):" % len(unknown))
        for u in unknown[:20]:
            print("  " + u[:100])


def cmd_add_language(args):
    code = args.code
    path = os.path.join(LOCALE_DIR, code + ".po")
    if os.path.exists(path):
        raise SystemExit("%s already exists" % rel(path))
    ordered = list(collect().entries.items())
    write_po(path, code, ordered, {}, {})
    with open(PROJECT, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'locale/translations=PackedStringArray\(([^)]*)\)', text)
    res = '"res://locale/%s.po"' % code
    if m and res not in m.group(1):
        inner = (m.group(1) + ", " + res) if m.group(1).strip() else res
        text = text[:m.start(1)] + inner + text[m.end(1):]
        with open(PROJECT, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
    print("created %s (%d messages) and registered it in project.godot" % (rel(path), len(ordered)))
    print("add its native name to NATIVE_NAMES in scripts/autoload/i18n.gd if it is missing")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("extract").set_defaults(fn=cmd_extract)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    p = sub.add_parser("missing")
    p.add_argument("code")
    p.add_argument("-n", type=int, default=0)
    p.set_defaults(fn=cmd_missing)
    p = sub.add_parser("apply")
    p.add_argument("code")
    p.add_argument("file")
    p.set_defaults(fn=cmd_apply)
    p = sub.add_parser("add-language")
    p.add_argument("code")
    p.set_defaults(fn=cmd_add_language)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
