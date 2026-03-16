/**
 * Interactive Three.js scene editor for previewing and adjusting room layout.
 * @module SceneEditor
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { OrbitControls, TransformControls, Html, Grid } from "@react-three/drei";
import * as THREE from "three";

import {
  adjustPreviewScene,
  calibrateAndBuild,
} from "@/api/client";
import type { SceneBody, SceneData, SceneGeom, SceneAdjustment } from "@/api/client";
import { PointCloudModal } from "@/components/PointCloudModal";

/** Props for the SceneEditor component. */
interface SceneEditorProps {
  /** Project identifier. */
  projectId: string;
  /** Called when user confirms the preview. */
  onConfirm: () => void;
  /** Called when user wants to go back. */
  onBack: () => void;
}

/**
 * Convert MuJoCo position (Y-forward, Z-up) to Three.js (Y-up, Z-forward).
 * @param pos - MuJoCo position [x, y, z].
 * @returns Three.js position [x, z, -y].
 */
function mjToThree(pos: number[]): [number, number, number] {
  return [pos[0] ?? 0, pos[2] ?? 0, -(pos[1] ?? 0)];
}

/**
 * Convert Three.js position back to MuJoCo coordinates.
 * @param pos - Three.js position [x, y, z].
 * @returns MuJoCo position [x, -z, y].
 */
function threeToMj(pos: THREE.Vector3): [number, number, number] {
  return [pos.x, -pos.z, pos.y];
}

/**
 * Convert RGBA array [0-1] to hex color string.
 * @param rgba - Color array.
 * @returns Hex color string.
 */
function rgbaToHex(rgba: number[]): string {
  const r = Math.round((rgba[0] ?? 0.5) * 255);
  const g = Math.round((rgba[1] ?? 0.5) * 255);
  const b = Math.round((rgba[2] ?? 0.5) * 255);
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

/**
 * Interactive Three.js scene editor.
 * @param props - Editor props.
 * @returns Scene editor element.
 */
export function SceneEditor({ projectId, onConfirm, onBack }: SceneEditorProps): React.JSX.Element {
  const [sceneData, setSceneData] = useState<SceneData | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [mode, setMode] = useState<"translate" | "rotate">("translate");
  const [loading, setLoading] = useState(false);
  const [loadingMsg, setLoadingMsg] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState<Map<string, SceneAdjustment>>(new Map());
  const [calibrated, setCalibrated] = useState(false);
  const [roomWidth, setRoomWidth] = useState("4.5");
  const [roomLength, setRoomLength] = useState("3.8");
  const [roomCeiling, setRoomCeiling] = useState("2.7");
  const [showPointCloud, setShowPointCloud] = useState(false);

  const handleCalibrate = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setLoadingMsg("Calibrating & analyzing room with AI...");
      const result = await calibrateAndBuild(projectId, {
        width_m: parseFloat(roomWidth),
        length_m: parseFloat(roomLength),
        ceiling_m: parseFloat(roomCeiling),
      });
      setSceneData(result.scene_data);
      setCalibrated(true);
      setDirty(new Map());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Calibration failed");
    } finally {
      setLoading(false);
      setLoadingMsg("");
    }
  }, [projectId, roomWidth, roomLength, roomCeiling]);

  useEffect(() => {
    const controller = new AbortController();

    async function checkScene(): Promise<void> {
      try {
        const resp = await fetch(`/api/projects/${projectId}/scene-data`, {
          signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (resp.ok) {
          const data = (await resp.json()) as SceneData;
          if (controller.signal.aborted) return;
          setSceneData(data);
          setCalibrated(true);
          setDirty(new Map());
        } else {
          setCalibrated(false);
        }
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setCalibrated(false);
      }
    }

    checkScene();
    return () => controller.abort();
  }, [projectId]);

  const handleBodyMove = useCallback((name: string, worldPos: THREE.Vector3) => {
    if (!sceneData) return;
    const { width, length, ceiling } = sceneData.room;

    // Clamp to room bounds in Three.js space (Y-up, Z = -MuJoCo_Y)
    worldPos.x = Math.max(0, Math.min(worldPos.x, width));
    worldPos.y = Math.max(0.05, Math.min(worldPos.y, ceiling));
    worldPos.z = Math.max(-length, Math.min(worldPos.z, 0));

    const mjPos = threeToMj(worldPos);
    setDirty(prev => {
      const next = new Map(prev);
      next.set(name, { body_name: name, position: mjPos });
      return next;
    });
    setSceneData(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        bodies: prev.bodies.map(b =>
          b.name === name ? { ...b, position: mjPos } : b,
        ),
      };
    });
  }, [sceneData]);

  const handleDelete = useCallback((name: string) => {
    setDirty(prev => {
      const next = new Map(prev);
      next.set(name, { body_name: name, remove: true });
      return next;
    });
    setSceneData(prev => {
      if (!prev) return prev;
      return { ...prev, bodies: prev.bodies.filter(b => b.name !== name) };
    });
    setSelected(null);
  }, []);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent): void {
      if (e.key === "Delete" && selected) {
        handleDelete(selected);
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selected, handleDelete]);

  const handleSaveAndContinue = useCallback(async () => {
    if (dirty.size > 0) {
      try {
        await adjustPreviewScene(projectId, Array.from(dirty.values()));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to save adjustments");
        return;
      }
    }
    onConfirm();
  }, [projectId, dirty, onConfirm]);

  if (loading) {
    return <p style={{ color: "#888", textAlign: "center", padding: 32 }}>{loadingMsg || "Loading..."}</p>;
  }
  if (error) {
    return (
      <div style={{ textAlign: "center", padding: 32 }}>
        <p style={{ color: "#f87171" }}>{error}</p>
        <button onClick={() => { setError(null); setCalibrated(false); }} style={btnStyle}>Retry</button>
      </div>
    );
  }
  if (!calibrated || !sceneData) {
    return (
      <CalibrationPanel
        roomWidth={roomWidth}
        roomLength={roomLength}
        roomCeiling={roomCeiling}
        onWidthChange={setRoomWidth}
        onLengthChange={setRoomLength}
        onCeilingChange={setRoomCeiling}
        onApply={handleCalibrate}
        onBack={onBack}
      />
    );
  }


  const selectedBody = sceneData.bodies.find(b => b.name === selected) ?? null;

  return (
    <div style={{ display: "flex", height: "calc(100vh - 180px)", gap: 0 }}>
      <SceneCanvas
        sceneData={sceneData}
        selected={selected}
        selectedBody={selectedBody}
        mode={mode}
        onSelect={setSelected}
        onBodyMove={handleBodyMove}
        onModeChange={setMode}
      />

      <SidePanel
        bodies={sceneData.bodies}
        selected={selected}
        onSelect={setSelected}
        onDelete={handleDelete}
        onConfirm={handleSaveAndContinue}
        onRebuild={() => { setCalibrated(false); setSceneData(null); }}
        onShowPointCloud={() => setShowPointCloud(true)}
        dirty={dirty.size > 0}
      />

      <PointCloudModal
        projectId={projectId}
        isOpen={showPointCloud}
        onClose={() => setShowPointCloud(false)}
      />
    </div>
  );
}

/**
 * Three.js canvas with room geometry, equipment, and transform controls.
 * @param props - Scene data and interaction callbacks.
 * @returns Canvas with 3D scene.
 */
function SceneCanvas({ sceneData, selected, selectedBody, mode, onSelect, onBodyMove, onModeChange }: {
  sceneData: SceneData;
  selected: string | null;
  selectedBody: SceneBody | null;
  mode: "translate" | "rotate";
  onSelect: (name: string) => void;
  onBodyMove: (name: string, pos: THREE.Vector3) => void;
  onModeChange: (m: "translate" | "rotate") => void;
}): React.JSX.Element {
  return (
    <div style={{ flex: 1, position: "relative" }}>
      <Canvas camera={{ position: [-3, 4, 5], fov: 50 }}>
        <ambientLight intensity={0.5} />
        <directionalLight position={[5, 8, 5]} intensity={0.6} />
        <OrbitControls makeDefault />
        <RoomGeometry walls={sceneData.walls} floor={sceneData.floor} />
        {sceneData.bodies.map(body => (
          <EquipmentBody
            key={body.name}
            body={body}
            selected={selected === body.name}
            onClick={() => onSelect(body.name)}
          />
        ))}
        {selected && (
          <SelectedTransform body={selectedBody} mode={mode} onMove={onBodyMove} roomBounds={sceneData.room} />
        )}
        <Grid
          args={[20, 20]}
          position={[sceneData.room.width / 2, 0.001, -sceneData.room.length / 2]}
          cellSize={0.5} cellColor="#333" sectionSize={1} sectionColor="#555" fadeDistance={15}
        />
        <axesHelper args={[1]} />
      </Canvas>
      <div style={toolbarStyle}>
        <button
          onClick={() => onModeChange("translate")}
          style={{ ...toolBtnStyle, ...(mode === "translate" ? toolBtnActiveStyle : {}) }}
        >Move</button>
        <button
          onClick={() => onModeChange("rotate")}
          style={{ ...toolBtnStyle, ...(mode === "rotate" ? toolBtnActiveStyle : {}) }}
        >Rotate</button>
      </div>
    </div>
  );
}

/**
 * Room geometry — floor, walls.
 * @param props - Room data.
 * @returns Room group element.
 */
function RoomGeometry({ walls, floor }: {
  walls: SceneGeom[];
  floor: SceneGeom;
}): React.JSX.Element {
  return (
    <group>
      {floor.size && (
        <mesh position={mjToThree(floor.pos)}>
          <boxGeometry args={[(floor.size[0] ?? 1) * 2, (floor.size[2] ?? 0.02) * 2, (floor.size[1] ?? 1) * 2]} />
          <meshStandardMaterial color={rgbaToHex(floor.rgba)} />
        </mesh>
      )}
      {walls.map(wall => (
        <mesh key={wall.name} position={mjToThree(wall.pos)}>
          <boxGeometry args={[(wall.size[0] ?? 0.1) * 2, (wall.size[2] ?? 1) * 2, (wall.size[1] ?? 0.1) * 2]} />
          <meshStandardMaterial
            color={rgbaToHex(wall.rgba)}
            transparent
            opacity={wall.rgba[3] ?? 0.2}
            side={THREE.DoubleSide}
          />
        </mesh>
      ))}
    </group>
  );
}

/**
 * Single equipment body with all its geoms.
 * @param props - Body data, selection state, click handler.
 * @returns Equipment group element.
 */
function EquipmentBody({ body, selected, onClick }: {
  body: SceneBody;
  selected: boolean;
  onClick: () => void;
}): React.JSX.Element {
  const groupRef = useRef<THREE.Group>(null);
  const pos = mjToThree(body.position);

  return (
    <group
      ref={groupRef}
      position={pos}
      rotation={[0, -(body.euler[2] ?? 0), 0]}
      onClick={(e) => { e.stopPropagation(); onClick(); }}
      name={body.name}
    >
      {body.geoms.map(geom => (
        <GeomMesh key={geom.name} geom={geom} selected={selected} />
      ))}
      {selected && (
        <Html position={[0, 1.2, 0]} center style={{ pointerEvents: "none" }}>
          <div style={labelStyle}>{body.name}</div>
        </Html>
      )}
    </group>
  );
}

/**
 * Single geom as a Three.js mesh.
 * @param props - Geom data and selection state.
 * @returns Mesh element.
 */
function GeomMesh({ geom, selected }: { geom: SceneGeom; selected: boolean }): React.JSX.Element {
  const pos = mjToThree(geom.pos);
  const color = rgbaToHex(geom.rgba);

  if (geom.type === "cylinder") {
    const radius = geom.size[0] ?? 0.1;
    const halfH = geom.size[1] ?? 0.1;
    return (
      <mesh position={pos}>
        <cylinderGeometry args={[radius, radius, halfH * 2, 16]} />
        <meshStandardMaterial
          color={color}
          emissive={selected ? "#4488ff" : "#000000"}
          emissiveIntensity={selected ? 0.3 : 0}
        />
      </mesh>
    );
  }

  return (
    <mesh position={pos}>
      <boxGeometry args={[(geom.size[0] ?? 0.1) * 2, (geom.size[2] ?? 0.1) * 2, (geom.size[1] ?? 0.1) * 2]} />
      <meshStandardMaterial
        color={color}
        emissive={selected ? "#4488ff" : "#000000"}
        emissiveIntensity={selected ? 0.3 : 0}
      />
    </mesh>
  );
}

/**
 * TransformControls wrapper for the selected body.
 * @param props - Selected body, transform mode, move callback.
 * @returns TransformControls element or null.
 */
function SelectedTransform({ body, mode, onMove, roomBounds }: {
  body: SceneBody | null;
  mode: "translate" | "rotate";
  onMove: (name: string, pos: THREE.Vector3) => void;
  roomBounds: { width: number; length: number; ceiling: number };
}): React.JSX.Element | null {
  const { scene } = useThree();

  if (!body) return null;

  const obj = scene.getObjectByName(body.name);
  if (!obj) return null;

  // Compute max half-extent across all geoms for accurate clamping
  let marginX = 0.1;
  let marginZ = 0.1;
  for (const g of body.geoms) {
    if (g.type === "cylinder") {
      const r = g.size[0] ?? 0.1;
      marginX = Math.max(marginX, r);
      marginZ = Math.max(marginZ, r);
    } else {
      marginX = Math.max(marginX, (g.size[0] ?? 0.1) + Math.abs(g.pos[0] ?? 0));
      marginZ = Math.max(marginZ, (g.size[1] ?? 0.1) + Math.abs(g.pos[1] ?? 0));
    }
  }

  return (
    <TransformControls
      object={obj}
      mode={mode}
      onObjectChange={() => {
        if (obj && mode === "translate") {
          obj.position.x = Math.max(marginX, Math.min(obj.position.x, roomBounds.width - marginX));
          obj.position.y = Math.max(0.05, Math.min(obj.position.y, roomBounds.ceiling));
          obj.position.z = Math.max(-roomBounds.length + marginZ, Math.min(obj.position.z, -marginZ));
          onMove(body.name, obj.position.clone());
        }
      }}
    />
  );
}

/**
 * Side panel with equipment list, properties, and actions.
 * @param props - Panel props.
 * @returns Side panel element.
 */
function SidePanel({ bodies, selected, onSelect, onDelete, onConfirm, onRebuild, onShowPointCloud, dirty }: {
  bodies: SceneBody[];
  selected: string | null;
  onSelect: (name: string | null) => void;
  onDelete: (name: string) => void;
  onConfirm: () => void;
  onShowPointCloud: () => void;
  onRebuild: () => void;
  dirty: boolean;
}): React.JSX.Element {
  const selectedBody = bodies.find(b => b.name === selected);

  return (
    <div style={panelStyle}>
      <h3 style={{ margin: "0 0 12px", fontSize: 14, color: "#ccc" }}>Equipment</h3>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {bodies.map(body => (
          <div
            key={body.name}
            onClick={() => onSelect(body.name)}
            style={{
              ...itemStyle,
              ...(selected === body.name ? itemActiveStyle : {}),
            }}
          >
            <span>{body.name}</span>
            <span style={{ color: "#666", fontSize: 11 }}>{body.category}</span>
          </div>
        ))}
      </div>

      {selectedBody && (
        <SelectedBodyProps body={selectedBody} onDelete={onDelete} />
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
        <button onClick={onShowPointCloud} style={btnSecondaryStyle}>View Point Cloud</button>
        <button onClick={onRebuild} style={btnSecondaryStyle}>Recalibrate</button>
        <button onClick={onConfirm} style={btnPrimaryStyle}>
          {dirty ? "Save & Continue →" : "Looks Good →"}
        </button>
      </div>
    </div>
  );
}

/**
 * Properties panel for the selected equipment body.
 * @param props - Selected body and delete handler.
 * @returns Properties panel element.
 */
function SelectedBodyProps({ body, onDelete }: {
  body: SceneBody;
  onDelete: (name: string) => void;
}): React.JSX.Element {
  return (
    <div style={propsStyle}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>
        {body.name}
      </div>
      <div style={propRowStyle}>
        <span>X:</span> <span>{body.position[0]?.toFixed(2)}</span>
        <span>Y:</span> <span>{body.position[1]?.toFixed(2)}</span>
      </div>
      <div style={propRowStyle}>
        <span>Z:</span> <span>{(body.position[2] ?? 0).toFixed(2)}</span>
        <span>Rot:</span> <span>{((body.euler[2] ?? 0) * 180 / Math.PI).toFixed(0)}°</span>
      </div>
      <button onClick={() => onDelete(body.name)} style={deleteBtnStyle}>
        Delete
      </button>
    </div>
  );
}

/**
 * Calibration panel shown before scene is built.
 * @param props - Calibration panel props.
 * @returns Calibration form element.
 */
function CalibrationPanel({ roomWidth, roomLength, roomCeiling, onWidthChange, onLengthChange, onCeilingChange, onApply, onBack }: {
  roomWidth: string;
  roomLength: string;
  roomCeiling: string;
  onWidthChange: (v: string) => void;
  onLengthChange: (v: string) => void;
  onCeilingChange: (v: string) => void;
  onApply: () => void;
  onBack: () => void;
}): React.JSX.Element {
  return (
    <div style={{ maxWidth: 420, margin: "60px auto", padding: 32 }}>
      <h2 style={{ color: "#ccc", marginBottom: 8 }}>Room Dimensions</h2>
      <p style={{ color: "#888", fontSize: 13, marginBottom: 24 }}>
        Enter your room dimensions to calibrate the scene. AI will detect furniture from photos.
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        <label style={calLabelStyle}>
          <span>Width (m)</span>
          <input type="number" step="0.1" min="0.5" value={roomWidth} onChange={e => onWidthChange(e.target.value)} style={calInputStyle} />
        </label>
        <label style={calLabelStyle}>
          <span>Length (m)</span>
          <input type="number" step="0.1" min="0.5" value={roomLength} onChange={e => onLengthChange(e.target.value)} style={calInputStyle} />
        </label>
        <label style={calLabelStyle}>
          <span>Ceiling (m)</span>
          <input type="number" step="0.1" min="1.0" value={roomCeiling} onChange={e => onCeilingChange(e.target.value)} style={calInputStyle} />
        </label>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 24 }}>
        <button onClick={onBack} style={btnSecondaryStyle}>Back</button>
        <button onClick={onApply} style={{ ...btnPrimaryStyle, flex: 1 }}>
          Apply Scale & Detect Furniture
        </button>
      </div>
    </div>
  );
}

// ── Styles ──

const btnStyle: React.CSSProperties = {
  padding: "8px 16px", borderRadius: 6, border: "1px solid #444",
  background: "#2a2a2a", color: "#fff", cursor: "pointer",
};

const btnPrimaryStyle: React.CSSProperties = {
  ...btnStyle, background: "#1a3a5c", borderColor: "#2a6cb0",
};

const btnSecondaryStyle: React.CSSProperties = {
  ...btnStyle, background: "#1a1a1a", borderColor: "#333",
};

const deleteBtnStyle: React.CSSProperties = {
  ...btnStyle, background: "#3a1a1a", borderColor: "#8b2020", color: "#f87171",
  marginTop: 8, width: "100%",
};

const panelStyle: React.CSSProperties = {
  width: 260, background: "#111", borderLeft: "1px solid #2a2a2a",
  padding: 16, display: "flex", flexDirection: "column",
};

const itemStyle: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
  padding: "6px 8px", borderRadius: 4, cursor: "pointer",
  marginBottom: 2, fontSize: 12, color: "#aaa",
};

const itemActiveStyle: React.CSSProperties = {
  background: "#1a3a5c", color: "#fff",
};

const propsStyle: React.CSSProperties = {
  background: "#1a1a1a", borderRadius: 6, padding: 12,
  marginTop: 12, fontSize: 12, color: "#ccc",
};

const propRowStyle: React.CSSProperties = {
  display: "flex", gap: 8, marginBottom: 4, fontSize: 11, color: "#888",
};

const toolbarStyle: React.CSSProperties = {
  position: "absolute", top: 12, left: 12, display: "flex", gap: 4,
};

const toolBtnStyle: React.CSSProperties = {
  padding: "4px 12px", borderRadius: 4, border: "1px solid #444",
  background: "#222", color: "#aaa", cursor: "pointer", fontSize: 12,
};

const toolBtnActiveStyle: React.CSSProperties = {
  background: "#1a3a5c", borderColor: "#2a6cb0", color: "#fff",
};

const calLabelStyle: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
  fontSize: 14, color: "#ccc",
};

const calInputStyle: React.CSSProperties = {
  width: 100, padding: "6px 10px", borderRadius: 4,
  border: "1px solid #444", background: "#1a1a1a", color: "#fff",
  fontSize: 14, textAlign: "right",
};

const labelStyle: React.CSSProperties = {
  background: "rgba(0,0,0,0.8)", color: "#fff", padding: "2px 8px",
  borderRadius: 4, fontSize: 11, whiteSpace: "nowrap",
};
