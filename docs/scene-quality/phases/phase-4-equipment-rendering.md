# Phase 4 — Realistic Equipment Rendering

## Goal

Replace the hardcoded `size="0.2 0.2 0.4"` boxes with properly dimensioned, oriented, and colored equipment bodies. A desk should look like a desk (flat wide surface), a wardrobe like a tall narrow box, a bed like a low wide platform.

## Tasks

### 4.1 Rewrite `_add_existing_equipment()` (`backend/app/services/scene.py`)

Current code (to be replaced):
```python
"type": "box",
"size": "0.2 0.2 0.4",        # hardcoded
"rgba": "0.6 0.4 0.2 1",      # hardcoded
```

New logic — use fields from extended `ExistingEquipment`:

```python
def _add_existing_equipment(worldbody, space):
    for eq in space.existing_equipment:
        dims = eq.dimensions          # (width, depth, height) from Vision
        half = (dims[0]/2, dims[1]/2, dims[2]/2)
        pos_z = _mounting_z(eq)       # floor: dims[2]/2, wall: eq.position[2], ceiling: ceiling - dims[2]/2
        pos = (eq.position[0], eq.position[1], pos_z)
        euler = (0, 0, math.radians(eq.orientation_deg))
        rgba = f"{eq.rgba[0]:.2f} {eq.rgba[1]:.2f} {eq.rgba[2]:.2f} {eq.rgba[3]:.2f}"

        body = SubElement(worldbody, "body", name=eq.name, pos=fmt(pos), euler=fmt(euler))
        SubElement(body, "geom",
            name=f"{eq.name}_geom",
            type=eq.shape,             # "box" or "cylinder"
            size=f"{half[0]} {half[1]} {half[2]}",
            rgba=rgba,
            contype="1", conaffinity="1",
        )
```

### 4.2 Mounting logic

**`_mounting_z(eq: ExistingEquipment, ceiling_m: float) → float`**

- `floor`: Z = height / 2 (center of box sitting on floor)
- `wall`: Z = eq.position[2] (user-specified, e.g., AC unit at 2.2m)
- `ceiling`: Z = ceiling_m - height / 2 (hanging from ceiling)

### 4.3 Composite equipment shapes

Some furniture is better represented as multiple geoms:

**`_add_table_body(worldbody, eq)`** — table = top slab + 4 legs:
- Top: box `(width/2, depth/2, 0.02)` at Z = height
- Legs: 4 × box `(0.025, 0.025, height/2)` at corners

**`_add_bed_body(worldbody, eq)`** — bed = mattress + headboard:
- Mattress: box `(width/2, depth/2, 0.15)` at Z = height - 0.15
- Frame: box `(width/2, depth/2, (height-0.15)/2)` at Z = (height-0.15)/2
- Headboard: box `(width/2, 0.03, 0.3)` at Y = -depth/2, Z = height + 0.15

**`_add_chair_body(worldbody, eq)`** — chair = seat + backrest + base:
- Seat: box `(width/2, depth/2, 0.03)` at Z = 0.45
- Backrest: box `(width/2, 0.03, 0.3)` at Y = -depth/2, Z = 0.6
- Base: cylinder `(0.25, 0.22)` at Z = 0.22

Dispatch by `eq.category`:
```python
_COMPOSITE_BUILDERS = {
    "table": _add_table_body,
    "desk": _add_table_body,
    "bed": _add_bed_body,
    "chair": _add_chair_body,
}
```

Other categories → simple box (as in 4.1).

### 4.4 Fallback dimensions

If Claude Vision fails to provide dimensions (or returns defaults), use category-based fallback:

```python
_DEFAULT_DIMENSIONS = {
    "table": (1.2, 0.6, 0.75),
    "desk": (1.2, 0.6, 0.75),
    "chair": (0.55, 0.55, 0.9),
    "bed": (1.6, 2.0, 0.5),
    "wardrobe": (1.2, 0.6, 2.0),
    "shelf": (0.8, 0.3, 1.8),
    "cabinet": (0.8, 0.4, 0.8),
    "appliance": (0.6, 0.3, 0.3),
    "plant": (0.4, 0.4, 1.0),
    "monitor": (0.6, 0.2, 0.4),
    "printer": (0.4, 0.4, 0.35),
}
```

### 4.5 Color defaults by category

If Claude returns default rgba, use category-based colors:

```python
_DEFAULT_COLORS = {
    "table": (0.35, 0.25, 0.15, 1.0),     # dark wood
    "desk": (0.25, 0.20, 0.15, 1.0),       # dark brown
    "chair": (0.2, 0.2, 0.2, 1.0),         # dark gray
    "bed": (0.75, 0.65, 0.4, 1.0),         # beige/tan
    "wardrobe": (0.15, 0.15, 0.15, 0.7),   # dark glass/metal
    "shelf": (0.6, 0.5, 0.35, 1.0),        # light wood
    "plant": (0.2, 0.5, 0.2, 1.0),         # green
    "appliance": (0.9, 0.9, 0.9, 1.0),     # white
}
```

### 4.6 Tests

- Unit test: `_add_existing_equipment` with dimensioned equipment → geom size matches
- Unit test: composite table → 5 geoms (top + 4 legs)
- Unit test: composite bed → 3 geoms (mattress + frame + headboard)
- Unit test: fallback dimensions for unknown category → uses generic box
- Unit test: floor-mounted Z position = height/2
- Unit test: wall-mounted Z position = specified Z
- Integration test: scene with 5 different equipment types loads in MuJoCo

## Checkpoint

```bash
pytest backend/tests/test_scene.py -v

python -c "
import mujoco
m = mujoco.MjModel.from_xml_path('data/projects/test/scenes/v1.xml')
for i in range(m.ngeom):
    name = mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_GEOM, i)
    size = m.geom_size[i]
    if name and not name.startswith('wall') and not name.startswith('floor'):
        print(f'{name}: size={size}')
"
# Expect: each equipment has unique, realistic dimensions
```

## Commit
```
feat(scene): render existing equipment with real dimensions and colors
```
