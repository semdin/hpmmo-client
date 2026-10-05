extends Node

## Phase 14 D14-2 attribution helper: a zero-cost frame marker.
##
## Two of these are added to the tree root by `phase14_spike.gd`, one with
## `process_priority = -10000` (runs before every other node's `_process`) and
## one with `+10000` (runs after every other node's). Each appends one
## microsecond timestamp per frame into the probe's arrays, so the probe can
## split a frame into:
##
##   script_us = end - start      time spent inside every node's _process
##   outside_us = frame_delta - script_us
##                                time spent in physics, rendering submission,
##                                GPU sync, and everything that is not _process
##
## Without this split a 120 ms hitch cannot be attributed: script time and
## renderer stalls look identical from a single delta sample.

var probe: Node = null
var role := "start"

func _process(_delta: float) -> void:
	if probe != null and is_instance_valid(probe):
		probe.call("note_marker", role, Time.get_ticks_usec())
