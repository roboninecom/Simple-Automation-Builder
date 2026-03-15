# Phase 2 — Merge Calibrate + Preview into Scene Editor

## Goal

Объединить шаги Calibrate и Preview в один шаг "Scene Editor". UI показывает 5 шагов вместо 6. Scene Editor содержит 3D-редактор с панелью калибровки.

## Tasks

### 2.1 Backend: обновить PipelinePhase

**`backend/app/models/project.py`:**

Текущий:
```python
PipelinePhase = Literal[
    "upload", "calibrate", "preview", "recommend", "build-scene", "simulate", "iterate",
]
```

Новый:
```python
PipelinePhase = Literal[
    "upload", "scene-editor", "recommend", "build-scene", "simulate", "iterate",
]
```

Phase `"scene-editor"` заменяет и `"calibrate"`, и `"preview"`.

### 2.2 Backend: обновить `calibrate-dimensions` endpoint

Endpoint `calibrate-dimensions` теперь:
1. Калибрует масштаб
2. Запускает Claude Vision
3. Сохраняет SpaceModel
4. Автоматически строит preview scene (`generate_preview_scene`)
5. Вызывает `advance_phase("scene-editor")`

Это один вызов вместо двух (calibrate + build-preview).

### 2.3 Frontend: обновить шаги

**`ProjectWorkflow.tsx`:**

```typescript
type Step = "upload" | "scene-editor" | "recommend" | "simulate" | "results";

const STEPS = [
  { key: "upload", label: "Upload Photos" },
  { key: "scene-editor", label: "Scene Editor" },
  { key: "recommend", label: "Plan" },
  { key: "simulate", label: "Simulate" },
  { key: "results", label: "Results" },
];

const PHASE_ORDER = ["upload", "scene-editor", "recommend", "build-scene", "simulate", "iterate"];

const STEP_MIN_PHASE = {
  upload: "upload",
  "scene-editor": "upload",
  recommend: "scene-editor",
  simulate: "recommend",
  results: "simulate",
};
```

### 2.4 Frontend: расширить SceneEditor с панелью калибровки

**`SceneEditor.tsx`** — добавить состояние `calibrated: boolean`:

**Некалиброванное состояние** (первый вход):
```
┌──────────────────────────────────────────────────────┐
│                                                      │
│       3D сцена (некалиброванные пропорции)            │
│                                                      │
├────────────────────────┬─────────────────────────────┤
│ Calibration            │                             │
│ ─────────────────────  │                             │
│ Room Width:  [4.5] m   │  Equipment (disabled)       │
│ Room Length: [3.8] m   │  ─────────────────────      │
│ Ceiling:     [2.7] m   │  Calibrate first to see     │
│                        │  detected equipment         │
│ [Apply Scale]          │                             │
│                        │                             │
│                        │  [View Point Cloud]         │
└────────────────────────┴─────────────────────────────┘
```

**После калибровки** (Apply Scale нажата):
```
┌──────────────────────────────────────────────────────┐
│                                                      │
│       3D сцена (калиброванная, с мебелью)             │
│                                                      │
├────────────────────────┬─────────────────────────────┤
│ ✓ Calibrated           │ Equipment                   │
│ 4.5 × 3.8 × 2.7 m     │ ─────────────────────       │
│ [Recalibrate]          │ ● desk_1 (table)      [✎]  │
│                        │   wardrobe_1 (wardr.)  [✎]  │
│ ─── Selected ────────  │   bed_1 (bed)          [✎]  │
│ desk_1                 │                             │
│ X: 2.50  Y: 1.00      │ Warnings                    │
│ [Move] [Rotate]        │ ⚠ desk overlaps chair       │
│ [Delete]               │                             │
│                        │ [View Point Cloud]          │
│ [Looks Good →]         │                             │
└────────────────────────┴─────────────────────────────┘
```

### 2.5 Frontend: обновить `useStepNavigation`

- Удалить `onCalibrationComplete` и `onPreviewComplete`
- Добавить `onSceneEditorComplete` — навигирует к `recommend`
- `onUploadComplete` навигирует к `scene-editor` вместо `calibrate`

### 2.6 Frontend: обновить Dashboard.tsx

Добавить `"scene-editor"` в `PHASE_TO_STEP` и `PHASE_LABELS`.

### 2.7 Frontend: обновить TypeScript types

`PipelinePhase` — заменить `"calibrate" | "preview"` на `"scene-editor"`.

### 2.8 Tests

- TypeScript: `tsc --noEmit` проходит
- Backend: phase order включает `"scene-editor"`, не включает `"calibrate"` и `"preview"`
- Manual: Upload → Scene Editor (калибровка + правка) → Plan

## Checkpoint

```bash
cd frontend && npx tsc --noEmit
pytest backend/tests/ -v

# Manual: полный flow
# 1. Upload фото
# 2. Scene Editor: ввести размеры → Apply Scale → увидеть мебель
# 3. Подвинуть стол → Looks Good → Plan
```

## Commit
```
feat(workflow): merge Calibrate + Preview into single Scene Editor step
```
