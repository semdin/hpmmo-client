#!/usr/bin/env python3
"""Apply the spell effects audio import settings from the sound library manifest.

    python client/tools/audio/tune_imports.py --client client [--check]

Every looping bed (broom wind, ward hum, burn loop, room tones, wind, fire,
candles, activity, stairs) must import with the forward loop flag, or the engine
plays a single 5-second sample and stops - which is exactly what "looping
ambience" is not. Long beds keep the engine's compressed mode (QOA by default)
rather than being forced to PCM.

Run this after synth_spell_sfx.py and before the Godot import pass. `--check`
verifies the settings without writing (used by run_vfx_checks.ps1).
"""

import argparse
import json
import os
import sys

# Godot's WAV importer enum starts with "Detect From WAV" at 0, so FORWARD is 2
# (0 detect, 1 disabled, 2 forward, 3 ping-pong, 4 backward). Writing 1 here
# silently disables looping.
LOOP_FORWARD = "2"

DEFAULTS = {
    "edit/loop_mode": "1",
    "edit/loop_begin": "0",
    "edit/loop_end": "-1",
    "compress/mode": "2",
}


def library_path(client):
    return os.path.join(client, "assets", "audio", "sound_library.json")


def import_path(client, rel_audio_path):
    """rel_audio_path is 'assets/audio/...wav' as recorded in the manifest."""
    return os.path.join(client, rel_audio_path.replace("/", os.sep) + ".import")


def read_params(path):
    params = {}
    section = None
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("[") and line.endswith("]"):
                section = line[1:-1]
                continue
            if section != "params" or "=" not in line:
                continue
            key, value = line.split("=", 1)
            params[key.strip()] = value.strip()
    return params


def write_params(path, params, order):
    lines = []
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    out = []
    section = None
    seen = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if section == "params":
                for key in order:
                    if key not in seen:
                        out.append("%s=%s" % (key, params[key]))
                        seen.add(key)
            section = stripped[1:-1]
            out.append(line)
            continue
        if section == "params" and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in params:
                out.append("%s=%s" % (key, params[key]))
                seen.add(key)
                continue
        out.append(line)
    if section == "params":
        for key in order:
            if key not in seen:
                out.append("%s=%s" % (key, params[key]))
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(out) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--client", required=True)
    parser.add_argument("--check", action="store_true")
    parsed = parser.parse_args()
    manifest_path = library_path(parsed.client)
    if not os.path.exists(manifest_path):
        raise SystemExit("missing %s (run synth_spell_sfx.py first)" % manifest_path)
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)

    changed = []
    drift = []
    checked = 0
    for key, entry in sorted(manifest.get("sounds", {}).items()):
        path = import_path(parsed.client, String(entry["path"]))
        if not os.path.exists(path):
            drift.append("%s: no .import file yet (run the Godot import pass)" % key)
            continue
        params = read_params(path)
        wanted = dict(DEFAULTS)
        if entry.get("loop_mode") == "forward":
            wanted["edit/loop_mode"] = LOOP_FORWARD
            wanted["edit/loop_begin"] = "0"
            wanted["edit/loop_end"] = "-1"
            # Looping beds use IMA-ADPCM: QOA (the engine default) carries no
            # loop points, so a QOA bed plays once and stops - the exact
            # failure "looping ambience" must not have. Still compressed, so a
            # multi-second bed never ships as PCM.
            wanted["compress/mode"] = "1"
        else:
            wanted["edit/loop_mode"] = "0"
        # anything long and non-looping stays in the engine's compressed mode
        if not entry.get("loop", False) and float(entry.get("seconds", 0.0)) >= 2.0:
            wanted["compress/mode"] = params.get("compress/mode", "2")
        checked += 1
        needs = {k: v for k, v in wanted.items() if params.get(k) != v}
        if needs:
            if parsed.check:
                drift.append("%s: %s" % (key, needs))
            else:
                merged = dict(params)
                merged.update(needs)
                write_params(path, merged, list(DEFAULTS.keys()))
                changed.append("%s: %s" % (key, needs))

    if drift:
        for line in drift:
            print("DRIFT: " + line)
        print("tune_imports: %d sounds checked, %d drifted" % (checked, len(drift)))
        raise SystemExit(1)
    if parsed.check:
        print("tune_imports: %d sounds checked, settings match the manifest" % checked)
    else:
        print("tune_imports: %d sounds checked, %d import files updated (re-run the Godot import pass)"
              % (checked, len(changed)))


def String(value):
    return "" if value is None else str(value)


if __name__ == "__main__":
    main()
