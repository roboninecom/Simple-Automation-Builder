# Phase 4 — Interactive Scene Editor (Three.js)

## Goal

Создать интерактивный 3D-редактор сцены в браузере на Three.js. Пользователь видит комнату с мебелью, может кликать на объекты, перетаскивать их по осям, вращать, менять размеры и удалять. После утверждения — переход к планированию автоматизации.

## Tasks

### 4.1 Backend: endpoint для scene data в JSON

**`GET /api/projects/{project_id}/scene-data`**

MJCF XML неудобен для Three.js. Endpoint парсит `scenes/preview.xml` и возвращает JSON:

```json
{
  "room": {
    "width": 5.0,
    "length": 4.0,
    "ceiling": 2.8
  },
  "bodies": [
    {
      "name": "desk_1",
      "category": "table",
      "position": [2.0, 1.5, 0.375],
      "euler": [0, 0, 1.5708],
      "geoms": [
        {
          "name": "desk_1_top",
          "type": "box",
          "size": [0.6, 0.3, 0.015],
          "pos": [0, 0, 0.735],
          "rgba": [0.25, 0.2, 0.15, 1.0]
        },
        {
          "name": "desk_1_leg0",
          "type": "box",
          "size": [0.025, 0.025, 0.36],
          "pos": [0.575, 0.275, 0.36],
          "rgba": [0.7, 0.7, 0.72, 1.0]
        }
      ]
    }
  ],
  "walls": [
    {
      "name": "wall_north_solid_vis",
      "type": "box",
      "size": [2.5, 0.05, 1.4],
      "pos": [2.5, 4.0, 1.4],
      "rgba": [0.92, 0.9, 0.87, 0.2]
    }
  ],
  "floor": {
    "size": [2.5, 2.0, 0.02],
    "pos": [2.5, 2.0, 0],
    "rgba": [0.72, 0.58, 0.42, 1.0]
  },
  "doors": [
    {"position": [3.0, 4.0], "width": 0.9, "wall": "north"}
  ],
  "windows": [
    {"position": [0.0, 2.5], "width": 1.2, "wall": "west"}
  ],
  "warnings": []
}
```

**Реализация** (`backend/app/services/scene_export.py` — new):

```python
def export_scene_data(scene_path: Path, space: SpaceModel) -> dict:
    """Parse MJCF XML and return JSON for Three.js editor."""
```

Парсит XML, извлекает body/geom элементы, конвертирует в dict. Пропускает room geometry (floor/wall/ceiling) — они идут отдельно.

### 4.2 Компонент `SceneEditor.tsx` — основной 3D canvas

**`frontend/src/components/SceneEditor.tsx`**

Использует `@react-three/fiber` и `@react-three/drei`:

```tsx
import { Canvas } from "@react-three/fiber";
import { OrbitControls, TransformControls, Grid } from "@react-three/drei";

function SceneEditor({ projectId, onConfirm, onBack }) {
  const [sceneData, setSceneData] = useState<SceneData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<"translate" | "rotate">("translate");
  // ...
  return (
    <div style={{ display: "flex", height: "100%" }}>
      <Canvas camera={{ position: [-2, -2, 4], fov: 50 }}>
        <ambientLight intensity={0.5} />
        <directionalLight position={[5, 5, 5]} />
        <OrbitControls makeDefault />

        <RoomGeometry room={sceneData.room} walls={sceneData.walls}
                      floor={sceneData.floor} />

        {sceneData.bodies.map(body => (
          <EquipmentBody
            key={body.name}
            body={body}
            selected={selected === body.name}
            onClick={() => setSelected(body.name)}
          />
        ))}

        {selected && (
          <TransformControls
            object={selectedRef}
            mode={mode}
            onObjectChange={handleTransform}
          />
        )}

        <Grid infiniteGrid fadeDistance={20} />
      </Canvas>

      <SidePanel
        bodies={sceneData.bodies}
        selected={selected}
        onSelect={setSelected}
        onDelete={handleDelete}
        onUpdate={handleUpdate}
        warnings={sceneData.warnings}
        mode={mode}
        onModeChange={setMode}
      />
    </div>
  );
}
```

### 4.3 Компонент `RoomGeometry` — пол, стены, потолок

```tsx
function RoomGeometry({ room, walls, floor }) {
  return (
    <group>
      {/* Floor */}
      <mesh position={floor.pos}>
        <boxGeometry args={[floor.size[0]*2, floor.size[1]*2, floor.size[2]*2]} />
        <meshStandardMaterial color={rgbaToHex(floor.rgba)} />
      </mesh>

      {/* Walls — semi-transparent */}
      {walls.map(wall => (
        <mesh key={wall.name} position={wall.pos}>
          <boxGeometry args={[wall.size[0]*2, wall.size[1]*2, wall.size[2]*2]} />
          <meshStandardMaterial
            color={rgbaToHex(wall.rgba)}
            transparent opacity={wall.rgba[3]}
          />
        </mesh>
      ))}
    </group>
  );
}
```

### 4.4 Компонент `EquipmentBody` — интерактивный объект

```tsx
function EquipmentBody({ body, selected, onClick }) {
  const groupRef = useRef<THREE.Group>(null);

  return (
    <group
      ref={groupRef}
      position={body.position}
      rotation={body.euler}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
    >
      {body.geoms.map(geom => (
        <mesh key={geom.name} position={geom.pos}>
          {geom.type === "box" ? (
            <boxGeometry args={[geom.size[0]*2, geom.size[1]*2, geom.size[2]*2]} />
          ) : (
            <cylinderGeometry args={[geom.size[0], geom.size[0], geom.size[1]*2]} />
          )}
          <meshStandardMaterial
            color={rgbaToHex(geom.rgba)}
            transparent={geom.rgba[3] < 1}
            opacity={geom.rgba[3]}
            emissive={selected ? "#4488ff" : "#000000"}
            emissiveIntensity={selected ? 0.3 : 0}
          />
        </mesh>
      ))}

      {/* Label above object */}
      {selected && (
        <Html position={[0, 0, maxGeomHeight + 0.2]} center>
          <div className="label">{body.name}</div>
        </Html>
      )}
    </group>
  );
}
```

### 4.5 Компонент `SidePanel` — список + форма + warnings

```
┌─────────────────────────────┐
│ Equipment                    │
│ ─────────────────────────── │
│ ● desk_1 (table)      [✎]  │  ← клик выделяет в 3D
│   wardrobe_1 (wardr.)  [✎]  │
│   bed_1 (bed)          [✎]  │
│   plant_1 (plant)      [✎]  │
│                              │
│ ─── Selected: desk_1 ───── │
│ X: [2.50]  Y: [1.00]        │
│ Rotation: [90°]              │
│ W: [1.20] D: [0.60] H:[0.75]│
│ [Move] [Rotate]              │  ← переключает TransformControls mode
│ [Delete]                     │
│                              │
│ ─── Warnings ────────────── │
│ ⚠ desk_1: overlaps chair_1  │
│ ⚠ plant_1: blocking door    │
│                              │
│ [Rebuild]  [Looks Good →]    │
└─────────────────────────────┘
```

**Двусторонняя синхронизация:**
- Перетаскивание в 3D → обновляет координаты в панели
- Ввод координат в панели → обновляет позицию в 3D
- Оба действия помечают body как "dirty" для отправки на backend

### 4.6 Сохранение изменений

**"Looks Good →"** кнопка:
1. Собирает все изменённые bodies
2. Отправляет `POST /api/projects/{id}/adjust-preview` со списком adjustments
3. Backend обновляет `scenes/preview.xml`
4. Вызывает `advance_phase("preview")`
5. Навигация → шаг Plan

**Auto-save (опционально):**
При каждом перетаскивании — debounced (500ms) отправка изменений на backend. Так preview.xml всегда актуален.

### 4.7 Координатная система: MuJoCo → Three.js

MuJoCo: Y-forward, Z-up
Three.js: Y-up, Z-forward (выход на зрителя)

Конвертация при рендеринге:
```typescript
function mjToThree(pos: [number, number, number]): [number, number, number] {
  return [pos[0], pos[2], -pos[1]];  // X=X, Y=Z, Z=-Y
}
```

**Обратная конвертация при сохранении:**
```typescript
function threeToMj(pos: [number, number, number]): [number, number, number] {
  return [pos[0], -pos[2], pos[1]];  // X=X, Y=-Z, Z=Y
}
```

### 4.8 Интеграция в ProjectWorkflow

```tsx
case "preview":
  return <SceneEditor
    projectId={projectId}
    onConfirm={() => navigateTo("recommend")}
    onBack={() => navigateTo("calibrate")}
  />;
```

### 4.9 Tests

- TypeScript: `tsc --noEmit` проходит
- Unit test: `mjToThree` / `threeToMj` — round-trip identity
- Unit test: `export_scene_data` возвращает корректный JSON из MJCF XML
- Component test: SceneEditor рендерится, Canvas создаётся
- Manual: полный flow — клик на объект → перетаскивание → сохранение → Plan

## Checkpoint

```bash
cd frontend && npx tsc --noEmit
cd frontend && npm run build
pytest backend/tests/test_scene_export.py -v

# Manual:
# 1. Upload → Calibrate → Preview
# 2. Увидеть 3D-сцену: пол, полупрозрачные стены, мебель
# 3. Кликнуть на стол → появляются стрелки TransformControls
# 4. Перетащить стол → координаты в панели обновляются
# 5. Нажать Delete → объект удаляется
# 6. "Looks Good" → Plan
```

## Commit
```
feat(ui): interactive Three.js scene editor with drag-and-drop
```
