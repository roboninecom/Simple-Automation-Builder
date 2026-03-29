# Phase 2 — Preview Scene Endpoint

## Goal

Создать endpoint для построения "preview"-сцены: комната + существующая мебель из SpaceModel, БЕЗ рекомендованного оборудования. Это позволяет пользователю увидеть и скорректировать сцену до начала планирования автоматизации.

## Tasks

### 2.1 Новый endpoint `POST /api/projects/{project_id}/build-preview`

```python
@router.post("/{project_id}/build-preview")
async def build_preview_scene(project_id: str) -> dict:
```

Логика:
1. Загрузить `space_model.json` из проекта
2. Вызвать новую функцию `generate_preview_scene(space, output_path)`
3. Сохранить результат в `scenes/preview.xml`
4. Вызвать `advance_phase(project_id, "preview")`
5. Вернуть `{"scene_path": "scenes/preview.xml", "status": "ok"}`

### 2.2 Новая функция `generate_preview_scene()` в `scene.py`

```python
def generate_preview_scene(
    space: SpaceModel,
    output_path: Path,
) -> Path:
```

Отличия от `generate_mjcf_scene()`:
- **Не принимает** `recommendation`, `model_dirs`, `catalog`
- Создаёт base scene (комната + свет + visual settings)
- Добавляет только `existing_equipment` из `SpaceModel`
- **Не добавляет** новое оборудование, work objects, камеры
- Валидирует через MuJoCo

По сути — это верхняя часть `_create_base_scene()` + `_add_existing_equipment()`, без вызовов `_add_new_equipment()`, `_add_work_objects()`, `_add_cameras()`.

### 2.3 Endpoint для получения scene XML

**`GET /api/projects/{project_id}/preview-scene`**

Отдаёт `scenes/preview.xml` как FileResponse. Frontend сможет использовать его для 3D-визуализации или передать в MuJoCo offscreen renderer.

### 2.4 Endpoint для корректировки preview-сцены

**`POST /api/projects/{project_id}/adjust-preview`**

Использует уже реализованную функцию `adjust_scene()` из `scene_validation.py`:
- Принимает список корректировок (позиция, размеры, удаление)
- Сохраняет скорректированную сцену как `scenes/preview.xml` (перезапись)
- Возвращает результат валидации `validate_scene_layout()`

### 2.5 Обновить `build-scene` endpoint

Текущий `POST /api/projects/{project_id}/build-scene` должен использовать preview-сцену как базу:
- Загрузить `scenes/preview.xml` (утверждённая пользователем комната)
- Добавить к ней рекомендованное оборудование и work objects
- Сохранить как `scenes/v1.xml`

Это гарантирует, что расположение мебели, утверждённое пользователем, сохраняется в финальной сцене.

### 2.6 Tests

- Unit test: `generate_preview_scene` создаёт валидный MJCF
- Unit test: preview-сцена содержит стены, пол, потолок, existing equipment
- Unit test: preview-сцена НЕ содержит recommendation equipment
- API test: `build-preview` → `adjust-preview` → корректировки применены

## Checkpoint

```bash
pytest backend/tests/test_scene.py -v

curl -X POST http://localhost:8000/api/projects/{id}/build-preview
# → {"scene_path": "scenes/preview.xml", "status": "ok"}

curl http://localhost:8000/api/projects/{id}/preview-scene
# → XML content of the preview scene
```

## Commit
```
feat(api): preview scene endpoint — room + furniture without recommendation
```
