# Phase 1 — Extend Data Models

## Goal

Add fields to `ExistingEquipment` and `SceneAnalysis` so that equipment dimensions, orientation, visual appearance, and mounting type can flow from Claude Vision all the way to scene generation. No business logic changes — only contracts.

## Tasks

### 1.1 Extend `ExistingEquipment` model (`backend/app/models/space.py`)

Current model has only: `name`, `category`, `position`, `confidence`.

Add:
- `dimensions: tuple[float, float, float]` — width, depth, height in meters
- `orientation_deg: float` — rotation around Z-axis (0 = aligned with X)
- `rgba: tuple[float, float, float, float]` — approximate color from photo
- `mounting: Literal["floor", "wall", "ceiling"]` — where the item is attached (default: `"floor"`)
- `shape: Literal["box", "cylinder"]` — geometric primitive (default: `"box"`)

All new fields have sensible defaults for backward compatibility.

### 1.2 Extend `Door` and `Window` models (`backend/app/models/space.py`)

**Door** — add:
- `height_m: float` — door height (default: 2.1)
- `wall: Literal["north", "south", "east", "west"]` — which wall the door is on

**Window** — add:
- `height_m: float` — window height (default: 1.2)
- `sill_height_m: float` — height from floor to bottom of window (default: 0.9)
- `wall: Literal["north", "south", "east", "west"]` — which wall

### 1.3 Update TypeScript types (`frontend/src/types/index.ts`)

Mirror all new fields in the corresponding TS interfaces: `ExistingEquipment`, `Door`, `Window`.

### 1.4 Update existing tests

- Existing test fixtures using `ExistingEquipment`, `Door`, `Window` must still pass (defaults cover them)
- Add new test cases with all fields populated

## Checkpoint

```bash
pytest backend/tests/test_models.py -v
cd frontend && npx tsc --noEmit

python -c "
from backend.app.models.space import ExistingEquipment
eq = ExistingEquipment(
    name='desk', category='table',
    position=(2.0, 1.5, 0.0), confidence=0.9,
    dimensions=(1.2, 0.6, 0.75), orientation_deg=90,
    rgba=(0.3, 0.2, 0.15, 1.0), mounting='floor',
)
print(eq.model_dump_json(indent=2))
"
```

## Commit
```
feat(models): add dimensions, orientation, color to ExistingEquipment
```
