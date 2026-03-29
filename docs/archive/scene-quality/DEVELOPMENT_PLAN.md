# Scene Quality — Development Plan

## Problem

The generated MuJoCo scene does not resemble the real room. All furniture becomes identical 40×40×80 cm brown boxes on a checkerboard floor. Walls, doors, windows are absent. The reconstructed mesh (convex hull) is a transparent "bubble" that adds no visual value.

**Root causes identified:**
1. Claude Vision prompt does not request equipment dimensions, orientation, or color
2. `SceneAnalysis` model lacks fields for dimensions and visual properties
3. `scene.py` hardcodes `size="0.2 0.2 0.4"` for all existing equipment
4. Doors and windows from `SpaceModel` are completely ignored in scene generation
5. No parametric walls/ceiling — only a floor plane exists
6. Convex hull mesh is useless as room representation

## Overview

Build order: **data model → vision → room geometry → equipment rendering → materials → validation**.
Each phase produces a testable improvement. The scene progressively becomes more realistic.

### Phase Dependency Graph

```
Phase 1  Extend Data Models (SceneAnalysis, ExistingEquipment)
   ↓
Phase 2  Improve Vision Analysis (prompt + parsing)
   ↓
Phase 3  Parametric Room (walls, floor, ceiling, doors, windows)
   ↓
Phase 4  Realistic Equipment Rendering (dimensions, orientation, color)
   ↓
Phase 5  Materials, Lighting, Visual Polish
   ↓
Phase 6  Visual Validation Loop (render → user confirms → adjust)
```

### Phase Summary

| Phase | Deliverable | Checkpoint |
|-------|-------------|------------|
| [Phase 1](./phases/phase-1-data-models.md) | Extended Pydantic + TS models with equipment dimensions, orientation, color | `pytest` passes, `tsc --noEmit` passes |
| [Phase 2](./phases/phase-2-vision-prompt.md) | Updated Vision prompt, Claude returns full equipment geometry | Vision analysis returns dimensions for each item |
| [Phase 3](./phases/phase-3-parametric-room.md) | Room walls, floor, ceiling with door/window cutouts in MJCF | MuJoCo scene shows enclosed room |
| [Phase 4](./phases/phase-4-equipment-rendering.md) | Equipment rendered with real dimensions, orientation, per-type colors | Desk is desk-shaped, wardrobe is wardrobe-shaped |
| [Phase 5](./phases/phase-5-materials.md) | Wood floor texture, wall color, ambient lighting | Scene looks like an interior, not a lab |
| [Phase 6](./phases/phase-6-validation.md) | Render preview endpoint, user feedback, position adjustment | User can verify and correct placement |

### What Does NOT Change

- pycolmap reconstruction pipeline (Phase 1-2 of init plan) — kept as-is
- Equipment catalog and recommendation module — unchanged
- Simulation physics and controllers — unchanged
- Iteration loop logic — unchanged
