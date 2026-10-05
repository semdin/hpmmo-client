extends SceneTree

## Throwaway probe (Phase 14): which Performance monitors this engine build
## actually exposes, so the perf scene reads real constants instead of guessed
## ones. Prints the value of each monitor it can name.

func _initialize() -> void:
	for name in ["TIME_PROCESS", "TIME_PHYSICS_PROCESS", "TIME_NAVIGATION_PROCESS",
			"MEMORY_STATIC", "MEMORY_STATIC_MAX", "OBJECT_COUNT", "OBJECT_RESOURCE_COUNT",
			"OBJECT_NODE_COUNT", "OBJECT_ORPHAN_NODE_COUNT",
			"RENDER_TOTAL_OBJECTS_IN_FRAME", "RENDER_TOTAL_PRIMITIVES_IN_FRAME",
			"RENDER_TOTAL_DRAW_CALLS_IN_FRAME", "RENDER_TEXTURE_MEM_USED", "RENDER_VIDEO_MEM_USED",
			"PHYSICS_3D_ACTIVE_OBJECTS", "PHYSICS_3D_COLLISION_PAIRS", "PHYSICS_3D_ISLAND_COUNT",
			"NAVIGATION_ACTIVE_MAPS", "NAVIGATION_REGION_COUNT", "NAVIGATION_AGENT_COUNT",
			"NAVIGATION_LINK_COUNT", "NAVIGATION_POLYGON_COUNT", "NAVIGATION_EDGE_COUNT",
			"NAVIGATION_OBSTACLE_COUNT"]:
		if Performance.has_method("get_monitor"):
			pass
		print("MONITOR %s = %s" % [name, str(Performance.get_monitor(Performance[name]))])
	quit(0)
