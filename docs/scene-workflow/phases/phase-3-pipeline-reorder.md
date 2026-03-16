# Phase 3 — Pipeline Reorder

## Goal

Вставить новый шаг "Preview" между Calibrate и Plan. Обновить phase tracking на бэкенде и step navigation на фронтенде.

## Tasks

### 3.1 Добавить phase `"preview"` в backend

**`backend/app/models/project.py`** — обновить `PipelinePhase`:

Текущий порядок:
```python
PHASE_ORDER = ["upload", "calibrate", "recommend", "build-scene", "simulate", "iterate"]
```

Новый порядок:
```python
PHASE_ORDER = ["upload", "calibrate", "preview", "recommend", "build-scene", "simulate", "iterate"]
```

**`PipelinePhase` Literal type** — добавить `"preview"`.

### 3.2 Обновить frontend step navigation

**`frontend/src/pages/ProjectWorkflow.tsx`:**

Текущие шаги UI:
```
1. Upload Photos  →  2. Calibrate  →  3. Plan  →  4. Simulate  →  5. Results
```

Новые шаги UI:
```
1. Upload Photos  →  2. Calibrate  →  3. Preview  →  4. Plan  →  5. Simulate  →  6. Results
```

Обновить:
- `STEPS` массив — добавить `{ key: "preview", label: "Preview" }`
- `PHASE_ORDER` — добавить `"preview"` между `"calibrate"` и `"recommend"`
- `STEP_MIN_PHASE` — `"preview"` требует `"calibrate"`, `"recommend"` теперь требует `"preview"`
- `PHASE_TO_STEP` — `"preview"` → `"preview"`
- URL routing — добавить `/projects/:id/preview`

### 3.3 Обновить `useStepNavigation` hook

Добавить:
- `buildPreview(projectId)` — вызывает `POST /api/projects/{id}/build-preview`
- `adjustPreview(projectId, adjustments)` — вызывает `POST /api/projects/{id}/adjust-preview`

### 3.4 Обновить `frontend/src/api/client.ts`

Добавить typed-функции:
```typescript
export async function buildPreviewScene(projectId: string): Promise<{scene_path: string; status: string}>;
export async function getPreviewScene(projectId: string): Promise<Blob>;
export async function adjustPreviewScene(projectId: string, adjustments: SceneAdjustment[]): Promise<SceneWarning[]>;
```

Добавить типы:
```typescript
interface SceneAdjustment {
  body_name: string;
  position?: [number, number, number];
  orientation_deg?: number;
  dimensions?: [number, number, number];
  remove?: boolean;
}
```

### 3.5 Обновить TypeScript types

**`frontend/src/types/index.ts`:**
- Добавить `"preview"` в `PipelinePhase` union type
- Добавить `SceneAdjustment` и `SceneWarning` interfaces

### 3.6 Убрать buildScene из RecommendationView

Текущий `handleConfirm` в `RecommendationView.tsx` вызывает `buildScene()`. Теперь:
- Кнопка "Confirm" только вызывает `advance_phase("recommend")` и переходит к simulate
- `buildScene()` вызывается на шаге simulate (перед запуском симуляции), используя preview-сцену как базу

### 3.7 Tests

- Frontend: `tsc --noEmit` проходит
- Backend: phase order включает `"preview"`
- Navigation: шаг "preview" недоступен без "calibrate"
- Navigation: шаг "recommend" недоступен без "preview"

## Checkpoint

```bash
cd frontend && npx tsc --noEmit
pytest backend/tests/ -v

# Manual: пройти полный flow в UI
# Upload → Calibrate → Preview (новый!) → Plan → Simulate → Results
```

## Commit
```
feat(workflow): add Preview step between Calibrate and Plan
```
