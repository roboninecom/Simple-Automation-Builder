# Phase 3 — Parametric Room Generation

## Goal

Replace the useless convex hull mesh with a proper parametric room: 4 walls, floor, ceiling, with cutouts for doors and windows. The room should feel like an enclosed interior space.

## Tasks

### 3.1 Room geometry generator (`backend/app/services/room.py` — new)

**`generate_room_bodies(dims: Dimensions, doors: list[Door], windows: list[Window]) → list[ET.Element]`**

Generates MuJoCo body elements for:

**Floor:**
- `geom type="box"` at Z=0, size = `(width/2, length/2, 0.02)`
- Material: wood texture (defined in Phase 5, placeholder color for now)

**Ceiling:**
- `geom type="box"` at Z=ceiling_m, size = `(width/2, length/2, 0.02)`
- Semi-transparent (rgba alpha=0.3) so camera can see inside

**Walls (4 sides):**
Each wall is one or more box segments. If a wall has a door or window, split it into segments around the opening.

**`_generate_wall_segments(wall: str, dims, openings) → list[geom]`**
- `wall="north"`: Y=length_m, extends along X-axis
- `wall="south"`: Y=0, extends along X-axis
- `wall="east"`: X=width_m, extends along Y-axis
- `wall="west"`: X=0, extends along Y-axis
- Wall thickness: 0.1m
- Wall height: ceiling_m

For a wall with a door at position X=3.0, width=0.9m, height=2.1m:
```
[left_segment] [door_gap] [right_segment]
                           [top_segment above door]
```

For a wall with a window at position X=2.5, width=1.2m, height=1.2m, sill=0.9m:
```
[left_segment] [window_gap] [right_segment]
               [below_sill]
               [above_window]
```

### 3.2 Update `scene.py` — use room generator

**`_create_base_scene(space: SpaceModel) → ET.Element`**

Replace current logic:
- Remove `_add_floor()` (replaced by room generator floor)
- Remove `_add_room_body()` (convex hull mesh — delete entirely)
- Remove `_include_room_mesh()` (no longer needed)
- Add: call `generate_room_bodies()`, append all returned bodies to worldbody
- Keep: `_add_lighting()`, `_add_texture_and_material()`

### 3.3 Wall collision properties

All wall geoms:
- `contype="1" conaffinity="1"` — robots and objects collide with walls
- `rgba` — light wall color (e.g., `"0.95 0.93 0.9 1"` — warm white)
- Named: `wall_north`, `wall_south_left`, `wall_south_right`, `wall_south_above_door`, etc.

Floor geom:
- `contype="1" conaffinity="1"` — objects land on floor
- Replaces the old checker `grid_mat` floor

### 3.4 Handle edge cases

- Wall with no openings → single box segment
- Wall with multiple doors/windows → sort openings by position, generate segments between each
- Opening wider than wall → clamp to wall width, log warning
- No doors/windows at all → 4 simple box walls

### 3.5 Tests

- Unit test: `generate_room_bodies` with no doors/windows → 4 walls + floor + ceiling = 6 bodies
- Unit test: wall with one door → 3 wall segments (left, right, above)
- Unit test: wall with one window → 4 wall segments (left, right, below sill, above)
- Unit test: wall with door + window → correct number of segments
- Integration test: full room loads in MuJoCo without errors

## Checkpoint

```bash
pytest backend/tests/test_room.py -v

python -c "
import mujoco
m = mujoco.MjModel.from_xml_path('data/projects/test/scenes/v1.xml')
# Expect: walls, floor, ceiling as named geoms
for i in range(m.ngeom):
    name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i)
    if name and ('wall' in name or 'floor' in name or 'ceiling' in name):
        print(name)
"
```

## Commit
```
feat(scene): parametric room with walls, floor, ceiling, door/window cutouts
```
