# Phase 3 — Point Cloud as Technical Link

## Goal

Облако точек доступно из Scene Editor как техническая информация — кнопка "View Point Cloud" открывает модальное окно с Three.js визуализацией point cloud. Это полезно для проверки качества реконструкции, но не является основным рабочим инструментом.

## Tasks

### 3.1 Компонент `PointCloudModal.tsx`

**`frontend/src/components/PointCloudModal.tsx`**

Модальное окно с:
- Three.js Canvas с point cloud (переиспользует логику из SceneViewer3D)
- OrbitControls для вращения
- Информация: количество точек, bounding box размеры
- Кнопка "Close"
- Затемнение фона

```tsx
interface PointCloudModalProps {
  projectId: string;
  isOpen: boolean;
  onClose: () => void;
}
```

### 3.2 Извлечь point cloud рендеринг из SceneViewer3D

Текущий `SceneViewer3D` содержит:
- PLY загрузку и парсинг
- Point cloud рендеринг через Three.js BufferGeometry
- Калибровочную панель

Извлечь point cloud рендеринг в отдельный компонент `PointCloudView`:
```tsx
function PointCloudView({ projectId }: { projectId: string }): React.JSX.Element
```

Этот компонент используется и в `PointCloudModal`, и (опционально) в старом `SceneViewer3D`.

### 3.3 Добавить кнопку в SceneEditor

В `SidePanel` добавить кнопку "View Point Cloud" под списком оборудования:

```tsx
<button onClick={() => setShowPointCloud(true)} style={btnSecondaryStyle}>
  View Point Cloud
</button>

{showPointCloud && (
  <PointCloudModal
    projectId={projectId}
    isOpen={showPointCloud}
    onClose={() => setShowPointCloud(false)}
  />
)}
```

### 3.4 Tests

- TypeScript: `tsc --noEmit` проходит
- Component test: PointCloudModal рендерится когда isOpen=true
- Manual: Scene Editor → "View Point Cloud" → модальное окно с облаком точек → Close

## Checkpoint

```bash
cd frontend && npx tsc --noEmit
cd frontend && npm run build

# Manual: Scene Editor → "View Point Cloud" → облако точек → Close
```

## Commit
```
feat(ui): point cloud viewer as modal in Scene Editor
```
