# Phase 1 — Direct Calibration (Room Dimensions Input)

## Goal

Добавить возможность калибровки через прямой ввод размеров комнаты (ширина, длина, высота потолка) вместо указания двух точек на облаке. Это позволяет калибровать без визуализации point cloud.

## Tasks

### 1.1 Новый endpoint `POST /api/capture/{project_id}/calibrate-dimensions`

```python
class DimensionCalibration(BaseModel):
    width_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    ceiling_m: float = Field(gt=0)
```

Логика:
1. Загрузить `reconstruction_meta.json` (некалиброванные размеры)
2. Вычислить scale factor: `scale = real_width / uncalibrated_width`
3. Применить scale к mesh, pointcloud, MJCF (как в `calibrate_scale`)
4. Обновить `dimensions` в reconstruction с новыми значениями
5. Запустить Claude Vision анализ с калиброванными размерами
6. Сохранить `space_model.json`
7. Вернуть `SpaceModel`

Отличие от текущего `calibrate_and_analyze`:
- **Текущий**: два 3D-точки + расстояние → scale factor из евклидова расстояния
- **Новый**: размеры комнаты напрямую → scale factor из соотношения ширин

### 1.2 Альтернативный scale factor

```python
def _compute_scale_from_dimensions(
    uncalibrated: Dimensions,
    real_width: float,
    real_length: float,
    real_ceiling: float,
) -> float:
    """Compute average scale factor from room dimensions.

    Uses average of width and length ratios for robustness.
    """
    scale_w = real_width / uncalibrated.width_m
    scale_l = real_length / uncalibrated.length_m
    return (scale_w + scale_l) / 2
```

### 1.3 Pydantic model `DimensionCalibration`

Добавить в `backend/app/models/space.py`:
```python
class DimensionCalibration(BaseModel):
    width_m: float = Field(gt=0)
    length_m: float = Field(gt=0)
    ceiling_m: float = Field(gt=0, default=2.7)
```

### 1.4 Tests

- Unit test: `_compute_scale_from_dimensions` с known values
- Unit test: endpoint возвращает SpaceModel с корректными dimensions
- Unit test: backward compatibility — старый endpoint с point_a/point_b всё ещё работает

## Checkpoint

```bash
pytest backend/tests/test_reconstruction.py -v

curl -X POST http://localhost:8000/api/capture/{id}/calibrate-dimensions \
  -H "Content-Type: application/json" \
  -d '{"width_m": 4.5, "length_m": 3.8, "ceiling_m": 2.7}'
# → SpaceModel with calibrated dimensions
```

## Commit
```
feat(calibration): direct room dimensions input for scale calibration
```
