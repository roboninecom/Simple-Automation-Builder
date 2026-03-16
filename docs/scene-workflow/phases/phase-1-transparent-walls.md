# Phase 1 — Semi-transparent Walls

## Goal

Сделать стены полупрозрачными (alpha=0.2), чтобы они обозначали границы комнаты, но не мешали обзору. Коллизии сохраняются — роботы и объекты не проходят сквозь стены.

## Tasks

### 1.1 Изменить `_WALL_COLOR` в `room.py`

Текущее значение:
```python
_WALL_COLOR = "0.95 0.93 0.9 1"  # alpha=1, непрозрачный
```

Новое значение:
```python
_WALL_COLOR = "0.92 0.90 0.87 0.2"  # alpha=0.2, почти прозрачный
```

### 1.2 Разделить collision и visual geom для стен

MuJoCo не поддерживает одновременно прозрачность и коллизии на одном geom (прозрачный geom визуально "мерцает" при столкновениях). Решение: два geom на каждый сегмент стены.

**Visual geom** (то что видит пользователь):
```xml
<geom name="wall_north_solid_vis" type="box" size="..." rgba="0.92 0.90 0.87 0.2"
      contype="0" conaffinity="0" group="1"/>
```

**Collision geom** (невидимый, только физика):
```xml
<geom name="wall_north_solid_col" type="box" size="..." rgba="0 0 0 0"
      contype="1" conaffinity="1" group="3"/>
```

`group="3"` — не рендерится по умолчанию в MuJoCo viewer.

### 1.3 Обновить `_split_wall_segments()` в `room.py`

Каждый сегмент стены теперь генерирует два geom вместо одного:
- `{name}_vis` — полупрозрачный, contype=0
- `{name}_col` — невидимый, contype=1

### 1.4 Обновить тесты

- Тест: каждый сегмент стены создаёт 2 geom (vis + col)
- Тест: vis geom имеет contype=0
- Тест: col geom имеет contype=1 и rgba с alpha=0
- Тест: solid wall → 2 geoms вместо 1

## Checkpoint

```bash
pytest backend/tests/test_room.py -v

# Manual: открыть сцену в MuJoCo viewer
# Стены должны быть едва видны, но объекты не проходят сквозь них
```

## Commit
```
feat(room): semi-transparent walls with separate collision geoms
```
