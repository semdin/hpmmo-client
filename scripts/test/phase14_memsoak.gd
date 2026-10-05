extends Node

## Phase 14 D14-3 resource-class soak recorder (diagnosis, not a fix).
##
## The Phase 14 soak measured ~10 MiB/hour of static memory with zero orphan
## nodes and a flat resource count, so the growth is "allocation, class unknown".
## This recorder wraps the EXISTING soak loop (`phase14_soak.gd`, unmodified: it
## is the same real client, same actions) and adds:
##
##   * a sample every `--sample=` seconds carrying every memory monitor the
##     engine exposes (static, video, texture, object/node/resource/orphan
##     counts) plus, per asset class, how many of the project's known resources
##     are currently alive in the resource cache (`ResourceLoader.has_cached`,
##     which follows Godot's cache: a resource with no references is freed and
##     evicted, so a growing "cached" count is a growing leak);
##   * per-phase accounting: static memory at phase entry vs exit, accumulated
##     by phase name, so the drift can be attributed to casts / fights / mounts /
##     transfers instead of to wall-clock time;
##   * every frame whose delta exceeds `--spike-ms=`, with the phase it happened
##     in - the windowed run's frame data is the D14-2 real-play correlate;
##   * a final summary line with the per-phase table and the spike list.
##
## Usage (client process; server is a separate process):
##   godot --path client res://scenes/test/phase14_memsoak.tscn -- \
##     --port=7791 --seconds=1800 --out=soak.jsonl --mem-out=mem.jsonl

const SOAK = preload("res://scripts/test/phase14_soak.gd")

const ASSET_CLASSES := {
	"vfx_atlas": "res://assets/vfx/atlases",
	"vfx_tex": "res://assets/vfx/tex",
	"vfx_mesh": "res://assets/vfx/meshes",
	"models": "res://assets/models",
	"audio": "res://assets/audio",
	"shader": "res://assets/shaders",
	"scene": "res://scenes",
}

var port := 7791
var duration := 1800.0
var out_path := ""
var mem_out := ""
var sample_seconds := 5.0
var spike_ms := 20.0
var probe_name := "MemSoak"

var _soak: Node = null
var _file: FileAccess = null
var _catalog: Dictionary = {}      # class -> [paths]
var _t := 0.0
var _sample_t := 0.0
var _frames := 0
var _frames_over := {}             # bucket -> count
var _spikes: Array = []
var _last_phase := ""
var _phase_mem0 := 0
var _phase_entry_t := 0.0
var _phase_acc: Dictionary = {}    # phase -> {runs, mem_kib, seconds, casts, kills}
var _phase_casts0 := 0
var _phase_kills0 := 0
var _phase_transfers0 := 0
var _phase_mounts0 := 0
var _cycles := 0
var _done := false


func _ready() -> void:
	_parse_args()
	if mem_out != "":
		_file = FileAccess.open(mem_out, FileAccess.WRITE)
	_catalog = _build_catalog()
	_soak = SOAK.new()
	_soak.name = "Phase14Soak"
	add_child(_soak)
	print("MEMSOAK START catalog=%s" % JSON.stringify(_catalog_sizes()))


func _parse_args() -> void:
	var forwarded := ""
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--mem-out="):
			mem_out = arg.substr(10)
		elif arg.begins_with("--sample="):
			sample_seconds = float(arg.substr(9))
		elif arg.begins_with("--spike-ms="):
			spike_ms = float(arg.substr(11))
		# everything else belongs to the soak loop
		forwarded += arg + " "
	# The soak parses OS.get_cmdline_user_args() itself; nothing to forward.


func _catalog_sizes() -> Dictionary:
	var sizes := {}
	for key in _catalog.keys():
		sizes[key] = (_catalog[key] as Array).size()
	return sizes


## Every resource file under the classes above, discovered once. Absolute paths
## stay stable, so `has_cached` answers "is this class holding more live
## resources than it did an hour ago".
func _build_catalog() -> Dictionary:
	var catalog := {}
	for key in ASSET_CLASSES.keys():
		var paths: Array = []
		_scan_dir(String(ASSET_CLASSES[key]), paths)
		catalog[key] = paths
	return catalog


func _scan_dir(dir_path: String, out: Array) -> void:
	var dir := DirAccess.open(dir_path)
	if dir == null:
		return
	dir.list_dir_begin()
	var name := dir.get_next()
	while name != "":
		if name.begins_with("."):
			name = dir.get_next()
			continue
		var full := dir_path.path_join(name)
		if dir.current_is_dir():
			_scan_dir(full, out)
		elif name.ends_with(".png") or name.ends_with(".glb") or name.ends_with(".gltf") \
				or name.ends_with(".ogg") or name.ends_with(".wav") or name.ends_with(".tscn") \
				or name.ends_with(".tres") or name.ends_with(".gdshader"):
			out.append(full)
		name = dir.get_next()
	dir.list_dir_end()


# ------------------------------------------------------------------ per frame

func _process(delta: float) -> void:
	if _done:
		return
	_t += delta
	_frames += 1
	var ms := delta * 1000.0
	# vsync-on buckets: 16.7 = one interval, 33.3 = one dropped frame, then real
	# hitches. The acceptance's soak ran windowed at the 60 Hz cap, so a 33 ms
	# frame is the smallest visible stutter there.
	var bucket := "<17"
	if ms >= 100.0:
		bucket = ">100"
	elif ms >= 66.0:
		bucket = "66-100"
	elif ms >= 50.0:
		bucket = "50-66"
	elif ms >= 33.0:
		bucket = "33-50"
	elif ms >= 25.0:
		bucket = "25-33"
	elif ms >= 17.0:
		bucket = "17-25"
	_frames_over[bucket] = int(_frames_over.get(bucket, 0)) + 1
	if ms >= spike_ms:
		_spikes.append({"t": snappedf(_t, 0.1), "ms": snappedf(ms, 0.1),
			"phase": String(_soak.get("_phase")), "frame": Engine.get_process_frames()})
	_sample_t += delta
	if _sample_t >= sample_seconds:
		_sample_t = 0.0
		_sample()
	if bool(_soak.get("_done")):
		_finish()


func _phase_counters() -> Array:
	return [int(_soak.get("_casts_accepted")), int(_soak.get("_kills")),
		int(_soak.get("_transfers")), int(_soak.get("_mounts"))]


## Phase accounting: when the soak moves to a new phase, charge the static-memory
## delta and the action counts of the phase that just ended to its name.
func _account_phase() -> void:
	var phase := String(_soak.get("_phase"))
	if phase == _last_phase:
		return
	var now := OS.get_static_memory_usage()
	if _last_phase != "":
		var acc: Dictionary = _phase_acc.get(_last_phase, {"runs": 0, "mem_kib": 0.0,
			"seconds": 0.0, "casts": 0, "kills": 0, "transfers": 0, "mounts": 0})
		acc["runs"] = int(acc["runs"]) + 1
		acc["mem_kib"] = float(acc["mem_kib"]) + (now - _phase_mem0) / 1024.0
		acc["seconds"] = float(acc["seconds"]) + (float(_soak.get("_t")) - _phase_entry_t)
		var c := _phase_counters()
		acc["casts"] = int(acc["casts"]) + (c[0] - _phase_casts0)
		acc["kills"] = int(acc["kills"]) + (c[1] - _phase_kills0)
		acc["transfers"] = int(acc["transfers"]) + (c[2] - _phase_transfers0)
		acc["mounts"] = int(acc["mounts"]) + (c[3] - _phase_mounts0)
		_phase_acc[_last_phase] = acc
		if _last_phase == "walk_back":
			_cycles += 1
	var c2 := _phase_counters()
	_phase_casts0 = c2[0]
	_phase_kills0 = c2[1]
	_phase_transfers0 = c2[2]
	_phase_mounts0 = c2[3]
	_phase_mem0 = now
	_phase_entry_t = float(_soak.get("_t"))
	_last_phase = phase


# ------------------------------------------------------------------ sampling

func _cached_by_class() -> Dictionary:
	var counts := {}
	var alive := 0
	for key in _catalog.keys():
		var n := 0
		for path in _catalog[key]:
			if ResourceLoader.has_cached(path):
				n += 1
		counts[key] = n
		alive += n
	return counts


func _sample() -> void:
	_account_phase()
	var row := {
		"t": snappedf(_t, 0.1),
		"phase": String(_soak.get("_phase")),
		"cycles": _cycles,
		"static_mib": OS.get_static_memory_usage() / 1048576.0,
		"peak_mib": OS.get_static_memory_peak_usage() / 1048576.0,
		"mem_mib": Performance.get_monitor(Performance.MEMORY_STATIC) / 1048576.0,
		"tex_mib": Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED) / 1048576.0,
		"vid_mib": Performance.get_monitor(Performance.RENDER_VIDEO_MEM_USED) / 1048576.0,
		"nodes": Performance.get_monitor(Performance.OBJECT_NODE_COUNT),
		"orphans": Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT),
		"resources": Performance.get_monitor(Performance.OBJECT_RESOURCE_COUNT),
		"objects": Performance.get_monitor(Performance.OBJECT_COUNT),
		"entities": SimAuthority.entities.size(),
		"draw_calls": Performance.get_monitor(Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME),
		"prims": Performance.get_monitor(Performance.RENDER_TOTAL_PRIMITIVES_IN_FRAME),
		"phys_objects": Performance.get_monitor(Performance.PHYSICS_3D_ACTIVE_OBJECTS),
		"fps": Engine.get_frames_per_second(),
		"spikes": _spikes.size(),
		"casts": int(_soak.get("_casts_accepted")),
		"casts_sent": int(_soak.get("_casts_sent")),
		"kills": int(_soak.get("_kills")),
		"respawns": int(_soak.get("_respawns")),
		"transfers": int(_soak.get("_transfers")),
		"mounts": int(_soak.get("_mounts")),
		"deaths": int(_soak.get("_deaths")),
		"rewards": int(_soak.get("_rewards")),
	}
	var cached := _cached_by_class()
	for key in cached.keys():
		row["cached_" + key] = cached[key]
	var text := "MEMSOAK " + JSON.stringify(row)
	print(text)
	if _file != null:
		_file.store_line(JSON.stringify(row))
		_file.flush()


func _finish() -> void:
	if _done:
		return
	_done = true
	_account_phase()
	_sample()
	var summary := {
		"event": "final",
		"seconds": snappedf(_t, 0.1),
		"cycles": _cycles,
		"frames": _frames,
		"frame_hist": _frames_over,
		"spike_ms_threshold": spike_ms,
		"spike_count": _spikes.size(),
		"spikes_top": _spikes.slice(0, 40),
		"phase_accounting": _phase_acc,
		"final_static_mib": OS.get_static_memory_usage() / 1048576.0,
		"final_cached": _cached_by_class(),
		"casts": int(_soak.get("_casts_accepted")),
		"kills": int(_soak.get("_kills")),
		"respawns": int(_soak.get("_respawns")),
		"transfers": int(_soak.get("_transfers")),
		"mounts": int(_soak.get("_mounts")),
	}
	print("MEMSOAK RESULT " + JSON.stringify(summary))
	if _file != null:
		_file.store_line(JSON.stringify(summary))
		_file.close()
