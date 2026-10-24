"""Write tools/audio/audio_spec.json: every generated (non-spell) sound and music bed.

One entry per sound_library key. SFX are generated with ElevenLabs Sound Effects v2
on fal.ai (fal-ai/elevenlabs/sound-effects/v2, pcm_44100), music with ElevenLabs
Music v2.5 (elevenlabs/music/v2.5, mp3_44100_128, force_instrumental). The spell,
basic-attack and creature cues from the 2026-10-16 pass live in
art/audio_fal/sfx_spec.json and are not touched here.

Fields: kind (sfx|music), path (under assets/audio), seconds, loop, bus, gain_db,
spatial, pv (pitch variation), text (prompt). Import with import_audio_spec.py.

Usage: python make_audio_spec.py
"""
import json, os

TAIL = ", no music, no voice"
SFX = {}
MUSIC = {}


def sfx(key, path, seconds, text, bus="sfx", gain=-12.0, spatial=True, pv=0.06, loop=False, tail=TAIL):
    SFX[key] = {"kind": "sfx", "path": "assets/audio/" + path, "seconds": seconds, "loop": loop,
                "bus": bus, "gain_db": gain, "spatial": spatial, "pv": pv, "text": text + tail}


def bed(key, path, text, gain=-18.0, seconds=22.0, spatial=False, bus="ambience"):
    sfx(key, path, seconds, text + ", seamless loop", bus=bus, gain=gain, spatial=spatial, pv=0.0, loop=True)


def music(key, path, seconds, prompt, gain=-11.0, loop=False):
    MUSIC[key] = {"kind": "music", "path": "assets/audio/" + path, "seconds": seconds, "loop": loop,
                  "bus": "music", "gain_db": gain, "spatial": False, "pv": 0.0, "text": prompt}


# ------------------------------------------------------------------ ambience beds
bed("amb_grounds", "ambience/grounds.wav",
    "Peaceful magical castle grounds on a mild sunny day: soft breeze through tall grass, distant songbirds, gently rustling leaves, calm open meadow, very relaxing", gain=-19.0)
bed("amb_courtyard", "ambience/courtyard.wav",
    "Sheltered old stone castle courtyard: a small fountain trickling softly, light breeze, faraway birds, calm and safe", gain=-20.0)
bed("amb_village", "ambience/village.wav",
    "Quiet fantasy village square: distant soft murmur of townsfolk, a wooden shop sign creaking, chickens far away, light breeze, cozy and calm", gain=-20.0)
bed("amb_forest", "ambience/forest.wav",
    "Dense ancient forest: wind high in the canopy, old trees creaking softly, sparse distant birds, insects humming, slightly mysterious", gain=-18.0)
bed("amb_forest_dark", "ambience/forest_dark.wav",
    "Dark haunted forest at dusk: low eerie wind through twisted trees, crickets, a distant owl, branches creaking, unsettling quiet", gain=-18.0)
bed("amb_moor", "ambience/moor.wav",
    "Bleak windswept highland moor: cold steady wind over heather and rocks, desolate and lonely, faint distant crow", gain=-18.0)
bed("amb_marsh", "ambience/marsh.wav",
    "Misty swamp marsh: still water, frogs croaking softly, insects, occasional mud bubbling, damp and gloomy", gain=-19.0)
bed("amb_shore", "ambience/shore.wav",
    "Misty lake shore: gentle waves lapping on pebbles, cool breeze, melancholic and calm", gain=-19.0)
bed("amb_high_wind", "ambience/high_wind.wav",
    "High altitude wind far above the ground: broad airy wind rush, open sky, cold and vast", gain=-17.0)
bed("amb_great_hall", "ambience/great_hall.wav",
    "Vast stone great hall interior of a magical castle: warm hearth crackling far away, faint echoing murmur of many distant people, tall ceiling reverb, cozy", gain=-20.0)
bed("amb_castle", "ambience/castle.wav",
    "Ancient stone castle corridor interior: soft cool draft, quiet low room tone, faint torch flicker, very distant echoing door", gain=-20.0)
bed("amb_library", "ambience/library.wav",
    "Silent old library interior: very quiet warm room tone, faint candle flicker, soft creak of wooden shelves, peaceful, no clock", gain=-22.0)
bed("amb_dungeon", "ambience/dungeon.wav",
    "Deep underground stone dungeon: low ominous cavern drone, distant echoing water drips, faint far-off rumble, cold and oppressive", gain=-17.0)
bed("amb_corridor", "ambience/forbidden_corridor.wav",
    "Forbidden stone corridor at night: heavy ominous silence, low rumbling drone, a huge beast breathing slowly far away behind a door, dread", gain=-17.0)
bed("amb_fire", "ambience/fire_loop.wav",
    "Fireplace hearth: warm crackling logs, soft wood pops, gentle low roar of flames", gain=-18.0, seconds=16.0, spatial=True)
bed("amb_despair", "ambience/despair.wav",
    "Supernatural icy chill: freezing hollow wind, frost creeping and crackling on stone, a faint ghostly rattling breath, dread", gain=-16.0, seconds=14.0)
bed("tension_heartbeat", "character/heartbeat.wav",
    "A slow heavy human heartbeat, deep muffled thumps, tense and close", gain=-10.0, seconds=8.0, bus="ui")
bed("broom_wind", "character/broom_wind.wav",
    "Flying on a broomstick: rushing wind past the ears, airy whoosh with robes fluttering, steady", gain=-14.0, seconds=12.0, bus="sfx")

# ------------------------------------------------------------------ scatter one-shots
for i, t in enumerate([
        "A single songbird singing a short sweet melodic phrase in the distance, natural, outdoors",
        "A blackbird's short fluting song from a tree, natural, outdoors",
        "Two small birds chirping a brief cheerful exchange far away, natural",
        "A wood pigeon cooing softly in the distance, natural"], 1):
    sfx("amb_bird_%d" % i, "ambience/birds/bird_%02d.wav" % i, 2.5, t, gain=-20.0, pv=0.05)
for i, t in enumerate(["A soft rolling gust of wind sweeping across an open field",
                       "A long gentle breeze swelling and fading through grass and trees"], 1):
    sfx("amb_wind_gust_%d" % i, "ambience/wind/wind_gust_%02d.wav" % i, 4.0, t, gain=-19.0, spatial=False, pv=0.04)
for i, t in enumerate(["Leaves rustling gently in a passing breeze in a tree",
                       "A bush's branches and foliage brushing softly in the wind"], 1):
    sfx("amb_leaf_rustle_%d" % i, "ambience/nature/leaf_rustle_%02d.wav" % i, 2.0, t, gain=-21.0)
for i, t in enumerate(["An old tree trunk creaking slowly in the wind, deep woody groan",
                       "Tall trees swaying and creaking in a forest, wooden strain"], 1):
    sfx("amb_tree_creak_%d" % i, "ambience/nature/tree_creak_%02d.wav" % i, 2.5, t, gain=-20.0)
sfx("amb_branch_snap", "ambience/nature/branch_snap.wav", 1.2,
    "A dry twig snapping somewhere in the undergrowth nearby, followed by silence, tense", gain=-18.0)
sfx("amb_owl_1", "ambience/nature/owl_01.wav", 2.5, "A tawny owl hooting twice in a dark forest, distant", gain=-19.0, pv=0.04)
sfx("amb_owl_2", "ambience/nature/owl_02.wav", 2.5, "A barn owl's eerie screech far away at night", gain=-21.0, pv=0.04)
sfx("amb_wolf_howl", "ambience/nature/wolf_howl.wav", 5.0, "A lone wolf howling far away in the hills, echoing, haunting", gain=-20.0, spatial=False, pv=0.04)
for i, t in enumerate(["A crow cawing harshly a few times from a distance",
                       "A raven's deep croak echoing over empty moorland"], 1):
    sfx("amb_crow_%d" % i, "ambience/nature/crow_%02d.wav" % i, 2.0, t, gain=-20.0)
for i, t in enumerate(["A large frog croaking in a swamp", "Several frogs croaking softly in marsh reeds"], 1):
    sfx("amb_frog_%d" % i, "ambience/nature/frog_%02d.wav" % i, 2.0, t, gain=-20.0)
sfx("amb_bubble", "ambience/nature/mud_bubble.wav", 1.5, "Thick swamp mud bubbling and popping slowly", gain=-21.0)
sfx("amb_wave", "ambience/nature/wave.wav", 3.5, "A single small lake wave washing over pebbles and drawing back", gain=-20.0)
sfx("amb_castle_door_far", "ambience/castle/door_far.wav", 2.5, "A heavy wooden door closing somewhere far away down a stone corridor, long echo", gain=-21.0)
sfx("amb_castle_steps_far", "ambience/castle/steps_far.wav", 3.0, "Distant footsteps hurrying along a stone corridor and fading away, echoing", gain=-22.0)
sfx("amb_ghost_laugh", "ambience/castle/ghost_laugh.wav", 2.5, "A faint playful ghostly giggle drifting past and fading, echoing in a stone hall, magical", gain=-22.0, tail=", no music")
sfx("amb_magic_chime", "ambience/castle/magic_chime.wav", 3.0, "A soft distant magical shimmer, delicate twinkling chimes like enchanted dust, fading slowly", gain=-21.0)
sfx("amb_portrait_whisper", "ambience/castle/portrait_whisper.wav", 2.5, "Faint unintelligible hushed whispering from old paintings in a quiet corridor, mysterious", gain=-23.0, tail=", no music")
sfx("amb_owl_flutter", "ambience/castle/owl_flutter.wav", 2.5, "An owl's wings flapping overhead under a high stone ceiling, then a soft hoot", gain=-21.0)
sfx("amb_hall_laughter", "ambience/castle/hall_laughter.wav", 3.0, "Distant warm laughter of a crowd echoing in a great hall, faint and muffled", gain=-24.0, tail=", no music")
for i, t in enumerate(["A parchment page being turned slowly", "An old heavy book being closed softly on a wooden table"], 1):
    sfx("amb_library_page_%d" % i, "ambience/library/page_%02d.wav" % i, 1.5, t, gain=-21.0)
sfx("amb_quill", "ambience/library/quill.wav", 2.0, "A feather quill scratching on parchment, writing briefly", gain=-22.0)
for i, t in enumerate(["A single water drop falling into a puddle in a cave, echoing",
                       "A slow water drip in a stone dungeon with a long reverberant tail",
                       "Two water drops plinking into a pool in a deep cavern, echo"], 1):
    sfx("amb_dungeon_drip_%d" % i, "ambience/dungeon/drip_%02d.wav" % i, 1.5, t, gain=-19.0, pv=0.08)
sfx("amb_dungeon_rumble", "ambience/dungeon/rumble.wav", 3.5, "Deep subterranean rumble of shifting stone, dust trickling down, ominous", gain=-18.0, spatial=False, pv=0.04)
sfx("amb_dungeon_chains", "ambience/dungeon/chains.wav", 2.5, "Rusty iron chains rattling and swaying somewhere in a dark dungeon, echo", gain=-21.0)
sfx("amb_dungeon_growl", "ambience/dungeon/growl_far.wav", 3.0, "A deep beast growl echoing from far down a dark tunnel, menacing", gain=-21.0, spatial=False, pv=0.05)
for i, t in enumerate(["A ghostly breathy whisper drifting through a dungeon and fading, eerie",
                       "A cold sighing draft moaning through stone cracks, haunting"], 1):
    sfx("amb_dungeon_whisper_%d" % i, "ambience/dungeon/whisper_%02d.wav" % i, 3.0, t, gain=-22.0, tail=", no music")

# ------------------------------------------------------------------ character
SURF = {
    "grass": "on soft grass",
    "dirt": "on a dry dirt path",
    "stone": "on hard stone floor, slight castle echo",
    "wood": "on old wooden floorboards",
    "water": "splashing in shallow water",
}
for surface, where in SURF.items():
    for i in range(1, 5):
        sfx("step_%s_%d" % (surface, i), "footsteps/%s_%02d.wav" % (surface, i), 0.5,
            "A single light footstep of a person in soft leather boots %s, one step only, variation %d" % (where, i),
            gain=-13.0, pv=0.07)
for i, t in enumerate(["Heavy wool robe fabric swishing as someone turns",
                       "Cloak cloth rustling briefly with movement",
                       "A long robe flapping softly once"], 1):
    sfx("robe_%d" % i, "character/robe_%02d.wav" % i, 0.6, t, gain=-18.0, pv=0.08)
sfx("mount", "character/mount.wav", 1.2, "A broomstick lifting off: a quick magical whoosh rising upward with a soft airy shimmer", gain=-9.0)
sfx("dismount", "character/dismount.wav", 0.9, "Hopping off a broomstick and landing lightly on the feet, cloth rustle", gain=-10.0)
sfx("landing", "character/landing.wav", 0.8, "A person landing on the ground after a short drop, solid soft thud with cloth rustle", gain=-9.0)
sfx("broom_land_blocked", "character/broom_land_blocked.wav", 0.9,
    "A soft magical refusal: a gentle low wooden knock with a dull fizzling shimmer, like a charm declining, short and subtle", bus="ui", gain=-11.0, spatial=False, pv=0.0)
for i, t in enumerate(["A fast swoosh of air as a broom rider banks sharply past",
                       "A quick airy whoosh of a broomstick diving and pulling up"], 1):
    sfx("broom_swoosh_%d" % i, "character/broom_swoosh_%02d.wav" % i, 1.2, t, gain=-13.0, spatial=False, pv=0.07)

# ------------------------------------------------------------------ interface
UI = {
    "ui_button": (0.5, "A soft wooden click of an old parchment menu button, subtle and warm", -12.0),
    "ui_hover": (0.5, "A tiny faint magical tick of shimmer, extremely subtle and soft", -20.0),
    "ui_open": (0.6, "A leather-bound book opening softly with a faint magic shimmer", -12.0),
    "ui_close": (0.6, "A leather-bound book closing softly, gentle thump", -12.0),
    "ui_confirm": (0.8, "A pleasant bright magical chime confirming a choice, two warm notes", -12.0),
    "ui_cancel": (0.6, "A soft descending parchment swish, cancelling, gentle", -13.0),
    "ui_deny": (0.7, "A soft muted low wooden knock with a dull fizzle, gentle refusal", -12.0),
    "ui_chat": (0.5, "A tiny soft owl-post paper flutter, very short notification", -16.0),
    "ui_coin": (0.8, "A few gold coins clinking into a leather purse", -11.0),
    "ui_loot": (0.9, "Picking up a treasure item: soft cloth rustle with a sparkling magical glint", -11.0),
    "ui_equip": (0.7, "Putting on leather armor gear: buckle clasp and cloth rustle", -11.0),
    "ui_unequip": (0.7, "Taking off leather gear: strap loosening and soft cloth drop", -12.0),
    "ui_potion": (1.0, "Drinking a magic potion: cork pop, a gulp and a soft bubbling sparkle", -10.0),
    "ui_hit": (0.5, "A soft muted punchy body hit thump, short, subtle", -14.0),
    "ui_death": (3.0, "A dark sorrowful descending magical swell with a deep low gong, fading into silence", -9.0),
    "ui_respawn": (2.5, "A warm rising magical shimmer of golden light and soft chimes, revival", -10.0),
    "ui_upgrade_success": (1.5, "Enchanting an item succeeds: a hammer strike on an anvil with a bright magical sparkle burst", -10.0),
    "ui_upgrade_fail": (1.5, "Enchanting an item fails: a hammer strike, a crack and a fizzling dying spark", -10.0),
    "map_transition": (2.5, "Magical teleport: a swirling airy whoosh rising into a soft shimmering pop", -10.0),
}
for key, (sec, text, gain) in UI.items():
    name = key[3:] if key.startswith("ui_") else key
    folder = "transitions" if key == "map_transition" else "ui"
    sfx(key, "%s/%s.wav" % (folder, name), sec, text, bus="ui", gain=gain, spatial=False, pv=0.03)
sfx("door_open", "transitions/door_open.wav", 1.5, "A heavy old wooden castle door creaking open on iron hinges", gain=-11.0)
sfx("door_close", "transitions/door_close.wav", 1.5, "A heavy old wooden castle door closing with a deep thud and latch", gain=-11.0)

# ------------------------------------------------------------------ creatures still on synth
MON = {
    "inferi": ("an undead drowned corpse creature", "hollow wet moan", "grasping lunge with a rotten gurgle", "long wet collapsing exhale"),
    "snatcher": ("a hooded dark wizard bandit", "rasping snarl as he spots prey", "lunging curse with a nasty grunt", "choked rasp and body collapse"),
    "spider": ("a giant spider", "agitated hiss and chitin clicking", "fast venomous bite snap with a hiss", "chitin crunch and expiring hiss, legs twitching"),
    "goblin": ("a small sly goblin bank guard", "sharp nasal hiss of outrage, no words", "quick claw swipe with a vicious little snarl", "strangled shriek and a jingle of spilled gold coins"),
}
for name, (who, alert, attack, death) in MON.items():
    gain = -6.0
    sfx("%s_alert" % name, "monsters/%s_alert.wav" % name, 1.5, "Fantasy game monster: %s, %s" % (who, alert), gain=gain)
    sfx("%s_%s" % (name, "bite" if name == "spider" else "attack"), "monsters/%s_%s.wav" % (name, "bite" if name == "spider" else "attack"),
        0.8, "Fantasy game monster: %s, %s, short" % (who, attack), gain=gain)
    sfx("%s_death" % name, "monsters/%s_death.wav" % name, 2.0, "Fantasy game monster death: %s, %s" % (who, death), gain=gain)
MOVES = {
    "inferi": ["slow shuffling wet footsteps with a low moan", "a gurgling groan while dragging its feet", "a raspy breath and wet shuffle"],
    "snatcher": ["rasping breath and quick boot steps", "a low mutter-less growl and cloak swish", "heavy breathing while running"],
    "spider": ["many legs skittering fast on the ground", "chitin legs clicking while crawling", "quick hairy legs scuttling"],
    "goblin": ["quick light footsteps and jingling keys", "a wordless muttering hiss and soft footsteps", "fast pattering little feet with coins clinking"],
}
for name, lines in MOVES.items():
    for i, t in enumerate(lines, 1):
        sfx("%s_move_%d" % (name, i), "monsters/%s_move_%02d.wav" % (name, i), 0.8, "Fantasy game monster: %s, %s, very short" % (MON[name][0], t),
            gain=-14.0, pv=0.08)
sfx("boss_alert", "monsters/boss_alert.wav", 2.5, "A colossal stone golem boss awakening: deep earth-shaking roar with grinding rock", gain=-5.0, pv=0.02)
sfx("boss_death", "monsters/boss_death.wav", 3.0, "A colossal boss monster dying: a long fading bellow and a massive rocky collapse", gain=-4.0, pv=0.02)
sfx("boss_slam_cast", "monsters/boss_slam_cast.wav", 1.2, "A giant monster charging a ground slam: deep rising guttural growl and rumbling energy build-up", gain=-4.0, pv=0.03)
sfx("boss_slam_release", "monsters/boss_slam_release.wav", 1.6, "A giant monster slamming the ground: massive impact boom with rocks cracking", gain=-2.5, pv=0.03)

# ------------------------------------------------------------------ music (ElevenLabs Music v2.5)
STYLE = ("Original fantasy video game soundtrack, cinematic orchestral, high production quality, instrumental only. ")
music("music_menu", "music/menu_theme.mp3", 150, STYLE +
      "Main menu theme for a magical wizard school MMO: a mysterious, wondrous celesta melody over soft strings and harp, warm horns join, sense of wonder and nostalgia, waltz feel 3/4, moderate tempo, grows gently then settles.", loop=True)
music("music_grounds_a", "music/grounds_a.mp3", 150, STYLE +
      "Peaceful exploration music for sunny castle grounds: gentle flute and clarinet melody, plucked harp, light strings, pastoral and calm, airy and relaxed, soft dynamics, no drums.")
music("music_grounds_b", "music/grounds_b.mp3", 150, STYLE +
      "Calm magical wandering theme: celesta and glockenspiel sparkles, oboe melody, warm string pads, whimsical yet serene, slow tempo, very gentle, no drums.")
music("music_village", "music/village.mp3", 120, STYLE +
      "Cozy fantasy village tavern-town music: acoustic lute, fiddle and recorder, light hand percussion, warm, friendly and relaxed, folk medieval feel, moderate tempo.")
music("music_forest", "music/forest.mp3", 150, STYLE +
      "Mysterious ancient forest exploration: low sustained strings, sparse alto flute, soft harp ostinato, distant french horn, slightly uneasy and curious, slow tempo, quiet.")
music("music_wilds", "music/wilds_dark.mp3", 150, STYLE +
      "Dark dangerous wilderness, misty moors and haunted marshes: eerie low cello drones, dissonant soft choir pads, sparse piano notes, cold wind-like textures, tense and lonely, slow, quiet but unsettling.")
music("music_castle_a", "music/castle_a.mp3", 150, STYLE +
      "Inside an ancient magical castle: grand yet warm, harpsichord and pizzicato strings, woodwinds with a curious playful melody, soft celesta, a hint of mystery, moderate tempo, light.")
music("music_castle_b", "music/castle_b.mp3", 120, STYLE +
      "Quiet castle halls and old library at evening: solo piano and harp with soft strings, contemplative, warm candlelight mood, slow and calm, very gentle.")
music("music_dungeon", "music/dungeon.mp3", 150, STYLE +
      "Dark underground dungeon: deep ominous low brass and contrabass drones, slow distant timpani pulses, creeping tremolo strings, metallic scrapes, dread and suspense, slow.")
music("music_corridor", "music/forbidden_corridor.mp3", 120, STYLE +
      "Forbidden corridor suspense: creeping staccato low strings, heartbeat-like soft drum pulse, eerie high violin harmonics, building tension, something huge lurks nearby, slow and menacing.")
music("music_combat", "music/combat.mp3", 120, STYLE +
      "Battle music for fighting magical creatures: driving staccato strings, bold brass stabs, pounding orchestral percussion, urgent and heroic, fast tempo 140 bpm, consistent energy throughout, loopable.", gain=-12.0, loop=True)
music("music_boss", "music/boss.mp3", 150, STYLE +
      "Epic boss battle: massive dark choir chanting without words, thundering taiko and timpani, aggressive brass, fast frantic strings, dramatic and overwhelming, 150 bpm, consistent intensity, loopable.", gain=-11.0, loop=True)
music("music_flight", "music/flight.mp3", 120, STYLE +
      "Soaring broomstick flight over castle grounds: uplifting sweeping strings, soaring french horn melody, glittering celesta and harp runs, exhilarating and free, moderate-fast tempo, joyful.")
music("stinger_victory", "music/stinger_victory.mp3", 8, STYLE +
      "Short victory fanfare stinger: triumphant brass and strings flourish ending on a bright major chord, 8 seconds.", gain=-9.0)
music("stinger_death", "music/stinger_death.mp3", 8, STYLE +
      "Short defeat stinger: sorrowful low strings and a mournful horn falling to a dark minor chord, fading, 8 seconds.", gain=-9.0)
music("stinger_boss", "music/stinger_boss.mp3", 6, STYLE +
      "Short boss appearance stinger: sudden ominous brass blast with deep drum hit and choir swell, dread, 6 seconds.", gain=-8.0)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "audio_spec.json")
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    json.dump({"_comment": __doc__.strip().splitlines()[0],
               "sfx_model": "fal-ai/elevenlabs/sound-effects/v2", "music_model": "elevenlabs/music/v2.5",
               "prompt_influence": 0.55, "sounds": {**SFX, **MUSIC}}, fh, indent=1, ensure_ascii=False)
    fh.write("\n")
print("sfx %d (%.0f s), music %d (%.0f s) -> %s" % (len(SFX), sum(v["seconds"] for v in SFX.values()),
      len(MUSIC), sum(v["seconds"] for v in MUSIC.values()), out))
