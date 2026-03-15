# Scene Workflow — Development Plan

## Problem

1. **Сцена создаётся слишком поздно.** Сейчас MJCF-сцена с мебелью строится только после рекомендации автоматизации (шаг "Confirm & Build Scene"). Пользователь не может увидеть и откорректировать расположение мебели, масштаб, границы комнаты до того, как Claude начнёт планировать автоматизацию.

2. **Стены непрозрачные и мешают обзору.** Стены rgba `0.95 0.93 0.9 1` (alpha=1) полностью закрывают вид при повороте камеры.

## Текущий pipeline

```
Upload → Calibrate (point cloud) → Plan (scenario → recommendation → build scene) → Simulate → Results
```

Проблема: сцена создаётся внутри шага Plan, после генерации рекомендации. Пользователь не видит MJCF-сцену до этого момента.

## Новый pipeline

```
Upload → Calibrate → Preview Scene (build + review + adjust) → Plan → Simulate → Results
```

Новый шаг **Preview Scene** вставляется между Calibrate и Plan:
- Автоматически строит MJCF из SpaceModel (комната + существующая мебель, БЕЗ рекомендованного оборудования)
- Показывает 3D-превью сцены
- Пользователь может корректировать расположение и размеры мебели
- Только после подтверждения → переход к планированию автоматизации

## Phase Dependency Graph

```
Phase 1  Semi-transparent walls
   ↓
Phase 2  Preview scene endpoint (room + furniture MJCF without recommendation)
   ↓
Phase 3  Pipeline reorder (new step between calibrate and plan)
   ↓
Phase 4  Scene preview UI (3D viewer + adjustment controls)
```

## Phase Summary

| Phase | Deliverable | Checkpoint |
|-------|-------------|------------|
| [Phase 1](./phases/phase-1-transparent-walls.md) | Стены с alpha=0.2, collision сохранён | MuJoCo viewer: стены видны но не мешают |
| [Phase 2](./phases/phase-2-preview-endpoint.md) | `POST /api/projects/{id}/build-preview` — сцена из SpaceModel без рекомендации | Endpoint возвращает MJCF с комнатой и мебелью |
| [Phase 3](./phases/phase-3-pipeline-reorder.md) | Новый шаг "Preview" в frontend + backend phase tracking | UI показывает 6 шагов, preview перед plan |
| [Phase 4](./phases/phase-4-preview-ui.md) | Интерактивный Three.js редактор: drag-and-drop мебели, rotate, delete | Пользователь перетаскивает мебель в 3D до планирования |

## Что НЕ меняется

- Reconstruction pipeline (pycolmap) — без изменений
- Vision analysis (Claude) — без изменений
- Recommendation logic — без изменений (но теперь получает уже утверждённую сцену)
- Simulation и iteration — без изменений
