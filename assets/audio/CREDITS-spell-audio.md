# Spell effects and music audio - provenance and credits

**Everything in this folder is PROJECT-ORIGINAL synthesis.** No sample pack, no
downloaded file, no third-party recording, and no image/audio generator is
involved. There is nothing to attribute and nothing to license.

## What made these files

`client/tools/audio/synth_spell_sfx.py` - Python plus NumPy/SciPy (the `wave`
module plus seeded deterministic DSP: RBJ biquad filters, resonators, Schroeder
and Freeverb-lineage reverbs, envelopes, FM/additive/noise/granular primitives,
soft clipping, loop crossfades). The RNG is seeded with `20261005`, so re-running
the script reproduces every file byte-for-byte on the same interpreter. A final
loudness pass RMS-matches every sound (one-shots at -17 dBFS, beds at -20) with a
peak ceiling, so the authored per-file `gain_db` is what shapes the mix.

The music beds are built by the same script: a small sequencer places notes into
original instrument models (string ensemble, piano, harp, organ, choir, flute,
oboe, horn, timpani, bass, bells) and renders stereo, seam-continuous loops.

    python client/tools/audio/synth_spell_sfx.py --out client/assets/audio
    python client/tools/audio/tune_imports.py --client client   # loop flags
    godot --headless --path client --editor --import --quit

`assets/audio/sound_library.json` is generated beside the WAVs and is the
runtime contract: per-file bus, base gain, pitch variation, loop mode, whether
the sound is positional, and its purpose. `tools/audio/tune_imports.py` applies
the import settings the manifest calls for (forward loop flag on every bed;
IMA-ADPCM for the mono beds; PCM for the stereo music, which must keep both its
channels and its loop points).

## The classical music beds

The five music beds are **original synthesised arrangements of public-domain
classical material**. Every referenced composer died in 1925 or earlier, so the
compositions are out of copyright worldwide; no recording by anyone was used,
because the notes are placed by the sequencer in this repository.

- `music/menu_gymnopedie.wav` - Satie's Gymnopédie mood; slow waltz, sparse.
- `music/map_pastoral.wav` - Grieg's *Morning Mood* palette for the open map.
- `music/castle_canon.wav` - the Pachelbel progression under bells and choir.
- `music/dungeon_toccata.wav` - Bach's D-minor toccata, slowed into a loop.
- `music/combat_fate.wav` - the Beethoven fifth motif as a battle loop.

## Licence

Project-original, dedicated by the project under the same terms as the rest of
HPMMO's original art (CC0-equivalent dedication by the project). The files may
be redistributed with the game. The classical compositions the music beds
arrange are public domain; the arrangements themselves are project-original.

## The one external audio element, for completeness

Nothing under `assets/audio/` is external. The asset audit Kenney candidates
(`kenney-impact-sounds`, `kenney-rpg-audio`, CC0 1.0, kenney.nl) remain under
`assets/candidates/audio/` as *unused* candidates - this library deliberately
does not depend on them, so the shipped sound set has a single, provable
provenance. The packs that were pruned with the candidate download folder
(`kenney-interface-sounds`, `kenney-music-jingles`, `oga-fireplace-loop`) are
recorded in `assets/manifest.json` under `rejected`.
