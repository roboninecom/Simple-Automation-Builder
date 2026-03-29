# Spatial Grounding: Anchor Vision Analysis to Point Cloud

## Problem Statement

Claude Vision estimates equipment positions "by eye" from 2D photos with no reference to the actual 3D reconstruction. Positions are guesses with +/-0.5-1m error — catastrophic for robot placement planning where 10cm matters.

**Root cause**: The point cloud and Vision analysis are two parallel worlds that never intersect. The point cloud knows geometry but not semantics; Claude Vision knows semantics but not precise geometry.

## Solution Overview

Pass per-image 3D spatial context (projected point cloud annotations) to Claude Vision so it can anchor detected objects to real reconstructed geometry instead of guessing coordinates.

### Key Insight

After pycolmap SfM, we have:
- **3D points** with world coordinates (xyz) and colors
- **Camera poses** for each registered image (world-to-camera transform)
- **Camera intrinsics** (focal length, principal point)
- **Projection method**: `image.project_point(xyz)` maps any 3D point to 2D pixel coordinates

We can project the point cloud into each photo, creating a spatial "overlay" that tells Claude: "this pixel in this photo corresponds to world coordinate (2.3, 1.5, 0.0)."

## Architecture

```
Current:
  Photos + Dimensions (text) ──→ Claude Vision ──→ SceneAnalysis (guessed positions)

Proposed:
  Photos + Dimensions + Spatial Anchors (per-image) ──→ Claude Vision ──→ SceneAnalysis (grounded positions)
```

### What are "Spatial Anchors"?

For each registered photo, we compute a set of reference points projected from the 3D reconstruction:

```
Photo "IMG_001.jpg":
  Spatial anchors (pixel → world coordinate):
    - pixel (320, 480) → world (0.00, 0.00, 0.00)  [floor corner, origin]
    - pixel (640, 240) → world (5.80, 0.00, 2.70)  [wall-ceiling edge]
    - pixel (450, 400) → world (2.10, 1.30, 0.00)  [floor point near desk]
    - pixel (100, 350) → world (0.00, 3.20, 0.90)  [west wall at 0.9m height]
    ...
  Bounding box coverage: floor (0,0)-(5.8, 4.2), ceiling at 2.7m
  Camera position: (2.9, 2.1, 1.6), looking toward north wall
```

This gives Claude a coordinate grid overlaid on each photo — it can now say "the desk is near pixel (450, 400) which maps to world (2.1, 1.3, 0.0)" instead of guessing.

---

## Phased Implementation Plan

### Phase 1: Export Reconstruction Metadata

**Goal**: Save camera poses, intrinsics, and point-image associations from pycolmap reconstruction.

**Changes to `reconstruction.py`**:

```python
def _export_reconstruction_metadata(
    reconstruction: pycolmap.Reconstruction,
    output_path: Path,
) -> None:
    """Export camera poses, intrinsics, and point observations.

    For each registered image, saves:
    - Camera intrinsics (focal length, principal point, image size)
    - Camera extrinsics (world-to-camera transform as 3x4 matrix)
    - Camera position and viewing direction in world coords
    - Image filename

    For each 3D point, saves:
    - World coordinates (in Three.js convention)
    - Which images observe it (image_id + pixel coordinates)
    """
```

**Output**: `reconstruction_meta.json` alongside existing `pointcloud.ply` and `mesh.obj`.

**Data structure**:
```json
{
  "cameras": {
    "1": {
      "model": "PINHOLE",
      "width": 4032,
      "height": 3024,
      "focal_length_x": 3456.7,
      "focal_length_y": 3456.7,
      "principal_point_x": 2016.0,
      "principal_point_y": 1512.0
    }
  },
  "images": {
    "1": {
      "name": "IMG_001.jpg",
      "camera_id": 1,
      "cam_from_world": [[r00,r01,r02,tx],[r10,r11,r12,ty],[r20,r21,r22,tz]],
      "projection_center": [2.9, 2.1, 1.6],
      "viewing_direction": [0.1, 0.8, -0.2]
    }
  },
  "num_points3D": 4521,
  "num_registered_images": 18
}
```

**Estimated effort**: Small. Pure data extraction, no algorithm changes.

**Files changed**: `reconstruction.py`, `space.py` (add path to SceneReconstruction)

---

### Phase 2: Compute Spatial Anchors Per Image

**Goal**: For each registered photo, project a meaningful set of 3D reference points into pixel coordinates.

**New module**: `backend/app/services/spatial_anchors.py`

**Algorithm**:

```
For each registered image:
  1. Get all 3D points visible in this image (via point tracks)
  2. Project each 3D point to pixel coordinates using image.project_point(xyz)
  3. Filter: keep only points within image bounds and in front of camera
  4. Sample strategically:
     a. Floor points (z ≈ 0): anchor the ground plane
     b. Wall points (x ≈ 0, x ≈ width, y ≈ 0, y ≈ length): anchor walls
     c. Ceiling points (z ≈ ceiling): anchor height
     d. Grid sampling: divide image into NxN cells, pick nearest point per cell
  5. Add synthetic anchors from room geometry:
     - Project room corners (0,0,0), (W,0,0), (0,L,0), (W,L,0) etc.
     - Project wall midpoints, floor center
  6. Output: list of (pixel_x, pixel_y, world_x, world_y, world_z, label)
```

**Anchor types**:

| Type | Source | Purpose |
|------|--------|---------|
| `floor_point` | 3D points with z ≈ 0 | Ground plane reference |
| `wall_point` | 3D points near room boundaries | Wall position reference |
| `ceiling_point` | 3D points with z ≈ ceiling | Height reference |
| `room_corner` | Projected room AABB corners | Absolute coordinate frame |
| `grid_sample` | Evenly distributed visible points | Spatial coverage |

**Sampling strategy**: ~20-40 anchors per image (not too many to overwhelm context, enough for spatial coverage). Prioritize diversity of world locations over density.

**Output per image**:
```json
{
  "image_name": "IMG_001.jpg",
  "camera_position": [2.9, 2.1, 1.6],
  "viewing_direction": [0.1, 0.8, -0.2],
  "anchors": [
    {"pixel": [320, 480], "world": [0.0, 0.0, 0.0], "label": "floor_corner_SW"},
    {"pixel": [1200, 300], "world": [5.8, 0.0, 2.7], "label": "ceiling_edge"},
    {"pixel": [700, 450], "world": [2.1, 1.3, 0.0], "label": "floor_point"},
    {"pixel": [150, 380], "world": [0.0, 2.5, 0.9], "label": "wall_point_W"}
  ]
}
```

**Estimated effort**: Medium. Core algorithm is straightforward (pycolmap provides `project_point`), but needs careful sampling and filtering.

**Files**: New `spatial_anchors.py`, tests `test_spatial_anchors.py`

---

### Phase 3: Inject Anchors into Vision Prompt

**Goal**: Modify the Vision analysis prompt and request to include spatial anchors per image.

**Changes to `vision.py`**:

The `_format_analysis_request()` function currently sends only room dimensions. We extend it to include per-image spatial context:

```python
def _format_analysis_request(
    dims: Dimensions,
    image_anchors: list[ImageAnchors] | None = None,
) -> str:
    text = f"Room dimensions from 3D reconstruction:\n..."

    if image_anchors:
        text += "\n## Spatial Reference Points\n\n"
        text += (
            "Each photo has spatial anchor points mapping pixel locations "
            "to real-world 3D coordinates (meters). Use these to determine "
            "precise positions of detected equipment.\n\n"
        )
        for img_anchor in image_anchors:
            text += f"### {img_anchor.image_name}\n"
            text += f"Camera at world ({img_anchor.camera_position}), "
            text += f"looking toward ({img_anchor.viewing_direction})\n"
            text += "| Pixel (x,y) | World (x,y,z) | Label |\n"
            text += "|-------------|---------------|-------|\n"
            for a in img_anchor.anchors:
                text += f"| ({a.pixel[0]}, {a.pixel[1]}) | ({a.world[0]:.2f}, {a.world[1]:.2f}, {a.world[2]:.2f}) | {a.label} |\n"
            text += "\n"

    return text
```

**Changes to `vision_analysis.md` prompt**:

Add a new section explaining how to use spatial anchors:

```markdown
## Spatial Anchor Points

Each photo includes a table of spatial anchor points. These map specific
pixel locations in the photo to real-world 3D coordinates (meters).

**How to use anchors for positioning**:
1. Identify which photo shows an object most clearly
2. Estimate which pixel region the object's base center occupies
3. Find the nearest spatial anchors around that region
4. Interpolate the world coordinates from surrounding anchors
5. Use interpolated coordinates as the object's position

**Example**: If a desk's base center appears near pixel (500, 420), and
nearby anchors are:
- pixel (450, 400) → world (2.1, 1.3, 0.0)
- pixel (550, 440) → world (2.5, 1.5, 0.0)

Then the desk position is approximately (2.3, 1.4, 0.0).

**Important**: Always prefer anchor-derived positions over pure estimation.
Anchors are computed from the actual 3D reconstruction and are metrically
accurate.
```

**Token budget**: ~20-40 anchors per image × ~30 tokens each × 10-20 images = 6,000-24,000 tokens. Well within Claude's 200K context. Can be tuned down by reducing anchor count or number of annotated images.

**Estimated effort**: Small-Medium. Mostly prompt engineering and text formatting.

**Files changed**: `vision.py`, `prompts/vision_analysis.md`

---

### Phase 4: Match Registered Photos to Uploaded Photos

**Goal**: Map pycolmap's internal image IDs back to the user's uploaded photo filenames, so we send the correct anchors with the correct images.

**Challenge**: pycolmap renames/indexes images internally. We need to match `reconstruction.images[id].name` to the actual `Path` objects in `photos: list[Path]`.

**Implementation**: During reconstruction, save a mapping `{image_name: image_id}`. In vision analysis, reorder photos to match registered images and attach the correct anchors.

**Edge case**: Not all uploaded photos may be registered (some may fail SfM). We should:
1. Send registered photos first (with anchors)
2. Optionally send unregistered photos after (without anchors, for additional visual context)
3. Clearly label which photos have anchors

**Estimated effort**: Small.

**Files changed**: `reconstruction.py`, `vision.py`

---

### Phase 5: Validate Grounded Positions Against Point Cloud

**Goal**: Cross-check Claude's output positions against the actual point cloud to catch gross errors.

**New validation step in `vision.py`**:

```python
def _validate_positions_against_cloud(
    analysis: SceneAnalysis,
    point_cloud: np.ndarray,
    dims: Dimensions,
) -> SceneAnalysis:
    """Check equipment positions against point cloud density.

    For each floor-mounted equipment item:
    1. Find nearby points in the cloud (within equipment footprint)
    2. If no points exist near the claimed position, flag low confidence
    3. If point density suggests empty space (corridor), warn

    Does NOT move equipment — only adjusts confidence scores.
    """
```

This provides a feedback signal: if Claude says there's a desk at (2.0, 1.5, 0.0) but no reconstruction points exist there, the confidence should drop.

**Estimated effort**: Medium.

**Files changed**: `vision.py`, `test_vision.py`

---

## Implementation Order & Dependencies

```
Phase 1: Export metadata ──→ Phase 2: Compute anchors ──→ Phase 3: Inject into prompt
                                                              │
Phase 4: Match photos ────────────────────────────────────────┘
                                                              │
                                                        Phase 5: Validate against cloud
```

Phases 1-3 are sequential (each depends on the previous).
Phase 4 can be developed in parallel with Phase 2.
Phase 5 is independent and can be done after Phase 3.

## Estimated Impact

| Metric | Before | After (expected) |
|--------|--------|-------------------|
| Position accuracy | ±0.5-1.0m (guess) | ±0.1-0.3m (anchor-interpolated) |
| Dimension accuracy | ±30-50% (reference guide) | ±15-25% (same, but positions improve downstream) |
| Confidence reliability | Unreliable (self-assessed) | Validated against point cloud |
| User correction needed | Almost always | Occasionally |

## Token Budget Analysis

| Component | Tokens | Notes |
|-----------|--------|-------|
| System prompt (current) | ~1,800 | vision_analysis.md |
| Dimension text (current) | ~400 | Room dimensions + wall refs |
| **Anchor section (new)** | **6,000-24,000** | 20-40 anchors × 10-20 images |
| Images (base64) | ~85,000/image | Not counted as text tokens by Claude |
| **Total text context** | **~8,000-26,000** | Well within 200K limit |

Can be further optimized by:
- Annotating only top-10 most informative images (widest coverage)
- Reducing to 15-20 anchors per image
- Dropping images that cover the same area

## Risks & Mitigations

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Claude ignores anchors | Medium | Strong prompt instructions + few-shot example in prompt |
| Too few visible points per image | Low (SfM only works with good coverage) | Fall back to room-corner projections as synthetic anchors |
| Anchor projection inaccurate due to calibration error | Medium | Anchors are relative to same coordinate system as point cloud — error is consistent |
| Token budget exceeded with many images | Low | Cap annotated images at 10; send rest without anchors |
| Interpolation error from sparse anchors | Medium | Use grid sampling to ensure spatial coverage; 20+ anchors per image |

## Testing Strategy

1. **Unit tests for Phase 1**: Verify metadata export matches reconstruction data
2. **Unit tests for Phase 2**: Verify anchor projection against known camera-point pairs; verify sampling produces good spatial coverage
3. **Integration test for Phase 3**: Mock Claude response to verify anchors are included in request text
4. **Accuracy benchmark (manual)**: Run full pipeline on 2-3 test rooms with known furniture positions; compare with/without anchors
5. **Regression tests**: Ensure existing tests pass (no breaking changes to SceneAnalysis format)
