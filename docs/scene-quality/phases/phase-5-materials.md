# Phase 5 — Materials, Lighting, Visual Polish

## Goal

Replace the checker-floor lab aesthetic with realistic interior materials: wood floor, painted walls, proper ambient lighting. The scene should read as "a room" at first glance.

## Tasks

### 5.1 Floor material

Replace `grid_mat` (checker pattern) with a wood-like floor:

```xml
<texture name="wood_floor" type="2d" builtin="flat"
         width="512" height="512" rgb1="0.72 0.58 0.42" rgb2="0.65 0.50 0.35"/>
<material name="floor_mat" texture="wood_floor" texrepeat="8 8" reflectance="0.05"/>
```

Apply to floor geom in room generator (Phase 3).

### 5.2 Wall material

Walls should be a flat matte color — warm white / light gray:

```xml
<material name="wall_mat" rgba="0.95 0.93 0.9 1" reflectance="0.02"/>
```

Apply to all wall geoms. Ceiling gets the same material but slightly lighter.

### 5.3 Improved lighting

Replace single directional light with a multi-light setup:

**Ambient light** — soft overall illumination:
```xml
<light pos="{cx} {cy} {ceiling}" dir="0 0 -1" diffuse="0.6 0.6 0.6" ambient="0.3 0.3 0.3"/>
```

**Fill light** — secondary from the side to reduce harsh shadows:
```xml
<light pos="0 {cy} {ceiling*0.7}" dir="1 0 -0.5" diffuse="0.3 0.3 0.35" specular="0 0 0"/>
```

If windows are present, add a directional "sunlight" from window direction:
```xml
<light pos="{window_x} {window_y} {ceiling*0.8}" dir="{into_room}" diffuse="0.4 0.4 0.35"/>
```

### 5.4 Update `_add_texture_and_material()` (`backend/app/services/scene.py`)

Replace current checker textures with the new material set. Keep backward compatibility: if `generate_room_bodies` is not used (old scenes), the checker floor still works.

### 5.5 Equipment material refinement

For composite equipment bodies (Phase 4), assign different materials to parts:
- Table top → dark wood material
- Table legs → metal material (reflectance=0.2)
- Bed headboard → dark material
- Bed mattress → fabric color from `rgba`

Create a small library of reusable materials:
```python
_MATERIALS = {
    "dark_wood": {"rgba": "0.3 0.22 0.14 1", "reflectance": "0.08"},
    "light_wood": {"rgba": "0.72 0.58 0.42 1", "reflectance": "0.05"},
    "metal": {"rgba": "0.7 0.7 0.72 1", "reflectance": "0.25"},
    "fabric": {"rgba": "0.5 0.5 0.5 1", "reflectance": "0.02"},
    "glass": {"rgba": "0.7 0.8 0.85 0.4", "reflectance": "0.15"},
    "plastic_white": {"rgba": "0.92 0.92 0.92 1", "reflectance": "0.1"},
}
```

### 5.6 MuJoCo rendering settings

Add `<visual>` section for better rendering defaults:

```xml
<visual>
  <headlight ambient="0.15 0.15 0.15" diffuse="0.4 0.4 0.4"/>
  <quality shadowsize="2048"/>
  <map znear="0.01" zfar="50"/>
</visual>
```

### 5.7 Tests

- Unit test: base scene includes wood floor material, wall material
- Unit test: lighting count ≥ 2 (ambient + fill)
- Unit test: window present → sunlight added
- Integration test: scene renders in MuJoCo viewer without warnings

## Checkpoint

```bash
pytest backend/tests/test_scene.py -v

# Manual: open scene in MuJoCo viewer
python -c "
import mujoco, mujoco.viewer
m = mujoco.MjModel.from_xml_path('data/projects/test/scenes/v1.xml')
d = mujoco.MjData(m)
mujoco.viewer.launch(m, d)
"
# Expect: wood floor, white walls, enclosed room, colored furniture
```

## Commit
```
feat(scene): wood floor, wall materials, multi-point lighting
```
