# Character motion, first pass

The existing hero now blends idle, walk, run, backward and side motion from
horizontal velocity. Diagonals share poses instead of switching between them.
The blend takes 0.18 seconds; cyclic synchronization keeps the imported clips
in step. Playback cadence follows speed with a bounded 0.55–1.65 multiplier.
Gait uses metres/second rather than the gameplay speed cap, so slowing the
character also changes its stride. Gameplay speed and collision are unchanged.

Air, mounted, death and other authored states use crossfades. Jump ascent and
descent have separate states. Repeated hit/landing one-shots reset their playback
and apply the requested speed to both the clip and its lifetime. Footstep
detection only runs for grounded locomotion and uses local foot height, so
falling and changes in world elevation do not masquerade as foot contacts.

Casting retimes preparation and recovery around the same tick-rounded windup
used by SimAuthority. The upper-body layer reaches full weight before release;
the arm extension and recoil use that release beat too. The final pose blends
out rather than disappearing when sampling stops. A full rolling event history
no longer suppresses release events. Remote characters start their gesture on
cast_started; cast_released does not replay the preparation for the same cast.
This is presentation timing; damage and projectile authority are unchanged.

## Review

From the workspace root:

```powershell
godot --path client res://scenes/test/motion_preview.tscn --windowed
```

Space replays the 12-second sequence. S toggles slow motion; Escape closes.
The preview uses the real player controller on a neutral floor and demonstrates
walking, acceleration, running, turning, stopping, three wand gestures, jumping
and casting while moving. Its walking segment lowers only the preview player's
speed. Production movement values are not changed.

For deterministic frames:

```powershell
godot --path client res://scenes/test/motion_preview.tscn --fixed-fps 60 --windowed --resolution 1280x720 -- --capture
```

PNG frames go to `tools/downloads/motion-preview/`. The first review GIF is
`tools/downloads/motion-preview.gif` (generated review artifact).

## Validation

`tools/run_rig_checks.ps1` runs the 132 rig checks and the new 26 motion
checks. The motion suite measures actual foot/hip pose changes, planted idle,
cadence, repeated hits, playback speed, jump/fall selection, cast sampling,
release events with a full history, and remote cast lifecycle. The 93-check
gameplay suite also passes after the changes.

## Remaining art work

The hero is now the Rigify-rigged body described in `docs/hero-rig.md`; the
imported animation sources were retargeted onto it unchanged. Separately
authored wand gestures, secondary cloth motion and foot locking on uneven
ground still require an art pass. Playback-rate limits reduce sliding but are
not a foot-lock solver. Remote release timing uses the latest replicated tick
and has not been validated under induced network latency in this pass.
