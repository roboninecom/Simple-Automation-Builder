# Scene Editor Merge — Development Plan

## Problem

Текущий workflow имеет 6 шагов, при этом Calibrate (облако точек) и Preview (3D-редактор) — разрозненные шаги. Калибровка происходит на абстрактном облаке точек, что неудобно. Пользователю логичнее калибровать масштаб видя реальную 3D-сцену с мебелью.

## Текущий pipeline (6 шагов)

```
Upload → Calibrate (point cloud) → Preview (3D editor) → Plan → Simulate → Results
```

## Новый pipeline (5 шагов)

```
Upload → Scene Editor → Plan → Simulate → Results
```

**Scene Editor** объединяет Calibrate + Preview в один шаг:
1. Сцена строится сразу из некалиброванных размеров
2. Пользователь задаёт масштаб (ширина/длина комнаты или два клика + расстояние)
3. Сцена перестраивается с правильным масштабом + Claude Vision анализ
4. Пользователь корректирует мебель (drag-and-drop)
5. Ссылка "Point Cloud" → техническая информация в отдельном окне
6. "Looks Good →" → переход к Plan

## Phase Dependency Graph

```
Phase 1  Калибровка без облака точек (прямой ввод размеров комнаты)
   ↓
Phase 2  Объединение Calibrate + Preview в один шаг Scene Editor
   ↓
Phase 3  Облако точек как техническая ссылка в Scene Editor
   ↓
Phase 4  Автоматическая перестройка сцены после калибровки
```

## Phase Summary

| Phase | Deliverable | Checkpoint |
|-------|-------------|------------|
| [Phase 1](./phases/phase-1-direct-calibration.md) | Backend: калибровка по размерам комнаты (без point_a/point_b) | Endpoint принимает width/length/ceiling → перестраивает SpaceModel |
| [Phase 2](./phases/phase-2-merge-steps.md) | Frontend: один шаг "Scene Editor" вместо Calibrate + Preview | UI показывает 5 шагов, scene editor с панелью калибровки |
| [Phase 3](./phases/phase-3-pointcloud-link.md) | Облако точек доступно по ссылке из Scene Editor | Кнопка "View Point Cloud" открывает модальное окно |
| [Phase 4](./phases/phase-4-auto-rebuild.md) | После калибровки сцена автоматически перестраивается | Apply Scale → Claude Vision → rebuild → обновление 3D |

## Что удаляется / меняется

- **Удаляется шаг "calibrate"** из frontend step navigation
- **Удаляется шаг "preview"** из frontend step navigation (оба → "scene-editor")
- **SceneViewer3D** — не удаляется, но перемещается внутрь SceneEditor как вложенный компонент (модальное окно)
- **Phase "calibrate" и "preview"** в backend — заменяются на одну phase "scene-editor"
- **PipelinePhase** — `"calibrate" | "preview"` → `"scene-editor"`
