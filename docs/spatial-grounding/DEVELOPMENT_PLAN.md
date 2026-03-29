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

---

## Feature Breakdown

Each feature is a self-contained unit with its own tests, validation, and commit.

---

### Feature 1: Export Reconstruction Metadata

**Commit**: `feat(reconstruction): export camera poses and intrinsics from pycolmap`

> Save camera poses, intrinsics, and reconstruction statistics as JSON
> after SfM completes. This data is currently discarded but is required
> for projecting 3D points into image pixel coordinates.

**Goal**: After `reconstruct_scene()`, produce `reconstruction_meta.json` with camera data.

**What to implement**:

1. New function `_export_reconstruction_metadata(reconstruction, output_path)` in `reconstruction.py`:
   - Iterate `reconstruction.cameras` → extract model, width, height, focal_length_x/y, principal_point_x/y
   - Iterate `reconstruction.images` → extract name, camera_id, `cam_from_world().matrix()` (3x4), `projection_center()`, `viewing_direction()`
   - Apply COLMAP→Three.js coordinate transform to projection_center and viewing_direction
   - Save as JSON

2. Call it from `_run_pycolmap_pipeline()` after `_export_pointcloud()` (line 261)

3. Add `metadata_path: Path | None` field to `SceneReconstruction` model in `space.py`

4. Set `metadata_path` when creating `SceneReconstruction` in `reconstruct_scene()`

**Output schema**:
```json
{
  "cameras": {
    "1": {
      "model": "PINHOLE",
      "width": 4032, "height": 3024,
      "focal_length_x": 3456.7, "focal_length_y": 3456.7,
      "principal_point_x": 2016.0, "principal_point_y": 1512.0
    }
  },
  "images": {
    "1": {
      "name": "IMG_001.jpg",
      "camera_id": 1,
      "cam_from_world": [[r00,r01,r02,tx], [r10,r11,r12,ty], [r20,r21,r22,tz]],
      "projection_center": [2.9, -2.1, -1.6],
      "viewing_direction": [0.1, -0.8, 0.2]
    }
  },
  "num_points3D": 4521,
  "num_registered_images": 18
}
```

**Validation step**:
- Unit test: create a mock pycolmap Reconstruction with known camera/image data, verify exported JSON matches
- Unit test: verify coordinate transform is applied to projection_center and viewing_direction
- Unit test: verify `SceneReconstruction.metadata_path` is set and file exists
- Regression: run existing `test_reconstruction.py` — all must pass

**Files changed**: `reconstruction.py`, `space.py`, `test_reconstruction.py`

---

### Feature 2: Photo-to-Image ID Mapping

**Commit**: `feat(reconstruction): save registered image name-to-id mapping`

> Save a mapping from photo filenames to pycolmap image IDs during
> reconstruction. Required to attach correct spatial anchors to
> each photo when sending to Claude Vision.

**Goal**: Know which uploaded photos were successfully registered by SfM and their internal IDs.

**What to implement**:

1. In `_export_reconstruction_metadata()`, include a `registered_images` mapping:
   ```json
   {
     "registered_images": {
       "IMG_001.jpg": 1,
       "IMG_003.jpg": 2,
       "IMG_005.jpg": 3
     },
     "unregistered_images": ["IMG_002.jpg", "IMG_004.jpg"]
   }
   ```

2. Compute by comparing `reconstruction.images[*].name` against the list of input photo filenames

3. Log warning for unregistered images (failed SfM for those views)

**Validation step**:
- Unit test: with N input photos and M < N registered, verify mapping is correct and unregistered list contains the rest
- Unit test: verify all filenames in registered_images are valid (no path prefix, just filename)
- Regression: existing tests pass

**Files changed**: `reconstruction.py`, `test_reconstruction.py`

---

### Feature 3: Spatial Anchor Computation

**Commit**: `feat(spatial-anchors): compute per-image 3D-to-pixel reference points`

> New module that projects reconstructed 3D points into each registered
> photo's pixel space. Produces anchor tables (pixel→world coordinate)
> that Claude Vision will use for precise equipment positioning.

**Goal**: For each registered image, produce a set of ~20-40 spatial anchors mapping pixel coordinates to world coordinates.

**What to implement**:

1. New file `backend/app/services/spatial_anchors.py`

2. Pydantic models:
   ```python
   class SpatialAnchor(BaseModel):
       pixel: tuple[int, int]       # (x, y) in image pixels
       world: tuple[float, float, float]  # (x, y, z) in meters (Three.js convention)
       label: str                   # e.g. "floor_point", "wall_W", "room_corner_SW"

   class ImageAnchors(BaseModel):
       image_name: str
       image_id: int
       camera_position: tuple[float, float, float]
       viewing_direction: tuple[float, float, float]
       anchors: list[SpatialAnchor]
   ```

3. Main function `compute_anchors_for_image(reconstruction, image_id, dims) -> ImageAnchors`:
   - Get all 3D points visible in this image via `point3d.track.elements`
   - For each visible point, project to pixels via `image.project_point(xyz)`
   - Filter: within image bounds, in front of camera (project_point returns None if behind)
   - Apply COLMAP→Three.js transform to world coordinates
   - **Strategic sampling**:
     a. Classify points: floor (z ≈ 0 ±0.3m), wall (near boundary ±0.3m), ceiling (z ≈ ceiling ±0.3m), interior
     b. Pick up to 5 floor points, 3 per wall, 3 ceiling points (spatial diversity via grid)
     c. Divide image into 4×4 grid cells, pick 1 nearest point per cell for coverage
     d. Cap total at 40 anchors
   - Label each anchor by type

4. Function `compute_all_anchors(reconstruction, dims) -> list[ImageAnchors]`:
   - Iterate registered images
   - Call `compute_anchors_for_image()` for each
   - Sort by number of anchors (most informative first)
   - Cap at 10 images max (token budget)

5. Function `add_synthetic_room_corners(image, reconstruction, dims) -> list[SpatialAnchor]`:
   - Project the 8 room bounding box corners into the image
   - Keep only those that land within image bounds and in front of camera
   - Label as `room_corner_SW`, `room_corner_NE`, etc.

**Validation step**:
- Unit test: mock reconstruction with known camera pose + 3D points, verify projected pixel coords match expected values
- Unit test: verify anchors are within image bounds (0..width, 0..height)
- Unit test: verify world coordinates are in Three.js convention (Y-up)
- Unit test: verify sampling produces diverse spatial distribution (not all in one corner)
- Unit test: verify cap at 40 anchors per image and 10 images total
- Unit test: synthetic room corners projected correctly for a simple pinhole camera

**Files**: New `spatial_anchors.py`, new `test_spatial_anchors.py`

---

### Feature 4: Inject Anchors into Vision Request

**Commit**: `feat(vision): include spatial anchors in Claude Vision analysis request`

> Extend the vision analysis request to include per-image spatial anchor
> tables. Claude receives pixel-to-world coordinate mappings alongside
> each photo, enabling precise equipment positioning.

**Goal**: `_format_analysis_request()` includes anchor data; `analyze_scene()` computes and passes anchors.

**What to implement**:

1. Extend `_format_analysis_request(dims, image_anchors=None)` in `vision.py`:
   - If `image_anchors` is provided, append a "Spatial Reference Points" section
   - For each image: camera position, viewing direction, anchor table (pixel→world)
   - Format as markdown table for readability

2. Extend `analyze_scene()` to:
   - Load `reconstruction_meta.json` if it exists
   - Load the pycolmap reconstruction from `sparse/` directory
   - Call `compute_all_anchors()` to generate anchors
   - Pass anchors to `_format_analysis_request()`
   - Reorder `photos` list: registered photos first (matched by filename), unregistered last

3. Graceful fallback: if metadata or sparse dir missing, proceed without anchors (backward compatible)

**Validation step**:
- Unit test: verify `_format_analysis_request()` with anchors produces correct markdown table format
- Unit test: verify `_format_analysis_request()` without anchors produces same output as before (backward compat)
- Unit test: verify anchor text token count is within budget (< 30,000 tokens for 10 images × 40 anchors)
- Integration test: mock `compute_all_anchors()` and verify `analyze_scene()` includes anchor data in the request
- Regression: all existing `test_vision.py` tests pass

**Files changed**: `vision.py`, `test_vision.py`

---

### Feature 5: Update Vision Prompt for Anchor Usage

**Commit**: `feat(vision): update prompt to instruct anchor-based positioning`

> Add instructions to the vision analysis prompt explaining how to use
> spatial anchor points for equipment positioning. Includes interpolation
> method and a worked example.

**Goal**: Claude knows how to use anchor tables to derive precise positions.

**What to implement**:

1. Add new section to `prompts/vision_analysis.md` after "Dimension Estimation Guide":

   ```markdown
   ## Spatial Anchor Points

   When provided, each photo includes a table of spatial anchor points mapping
   pixel locations to real-world 3D coordinates (meters). These are computed
   from the actual 3D reconstruction and are metrically accurate.

   **How to use anchors for positioning**:
   1. Identify which photo shows an object most clearly
   2. Estimate which pixel region the object's base center occupies
   3. Find the 2-4 nearest spatial anchors surrounding that pixel region
   4. Interpolate the world coordinates from those anchors
   5. Use the interpolated result as the object's position

   **Example**: A desk's base center appears near pixel (500, 420).
   Nearby anchors:
   - pixel (450, 400) → world (2.10, 1.30, 0.00)
   - pixel (550, 440) → world (2.50, 1.50, 0.00)
   Interpolated position: approximately (2.30, 1.40, 0.00).

   **Rules**:
   - ALWAYS prefer anchor-derived positions over pure visual estimation
   - If no anchors are near an object, fall back to room-dimension-based estimation
   - Floor-level anchors (z ≈ 0) are most reliable for XY positioning
   - Wall anchors help confirm wall-relative placement of doors/windows
   ```

2. Update the "Guidelines" section:
   - Add: "When spatial anchors are provided, use them as primary position reference"
   - Add: "Report which photo and approximate pixel region you used for each equipment position"

**Validation step**:
- Manual review: prompt reads clearly and gives actionable instructions
- Unit test: `load_prompt("vision_analysis")` loads successfully and contains "Spatial Anchor Points" section
- Regression: existing prompt loading tests pass

**Files changed**: `prompts/vision_analysis.md`, `test_prompts.py`

---

### Feature 6: Point Cloud Position Validation

**Commit**: `feat(vision): validate equipment positions against point cloud density`

> Cross-check Claude's reported equipment positions against the actual
> point cloud. Adjusts confidence scores down when no reconstruction
> points exist near a claimed equipment location.

**Goal**: Catch gross positioning errors by checking if the point cloud supports Claude's claims.

**What to implement**:

1. New function `validate_positions_against_cloud(analysis, pointcloud_path, dims) -> SceneAnalysis` in `vision.py`:
   - Load point cloud from PLY (trimesh)
   - Build a KD-tree from point cloud vertices (scipy.spatial.KDTree or trimesh)
   - For each floor-mounted equipment item:
     a. Define search region: equipment position ± half-dimensions (footprint box)
     b. Query KD-tree for points within search radius
     c. Count nearby points
     d. If count < threshold (e.g., 3 points within 0.5m): reduce confidence by 0.2
     e. If count == 0 within 1.0m: reduce confidence by 0.4 and log warning
   - Return modified analysis with updated confidences

2. Call from `analyze_scene()` after `validate_analysis()`, if pointcloud_path is available

3. Add `pointcloud_path` to `SceneReconstruction` (if not already there) and pass through

**Validation step**:
- Unit test: create synthetic point cloud (numpy array), place equipment at known positions, verify confidence stays high when points exist nearby
- Unit test: place equipment in empty region of cloud, verify confidence is reduced
- Unit test: verify wall-mounted and ceiling-mounted items are skipped (only floor-mounted checked)
- Unit test: verify function is no-op when pointcloud_path is None (backward compat)
- Regression: all existing `test_vision.py` tests pass

**Files changed**: `vision.py`, `test_vision.py`

---

### Feature 7: Integration Wiring & End-to-End Validation

**Commit**: `feat(spatial-grounding): wire full anchor pipeline from reconstruction to vision`

> Connect all spatial grounding components end-to-end: reconstruction
> metadata export → anchor computation → vision prompt injection →
> position validation. Includes integration test.

**Goal**: Full pipeline works: `reconstruct_scene()` → metadata saved → `analyze_scene()` uses anchors → positions validated.

**What to implement**:

1. Verify `reconstruct_scene()` now saves metadata JSON alongside point cloud
2. Verify `analyze_scene()` loads metadata, computes anchors, injects into prompt
3. Verify `validate_positions_against_cloud()` runs after analysis
4. Update `calibrate_and_analyze()` in `capture.py` if needed to pass new data through
5. Ensure backward compatibility: if metadata doesn't exist (old reconstructions), everything still works

**Validation step**:
- Integration test: mock full pipeline (pycolmap reconstruction → metadata → anchors → vision request), verify anchors appear in Claude request payload
- Integration test: verify old projects without metadata still work (no crash, no anchors in request)
- E2E test: add to `test_e2e_pipeline.py` — verify metadata file exists after reconstruction, anchor computation succeeds
- Manual test: run on real photos (if available) and compare position accuracy before/after
- Regression: full test suite passes

**Files changed**: `capture.py`, `vision.py`, `test_e2e_pipeline.py`

---

## Implementation Order

```
Feature 1 ──→ Feature 2 ──→ Feature 3 ──→ Feature 4 ──→ Feature 5 ──→ Feature 7
                                                                          ↑
                                                          Feature 6 ──────┘
```

Features 1-5 are strictly sequential.
Feature 6 can be developed in parallel after Feature 4.
Feature 7 wires everything together and runs final validation.

## Commit Summary

| # | Commit message | Files changed |
|---|---------------|---------------|
| 1 | `feat(reconstruction): export camera poses and intrinsics from pycolmap` | reconstruction.py, space.py, test_reconstruction.py |
| 2 | `feat(reconstruction): save registered image name-to-id mapping` | reconstruction.py, test_reconstruction.py |
| 3 | `feat(spatial-anchors): compute per-image 3D-to-pixel reference points` | spatial_anchors.py, test_spatial_anchors.py |
| 4 | `feat(vision): include spatial anchors in Claude Vision analysis request` | vision.py, test_vision.py |
| 5 | `feat(vision): update prompt to instruct anchor-based positioning` | vision_analysis.md, test_prompts.py |
| 6 | `feat(vision): validate equipment positions against point cloud density` | vision.py, test_vision.py |
| 7 | `feat(spatial-grounding): wire full anchor pipeline from reconstruction to vision` | capture.py, vision.py, test_e2e_pipeline.py |

## Expected Impact

| Metric | Before | After (expected) |
|--------|--------|-------------------|
| Position accuracy | ±0.5-1.0m (guess) | ±0.1-0.3m (anchor-interpolated) |
| Dimension accuracy | ±30-50% (reference guide) | ±15-25% (positions improve downstream) |
| Confidence reliability | Unreliable (self-assessed) | Validated against point cloud |
| User correction needed | Almost always | Occasionally |
