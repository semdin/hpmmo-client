# Spell effects and music audio - provenance and credits

## Spell sounds (`spells/`, every `spell_*` key) - generated, 2026-10-16

The cast / travel / impact / sustain / end sounds of all seven spells (the basic
chain's three cast steps and two impacts included) were **generated with
ElevenLabs Sound Effects v2 through fal.ai** (`fal-ai/elevenlabs/sound-effects/v2`,
44.1 kHz PCM output) from the prompts in `art/audio_fal/sfx_spec.json`; the raw
takes are kept in `art/audio_fal/`. `client/tools/audio/import_fal_sfx.py` turns
them into the shipped files: mono downmix for positional playback, leading-silence
trim, loop crossfade for travel/sustain beds, and the same RMS targets as the rest
of the library (one-shots -17 dBFS, beds -20 dBFS). Generated output; commercial
use is permitted under the ElevenLabs / fal.ai terms of the generating account.
No third-party recording or sample pack is involved.

    python client/tools/audio/import_fal_sfx.py --art art/audio_fal --client client
    python client/tools/audio/tune_imports.py --client client   # loop flags

## Everything else - generated, 2026-10-19

Ambience beds (grounds, courtyard, village, forest, dark forest, moor, marsh,
shore, high wind, great hall, castle, library, dungeon, forbidden corridor,
fire, despair chill), the scattered one-shots, footsteps (five surfaces x four
takes), robe, broom (mount, dismount, landing, wind bed, swooshes, landing
refused), heartbeat, interface, doors, map transition and the inferi /
snatcher / spider / boss cues were **generated with ElevenLabs Sound Effects v2
through fal.ai** (`fal-ai/elevenlabs/sound-effects/v2`, pcm_44100). The
soundtrack (menu, two grounds themes, village, forest, wilds, two castle
themes, dungeon, forbidden corridor, flight, combat, boss) and the victory /
defeat / boss stingers were **generated with ElevenLabs Music v2.5**
(`elevenlabs/music/v2.5`, instrumental, MP3 128 kbps). Prompts live in
`client/tools/audio/audio_spec.json` (written by `make_audio_spec.py`); raw takes
in `art/audio_v2/`. Generated output; commercial use is permitted under the
ElevenLabs / fal.ai terms of the generating account. No third-party recording
or sample pack is involved.

    python client/tools/audio/make_audio_spec.py
    python client/tools/audio/import_audio_spec.py --art art/audio_v2 --client client --retire
    python client/tools/audio/tune_imports.py --client client   # loop flags (WAV)

The earlier synthesised set (`synth_spell_sfx.py`, classical arrangements) is
retired; that generator no longer feeds the library.
