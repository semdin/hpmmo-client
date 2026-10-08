# Spell effects audio - provenance and credits

**Everything in this folder is PROJECT-ORIGINAL synthesis.** No sample pack, no
downloaded file, no third-party recording, and no image/audio generator is
involved. There is nothing to attribute and nothing to license.

## What made these files

`client/tools/audio/synth_spell_sfx.py` - Python standard library only (the `wave`
module plus seeded deterministic DSP: RBJ biquad filters, Schroeder reverb,
envelopes, FM/additive/noise/granular primitives, soft clipping, loop
crossfades). The RNG is seeded with `20261005`, so re-running the script
reproduces every file byte-for-byte on the same interpreter.

    python client/tools/audio/synth_spell_sfx.py --out client/assets/audio
    python client/tools/audio/tune_imports.py --client client   # loop flags
    godot --headless --path client --editor --import --quit

`assets/audio/sound_library.json` is generated beside the WAVs and is the
runtime contract: per-file bus, base gain, pitch variation, loop mode, whether
the sound is positional, and its purpose. `tools/audio/tune_imports.py` applies
the import settings the manifest calls for (forward loop flag on every bed;
compressed mode kept for anything over two seconds).

## Licence

Project-original, dedicated by the project under the same terms as the rest of
HPMMO's original art (CC0-equivalent dedication by the project). The files may
be redistributed with the game.

## The one external audio element, for completeness

Nothing under `assets/audio/` is external. The asset audit Kenney candidates
(`kenney-impact-sounds`, `kenney-rpg-audio`, `kenney-interface-sounds`,
`kenney-music-jingles`, CC0 1.0, kenney.nl) remain available under
`assets/candidates/` and `tools/downloads/asset-candidates/` as *unused*
candidates - this library deliberately does not depend on them, so the shipped
sound set has a single, provable provenance.
