# Phase 4 — Auto-rebuild Scene After Calibration

## Goal

После нажатия "Apply Scale" сцена автоматически перестраивается: калибровка → Claude Vision анализ → rebuild preview → обновление 3D-редактора. Пользователь видит плавный переход от некалиброванной пустой комнаты к калиброванной сцене с мебелью.

## Tasks

### 4.1 Цепочка вызовов в SceneEditor

При нажатии "Apply Scale":

```typescript
async function handleApplyScale(width: number, length: number, ceiling: number) {
  setCalibrating(true);
  try {
    // 1. Калибровка + Claude Vision + SpaceModel
    await calibrateDimensions(projectId, { width_m: width, length_m: length, ceiling_m: ceiling });

    // 2. Build preview scene (room + detected furniture)
    await buildPreviewScene(projectId);

    // 3. Load scene data for Three.js
    const data = await getSceneData(projectId);
    setSceneData(data);
    setCalibrated(true);
  } catch (e) {
    setError(e.message);
  } finally {
    setCalibrating(false);
  }
}
```

### 4.2 API client: добавить `calibrateDimensions`

```typescript
export async function calibrateDimensions(
  projectId: string,
  dims: { width_m: number; length_m: number; ceiling_m: number },
): Promise<SpaceModel> {
  return apiFetch(`/capture/${projectId}/calibrate-dimensions`, {
    method: "POST",
    body: JSON.stringify(dims),
  });
}
```

### 4.3 Loading state во время калибровки

Пока цепочка выполняется (5-30 секунд из-за Claude Vision):

```
┌──────────────────────────────────────────────────┐
│                                                  │
│         Calibrating scene...                     │
│         ████████████░░░░░░  60%                  │
│                                                  │
│         ✓ Scale applied                          │
│         ⏳ Analyzing room with AI...             │
│         ○ Building 3D scene                      │
│                                                  │
└──────────────────────────────────────────────────┘
```

Три этапа с визуальным прогрессом:
1. "Applying scale..." → быстро (< 1 сек)
2. "Analyzing room with AI..." → Claude Vision (5-20 сек)
3. "Building 3D scene..." → генерация MJCF (< 1 сек)

### 4.4 Некалиброванная сцена при первом входе

При первом входе в Scene Editor (до калибровки):
- Показать пустую комнату с некалиброванными размерами (стены + пол, без мебели)
- Панель калибровки открыта по умолчанию
- Оборудование не показывается (Claude Vision ещё не запущен)
- Подсказка: "Enter your room dimensions to detect furniture"

После калибровки:
- Сцена перестраивается с мебелью
- Панель калибровки сворачивается (но доступна через "Recalibrate")
- Список оборудования и drag-and-drop активны

### 4.5 Recalibrate flow

Кнопка "Recalibrate" возвращает панель калибровки:
- Пользователь меняет размеры
- "Apply Scale" → полная перестройка (пункт 4.1)
- Все manual adjustments теряются (предупреждение: "This will reset furniture positions")

### 4.6 Backend: объединённый endpoint (опционально)

Для уменьшения количества HTTP-запросов, можно объединить calibrate + build-preview в один endpoint:

**`POST /api/capture/{project_id}/calibrate-and-build`**

```python
@router.post("/{project_id}/calibrate-and-build")
async def calibrate_and_build(project_id: str, dims: DimensionCalibration) -> dict:
    # 1. Calibrate scale
    reconstruction = _load_reconstruction_meta(project_dir)
    calibrated = calibrate_scale_from_dimensions(reconstruction, dims)

    # 2. Claude Vision analysis
    analysis = await analyze_scene(client, photos, calibrated)
    space = build_space_model(calibrated, analysis)
    save_space_model(space)

    # 3. Build preview scene
    preview_path = generate_preview_scene(space, scenes_dir / "preview.xml")

    # 4. Export scene data for Three.js
    scene_data = export_scene_data(preview_path, space)

    advance_phase(project_id, "scene-editor")

    return {
        "space_model": space.model_dump(),
        "scene_data": scene_data,
    }
```

Один запрос → всё что нужно для 3D-редактора. Фронтенд получает scene_data сразу, без дополнительных запросов.

### 4.7 Tests

- Unit test: `calibrate_scale_from_dimensions` корректно масштабирует
- Integration test: `calibrate-and-build` → scene_data содержит bodies
- TypeScript: `tsc --noEmit` проходит
- Manual: ввести размеры → Apply → прогресс-бар → мебель появляется в 3D

## Checkpoint

```bash
pytest backend/tests/ -v
cd frontend && npx tsc --noEmit

# Manual:
# 1. Upload → Scene Editor
# 2. Пустая комната с некалиброванными пропорциями
# 3. Ввести 4.5 × 3.8 × 2.7
# 4. Apply Scale → прогресс → мебель появляется
# 5. Подвинуть стол → Looks Good → Plan
```

## Commit
```
feat(scene-editor): auto-rebuild scene after calibration with progress
```
