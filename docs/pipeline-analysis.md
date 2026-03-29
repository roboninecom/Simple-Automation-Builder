# Robo9 Automate: Pipeline Analysis, Bottlenecks & Recommendations

## 1. Project Goal

**Robo9 Automate** is a platform that enables small businesses to design robotic automation for their workspace **without purchasing equipment**:

```
Room photos -> 3D model -> AI automation plan -> Physics simulation -> Iterative optimization
```

**End deliverable**: a validated robot placement plan with metrics (cycle time, success rate, collisions) that gives the customer confidence before investing in hardware.

---

## 2. Pipeline Stages & Bottlenecks

### Stage 1: Photo Upload & Reconstruction (60% ready)

**What it does**: 10-30 photos -> pycolmap SfM -> sparse point cloud + convex hull mesh

**Bottlenecks**:
- **Sparse cloud** — thousands of points, not hundreds of thousands. The user sees a skeleton, not a room. Hard to understand what the system reconstructed.
- **No photo quality validation** — blurry, dark, or duplicate photos are accepted silently and produce garbage reconstruction.
- **No SfM result validation** — if only 3 out of 30 photos registered, the code treats it as success. Reprojection error, registered camera count, and cloud density are not checked.
- **Convex hull mesh** — produces incorrect geometry for L-shaped, T-shaped, or irregular rooms.

**Impact on real tasks**: user uploads photos of a real workshop -> gets an unintelligible point cloud -> cannot tell whether the system "saw" their space correctly. **Trust is lost at the first step.**

---

### Stage 2: Scale Calibration (50% ready)

**What it does**: user enters real dimensions -> system rescales everything

**Bottlenecks**:
- **Arithmetic averaging of scale factors** (`(scale_w + scale_l) / 2`) — mathematically incorrect for scale coefficients; geometric mean should be used.
- **String-based MJCF scaling** — searches for `scale="1 1 1"` in XML as a string and replaces it. Fragile: any format change silently breaks calibration.
- **No recalibration** — wrong dimensions entered -> start over from scratch.
- **Ceiling height is ignored** in scale factor computation, even though it's part of `DimensionCalibration`.

**Impact**: user enters 6x4m, but the cloud was skewed -> scale is correct on one axis, wrong on the other. Furniture and walls end up in the wrong positions. **All downstream geometry is inaccurate.**

---

### Stage 3: Claude Vision — Scene Analysis (40% ready)

**What it does**: photos -> Claude Vision -> list of equipment with positions, dimensions, zones, doors, windows

**This is the BIGGEST BOTTLENECK of the entire pipeline.** Issues:

- **Claude estimates positions "by eye"** — there is no alignment with the point cloud or mesh. Positions are the model's guess from 2D photos. Accuracy of +/-0.5-1m for an industrial space is catastrophic.
- **Equipment dimensions are also guesses** — the prompt contains a "furniture size guide" with ranges (desk: 1.0-1.6m), but for industrial equipment (CNC machines, shelving, conveyors) there is no guide at all.
- **No ground truth** — the system never cross-checks Vision results against the point cloud. Claude could place a table inside a wall or overlap two objects — this is not validated.
- **Silent clamping corrects data** — if Claude places an object outside room bounds, it is silently moved to the nearest wall. The user is never informed.
- **Only 14 equipment categories** — industrial spaces have dozens of types not covered by the list.
- **Fragile JSON parsing** — 2 retries, no backoff, no distinction between "Claude returned garbage" vs "API failure".

**Impact**: a table is in the center of the workshop, but Claude placed it against the wall. A 2x1.5m machine is recorded as 0.8x0.4m. The "storage" zone is drawn on top of the "assembly" zone. **The entire space map is inaccurate -> robot placement recommendations are meaningless.**

---

### Stage 4: AI Recommendation (65% ready)

**What it does**: scenario description + SpaceModel -> Claude -> robot placement plan, workflow

**Bottlenecks**:
- **Built on Stage 3 data** — if equipment positions are off by 0.5-1m, the robot won't reach its target.
- **No reach validation** — the prompt says "ensure the robot can reach," but Claude cannot compute kinematic reachability. It's just words.
- **No collision check** — Claude places equipment without checking intersections.
- **Workflow targets are abstract coordinates** — "pick at (2.5, 1.0, 0.8)" might be inside a wall, but nobody validates this.

**Impact**: the plan looks convincing on paper but is physically infeasible. This is only discovered at the simulation stage.

---

### Stage 5: MJCF Scene Assembly (70% ready)

**What it does**: SpaceModel + Recommendation -> MJCF XML for MuJoCo

**Bottlenecks**:
- **Rectangular rooms only** — walls are generated as 4 boxes. L-shaped and T-shaped rooms are not supported.
- **Only box and cylinder** for equipment — real equipment is reduced to primitives.
- **Fallback dimensions (0.4x0.4x0.8)** when Claude provides no sizes — unexplained "cubes" appear in the scene.
- **No collision detection during assembly** — objects can intersect in XML. MuJoCo will handle it, but the simulation will be incorrect.

**Impact**: the scene assembles, but does not reflect reality. A robot "stands" inside a table. A conveyor passes through a wall.

---

### Stage 6: Simulation (75% ready)

**What it does**: MuJoCo + scripted controllers -> metrics (success rate, collisions, cycle time)

**Relatively functional**, but:
- **Scripted controllers != real controllers** — the IK controller moves the arm to a point directly; a real robot has trajectory constraints.
- **Metrics depend on quality of previous stages** — if the table is in the wrong place, the success rate is meaningless.
- **No in-browser visualization** — the user cannot see WHAT is happening. Only numbers.

---

### Stage 7: Iterative Optimization (55% ready)

**What it does**: Claude analyzes metrics -> proposes corrections -> reruns simulation

**Bottlenecks**:
- **Optimizes the simulation, not reality** — if source data (positions, dimensions) are inaccurate, iterations improve the "wrong" scene.
- **No exit from dead ends** — if success rate is stuck at 0.94 (threshold 0.95), the loop runs until max_iterations with no progress.
- **Body search by name uses partial match** — `_apply_position_change()` looks for "robot" and may find "robot_2_leg".

---

## 3. Root Causes

All bottlenecks trace back to **three fundamental problems**:

### Root Cause #1: No Accurate Spatial Grounding

Claude Vision guesses positions from photos but **never aligns them with the 3D reconstruction**. The point cloud and Vision analysis are two parallel worlds that never intersect.

```
Point Cloud: knows geometry, does not know semantics
Claude Vision: knows semantics, does not know precise geometry
-> Nobody knows both
```

**This causes ~60% of all problems**: inaccurate positions -> inaccurate plan -> inaccurate simulation -> meaningless metrics.

### Root Cause #2: No Feedback Between Stages

The pipeline is a **linear conveyor with no validation at junctions**:

```
Photos -> [SfM] -> cloud -> [Vision] -> model -> [Planning] -> plan -> [Build] -> MJCF -> [Sim] -> metrics
            |          |           |           |          |           |
         no check   no check   no check   no check   no check   no check
```

An error at any stage silently propagates to the end. There is no single point where the system says: "the data looks wrong, please verify."

### Root Cause #3: The User Cannot Verify or Correct

- The point cloud is too sparse to understand correctness.
- Vision results are not visualized in 3D.
- The recommendation is read-only.
- The simulation is not shown in the browser.
- Metrics are numbers without context.

**The user is a blind passenger** from photos to results.

---

## 4. Recommendations (prioritized by impact)

| # | Problem | Impact | Complexity | Recommendation |
|---|---------|--------|------------|----------------|
| 1 | **Vision is not grounded to point cloud** — equipment positions are guesses | Critical | High | Pass point cloud coordinates into Vision context so Claude can anchor objects to real geometry; or use depth estimation + 2D bbox projection to 3D |
| 2 | **No 3D visualization of Vision results** — user can't see what the system "understood" | Critical | Medium | Render detected equipment as labeled boxes overlaid on the point cloud in SceneViewer3D |
| 3 | **No validation at stage junctions** — errors propagate silently | High | Medium | Add validators between each stage: check registered camera count, equipment-in-bounds, reach feasibility, collision pre-check |
| 4 | **Recommendation is read-only** — user can't fix the plan | High | Low | Expose existing `SceneCorrections` backend capability in the frontend; let users drag/add/remove equipment |
| 5 | **No in-browser simulation visualization** | High | High | Stream MuJoCo frames to browser via WebSocket, or export to Three.js-compatible format |
| 6 | **Rectangular rooms only** | Medium | Medium | Support polygonal room outlines (wall segments from polygon edges) |
| 7 | **Sparse point cloud** — user can't see their space | Medium | Medium | Add dense MVS step (requires NVIDIA GPU) or integrate external photogrammetry API |
| 8 | **Fragile parsing / string-based XML** | Medium | Low | Replace string manipulation with proper XML (lxml/ElementTree) operations; add structured output for Claude responses |

---

## 5. Recommended Fix for Root Cause #1

The spatial grounding problem has three possible approaches:

### Option A: Feed point cloud to Vision (low effort, moderate accuracy)
Pass the point cloud bounding box, centroid, and extremes into the Vision prompt. Claude can then place objects relative to known reference points rather than guessing absolute coordinates.

### Option B: User-assisted placement (medium effort, high accuracy)
After Vision identifies WHAT objects exist (semantics), let the user place them on the point cloud in the 3D editor. This leverages Claude for recognition and the user for precise positioning.

### Option C: Depth estimation + projection (high effort, highest accuracy)
Run monocular depth estimation on each photo, project 2D bounding boxes into 3D using camera poses from SfM, and triangulate object positions. This is fully automatic but requires significant engineering.

**Recommended approach**: Start with **Option B** — it requires the least new technology, gives the highest accuracy, and improves user trust by making them an active participant rather than a blind passenger.

---

## 6. Additional Technical Issues

### Calibration Math
- Scale factor uses arithmetic mean instead of geometric mean
- Ceiling height is ignored in scale computation
- String-based MJCF scale replacement is fragile

### Vision Analysis
- Only 14 equipment categories (insufficient for industrial spaces)
- Confidence scoring has no examples or calibration
- JSON extraction handles only `\`\`\`json` code blocks
- Silent clamping of out-of-bounds positions

### Scene Generation
- Composite builders exist only for table, desk, bed, chair
- No collision detection during assembly
- Deduplication uses incomplete tuple matching
- Fallback dimensions create unexplained primitives

### Iteration Loop
- Partial name matching for body search
- No divergence detection (metrics getting worse)
- No early exit for unrecoverable failures

### Frontend
- No measurement tools in point cloud viewer
- No undo/redo in scene editor
- No progress indicators for long operations
- Simulation results are numbers only — no visual context
- Backend validation warnings are not surfaced to UI

### Testing & Deployment
- Zero API endpoint tests (16 endpoints untested)
- Zero frontend tests
- API key committed to git (security risk)
- Dockerfile missing COPY for knowledge-base/ and prompts/
- No startup health checks
