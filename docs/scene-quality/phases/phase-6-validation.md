# Phase 6 — Visual Validation Loop

## Goal

Add a render preview endpoint so the user can see the generated scene before simulation, compare it with the original photos, and request position/dimension adjustments. Close the feedback loop between "what I see in real life" and "what the simulator built."

## Tasks

### 6.1 Scene render endpoint (`backend/app/api/projects.py`)

**`GET /api/projects/{project_id}/render-preview`**
- Loads latest scene MJCF
- Renders 4 camera views using MuJoCo offscreen rendering:
  - Top-down (bird's eye)
  - Front (south wall perspective)
  - Side (east wall perspective)
  - Isometric (45° angle from corner)
- Returns JSON with 4 base64-encoded JPEG images
- Resolution: 800×600 per view

**Rendering logic:**
```python
def render_preview(scene_path: Path) -> list[bytes]:
    model = mujoco.MjModel.from_xml_path(str(scene_path))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    renderer = mujoco.Renderer(model, height=600, width=800)

    views = []
    for camera_config in _PREVIEW_CAMERAS:
        renderer.update_scene(data, camera=camera_config)
        views.append(renderer.render())
    return views
```

### 6.2 Scene adjustment endpoint (`backend/app/api/projects.py`)

**`POST /api/projects/{project_id}/adjust-scene`**

Accepts a list of adjustments:
```json
{
  "adjustments": [
    {
      "body_name": "desk_1",
      "position": [2.5, 1.0, 0.0],
      "orientation_deg": 45,
      "dimensions": [1.4, 0.7, 0.75]
    },
    {
      "body_name": "wardrobe_1",
      "remove": true
    }
  ]
}
```

- Modifies MJCF XML in place: updates body positions, geom sizes, removes bodies
- Saves as new version (`v1_adjusted.xml`)
- Returns updated render preview

### 6.3 Frontend preview component (`frontend/src/components/ScenePreview.tsx`)

- Displays 4 rendered views in a 2×2 grid
- Side-by-side comparison: original photo vs rendered view
- Click on equipment → shows edit form (position, rotation, dimensions)
- "Apply Changes" button → calls adjust endpoint → refreshes preview
- "Looks Good" button → proceeds to simulation

### 6.4 Photo comparison view

Display original room photos next to rendered views so user can visually check:
- Is the desk in the right position?
- Are the dimensions roughly correct?
- Is anything missing or misplaced?

### 6.5 Auto-validation heuristics

**`validate_scene_layout(space: SpaceModel, scene_path: Path) → list[Warning]`**

Check for common issues:
- Equipment overlapping (bounding boxes intersect)
- Equipment outside room bounds
- Floor-mounted equipment floating above floor
- Equipment blocking door openings
- Suspiciously small or large equipment (< 0.1m or > 4m in any dimension)

Return list of warnings to display in frontend.

### 6.6 Tests

- Unit test: render preview produces 4 non-empty images
- Unit test: adjust endpoint modifies MJCF body position correctly
- Unit test: overlap detection catches intersecting boxes
- Unit test: out-of-bounds detection catches equipment outside room
- Integration test: full flow — render → adjust → re-render → different images

## Checkpoint

```bash
pytest backend/tests/test_validation.py -v

# Manual: render preview
curl http://localhost:8000/api/projects/{id}/render-preview | python -m json.tool
# → JSON with 4 base64 images

# Manual: adjust and re-render
curl -X POST http://localhost:8000/api/projects/{id}/adjust-scene \
  -H "Content-Type: application/json" \
  -d '{"adjustments": [{"body_name": "desk_1", "position": [3.0, 1.5, 0.0]}]}'
# → updated preview images
```

## Commit
```
feat(scene): render preview, user adjustments, layout validation
```
