# Phase 2 — Improve Vision Analysis

## Goal

Update the Claude Vision prompt and response parser so that Claude returns equipment dimensions, orientation, color, and mounting type for every detected item. Also improve door/window detection with wall assignment.

## Tasks

### 2.1 Update vision prompt (`prompts/vision_analysis.md`)

Replace the current minimal prompt with a detailed one that asks Claude to estimate:

**For each piece of equipment:**
- `dimensions: [width_m, depth_m, height_m]` — estimated from photo using room dimensions as scale reference
- `orientation_deg` — rotation relative to room X-axis (0 = parallel to width wall)
- `rgba: [r, g, b, a]` — dominant color (normalized 0-1)
- `mounting` — "floor", "wall", or "ceiling"
- `shape` — "box" or "cylinder"

**For doors:**
- `wall` — which wall (north/south/east/west), determined by position relative to room center
- `height_m` — estimated door height

**For windows:**
- `wall` — which wall
- `height_m` — window height
- `sill_height_m` — height from floor to window bottom

Add a **dimension estimation guide** to the prompt:
```
Use room dimensions as reference scale:
- Standard desk: 1.0-1.6m wide, 0.5-0.8m deep, 0.72-0.78m high
- Office chair: 0.5-0.7m wide, 0.5-0.7m deep, 0.8-1.2m high
- Wardrobe: 0.8-2.0m wide, 0.5-0.6m deep, 1.8-2.4m high
- Bed (single): 0.9-1.0m wide, 1.9-2.1m long, 0.4-0.6m high
- Bed (double): 1.4-1.8m wide, 1.9-2.1m long, 0.4-0.6m high
- Standard door: 0.8-0.9m wide, 2.0-2.1m high
- AC unit (wall-mounted): 0.8-1.0m wide, 0.2-0.3m deep, 0.3m high
```

Add **coordinate system clarification**:
```
Wall naming convention (top-down view):
- North wall: Y = length_m (far wall)
- South wall: Y = 0 (near wall / origin side)
- East wall: X = width_m (right wall)
- West wall: X = 0 (left wall)

Equipment orientation:
- 0° = long side parallel to X-axis (width)
- 90° = long side parallel to Y-axis (length)
```

### 2.2 Update output schema in prompt

Replace the current minimal JSON example with the full schema:

```json
{
  "zones": [
    {
      "name": "workspace",
      "polygon": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]],
      "area_m2": 4.0
    }
  ],
  "existing_equipment": [
    {
      "name": "desk_1",
      "category": "table",
      "position": [2.0, 1.5, 0.0],
      "confidence": 0.9,
      "dimensions": [1.2, 0.6, 0.75],
      "orientation_deg": 0,
      "rgba": [0.3, 0.2, 0.15, 1.0],
      "mounting": "floor",
      "shape": "box"
    }
  ],
  "doors": [
    {
      "position": [3.0, 4.5],
      "width_m": 0.9,
      "height_m": 2.1,
      "wall": "north"
    }
  ],
  "windows": [
    {
      "position": [0.0, 2.5],
      "width_m": 1.2,
      "height_m": 1.2,
      "sill_height_m": 0.9,
      "wall": "west"
    }
  ]
}
```

### 2.3 Update `_format_analysis_request()` (`backend/app/services/vision.py`)

Enhance the text portion to include:
- Room dimensions (as before)
- Wall naming reference (north/south/east/west with coordinate mapping)
- Request for dimension estimates using room scale as reference

### 2.4 Update response parser

`_parse_analysis_response()` already uses `SceneAnalysis.model_validate_json()` — no change needed if Phase 1 models have proper defaults. Add a post-validation step:

**`_validate_dimensions(analysis: SceneAnalysis, dims: Dimensions) → SceneAnalysis`**
- Clamp equipment positions to within room bounds
- Clamp equipment dimensions to reasonable ranges (min 0.05m, max = room dimension)
- Ensure floor-mounted equipment has `position[2] = 0`
- Ensure wall-mounted equipment position matches declared wall
- Log warnings for suspicious values

### 2.5 Tests

- Unit test: parse Claude response with full schema → all new fields populated
- Unit test: `_validate_dimensions` clamps out-of-bound values
- Unit test: backward compatibility — old response format (without new fields) still parses with defaults
- Integration test: real Claude Vision call with room photos → response includes dimensions for each item

## Checkpoint

```bash
pytest backend/tests/test_vision.py -v

# Manual: test with real photos
curl -X POST http://localhost:8000/api/capture/{id}/calibrate \
  -H "Content-Type: application/json" \
  -d '{"point_a": [0,0,0], "point_b": [1,0,0], "real_distance_m": 4.5}'
# → SpaceModel with dimensioned equipment, doors with walls, windows with sill heights
```

## Commit
```
feat(vision): Claude Vision returns equipment dimensions, orientation, color
```
