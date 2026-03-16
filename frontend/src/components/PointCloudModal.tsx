/**
 * Modal dialog showing point cloud from reconstruction as technical reference.
 * @module PointCloudModal
 */

import { useEffect, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import * as THREE from "three";

/** Props for PointCloudModal. */
interface PointCloudModalProps {
  /** Project identifier. */
  projectId: string;
  /** Whether the modal is open. */
  isOpen: boolean;
  /** Called when user closes the modal. */
  onClose: () => void;
}

/**
 * Modal with Three.js point cloud visualization.
 * @param props - Modal props.
 * @returns Modal element or null if closed.
 */
export function PointCloudModal({ projectId, isOpen, onClose }: PointCloudModalProps): React.JSX.Element | null {
  if (!isOpen) return null;

  return (
    <div style={overlayStyle} onClick={onClose}>
      <div style={modalStyle} onClick={e => e.stopPropagation()}>
        <div style={headerStyle}>
          <h3 style={{ margin: 0, fontSize: 14 }}>Point Cloud</h3>
          <button onClick={onClose} style={closeBtnStyle}>Close</button>
        </div>
        <div style={{ flex: 1 }}>
          <Canvas camera={{ position: [0, 3, 5], fov: 50 }}>
            <ambientLight intensity={0.8} />
            <OrbitControls />
            <PointCloudView projectId={projectId} />
            <axesHelper args={[1]} />
          </Canvas>
        </div>
      </div>
    </div>
  );
}

/**
 * Three.js point cloud renderer that loads PLY from backend.
 * @param props - Project ID.
 * @returns Points element.
 */
function PointCloudView({ projectId }: { projectId: string }): React.JSX.Element {
  const pointsRef = useRef<THREE.Points>(null);
  const [geometry, setGeometry] = useState<THREE.BufferGeometry | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load(): Promise<void> {
      try {
        const resp = await fetch(`/api/capture/${projectId}/pointcloud`);
        if (!resp.ok) return;
        const buffer = await resp.arrayBuffer();
        const geo = parsePlyToGeometry(buffer);
        if (!cancelled) setGeometry(geo);
      } catch {
        // Point cloud may not be available
      }
    }

    load();
    return () => { cancelled = true; };
  }, [projectId]);

  if (!geometry) {
    return <></>;
  }

  return (
    <points ref={pointsRef} geometry={geometry}>
      <pointsMaterial size={0.01} vertexColors sizeAttenuation />
    </points>
  );
}

/**
 * Parse binary/ASCII PLY buffer into Three.js BufferGeometry.
 * @param buffer - PLY file contents.
 * @returns BufferGeometry with position and color attributes.
 */
function parsePlyToGeometry(buffer: ArrayBuffer): THREE.BufferGeometry {
  const text = new TextDecoder().decode(buffer.slice(0, 4096));
  const headerEnd = text.indexOf("end_header");
  if (headerEnd < 0) return new THREE.BufferGeometry();

  const header = text.slice(0, headerEnd);
  const vertexMatch = header.match(/element vertex (\d+)/);
  const vertexCount = vertexMatch?.[1] ? parseInt(vertexMatch[1], 10) : 0;
  if (vertexCount === 0) return new THREE.BufferGeometry();

  const headerBytes = new TextEncoder().encode(text.slice(0, headerEnd + "end_header\n".length)).length;
  const isBinary = header.includes("format binary");

  const positions = new Float32Array(vertexCount * 3);
  const colors = new Float32Array(vertexCount * 3);

  if (isBinary) {
    const view = new DataView(buffer, headerBytes);
    const hasColor = header.includes("property uchar red");
    const stride = hasColor ? 15 : 12; // 3 floats + 3 bytes (RGB)

    for (let i = 0; i < vertexCount; i++) {
      const offset = i * stride;
      positions[i * 3] = view.getFloat32(offset, true);
      positions[i * 3 + 1] = view.getFloat32(offset + 8, true); // swap Y/Z for Three.js
      positions[i * 3 + 2] = -view.getFloat32(offset + 4, true);

      if (hasColor) {
        colors[i * 3] = view.getUint8(offset + 12) / 255;
        colors[i * 3 + 1] = view.getUint8(offset + 13) / 255;
        colors[i * 3 + 2] = view.getUint8(offset + 14) / 255;
      } else {
        colors[i * 3] = colors[i * 3 + 1] = colors[i * 3 + 2] = 0.7;
      }
    }
  } else {
    const lines = text.slice(headerEnd + "end_header\n".length).trim().split("\n");
    for (let i = 0; i < Math.min(vertexCount, lines.length); i++) {
      const parts = (lines[i] ?? "").trim().split(/\s+/);
      positions[i * 3] = parseFloat(parts[0] ?? "0");
      positions[i * 3 + 1] = parseFloat(parts[2] ?? "0");
      positions[i * 3 + 2] = -parseFloat(parts[1] ?? "0");

      if (parts.length >= 6) {
        colors[i * 3] = parseInt(parts[3] ?? "180", 10) / 255;
        colors[i * 3 + 1] = parseInt(parts[4] ?? "180", 10) / 255;
        colors[i * 3 + 2] = parseInt(parts[5] ?? "180", 10) / 255;
      } else {
        colors[i * 3] = colors[i * 3 + 1] = colors[i * 3 + 2] = 0.7;
      }
    }
  }

  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  return geo;
}

// ── Styles ──

const overlayStyle: React.CSSProperties = {
  position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
  background: "rgba(0,0,0,0.7)", zIndex: 1000,
  display: "flex", alignItems: "center", justifyContent: "center",
};

const modalStyle: React.CSSProperties = {
  width: "80vw", height: "70vh", background: "#111",
  borderRadius: 12, border: "1px solid #333",
  display: "flex", flexDirection: "column", overflow: "hidden",
};

const headerStyle: React.CSSProperties = {
  display: "flex", justifyContent: "space-between", alignItems: "center",
  padding: "12px 16px", borderBottom: "1px solid #2a2a2a", color: "#ccc",
};

const closeBtnStyle: React.CSSProperties = {
  padding: "4px 12px", borderRadius: 4, border: "1px solid #444",
  background: "#222", color: "#aaa", cursor: "pointer", fontSize: 12,
};
