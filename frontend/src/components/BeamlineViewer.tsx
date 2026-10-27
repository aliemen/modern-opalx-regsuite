import { Suspense, useEffect, useMemo } from "react";
import * as THREE from "three";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, GizmoHelper, GizmoViewport } from "@react-three/drei";
import type { BeamlineElement, BeamlineMesh } from "../lib/beamlineMesh";

// Element-type palette mirrors the legend hardcoded in OPALX's
// MeshGenerator (Structure/MeshGenerator.cpp). Indices 0-8 must stay in sync.
const ELEMENT_PALETTE: Array<{ label: string; rgb: [number, number, number] }> = [
  { label: "Other",         rgb: [0.5, 0.5, 0.5] },
  { label: "Dipole",        rgb: [1.0, 0.847, 0.0] },
  { label: "Quadrupole",    rgb: [1.0, 0.0, 0.0] },
  { label: "Sextupole",     rgb: [0.537, 0.745, 0.525] },
  { label: "Octupole",      rgb: [0.5, 0.5, 0.0] },
  { label: "Solenoid",      rgb: [1.0, 138 / 255, 0.0] },
  { label: "RFCavity",      rgb: [1.0, 1.0, 0.0] },
  { label: "TravelingWave", rgb: [0.0, 0.6, 0.0] },
  { label: "Drift",         rgb: [0.0, 0.0, 1.0] },
];

function ElementMesh({ element }: { element: BeamlineElement }) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(element.vertices, 3));
    g.setIndex(element.indices);
    g.computeVertexNormals();
    return g;
  }, [element.vertices, element.indices]);

  // Free GPU buffers on unmount (e.g. when data refetches).
  useEffect(() => () => geometry.dispose(), [geometry]);

  const palette = ELEMENT_PALETTE[element.colorIndex] ?? ELEMENT_PALETTE[0];
  const color = useMemo(() => new THREE.Color(...palette.rgb), [palette.rgb]);

  return (
    <mesh geometry={geometry}>
      <meshStandardMaterial color={color} side={THREE.DoubleSide} />
    </mesh>
  );
}

interface SceneFrame {
  center: [number, number, number];
  span: number;            // largest axis extent
}

function Scene({ data, frame }: { data: BeamlineMesh; frame: SceneFrame }) {
  const gridSize = Math.max(frame.span * 2, 2);

  return (
    <>
      <ambientLight intensity={0.5} />
      <directionalLight position={[1, 1, 1]} intensity={0.6} />
      <directionalLight position={[-1, -1, 0.5]} intensity={0.3} />

      {data.elements.map((e, i) => (
        <ElementMesh key={i} element={e} />
      ))}

      <gridHelper
        args={[gridSize, 10, "#666", "#444"]}
        position={[frame.center[0], frame.center[1], 0]}
      />
      <axesHelper args={[gridSize / 2]} />

      <OrbitControls
        target={frame.center}
        makeDefault
        enableDamping
        dampingFactor={0.1}
      />
      <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
        <GizmoViewport axisColors={["#ff6666", "#66cc66", "#6699ff"]} labelColor="#222" />
      </GizmoHelper>
    </>
  );
}

function ColorLegend({ active }: { active: Set<number> }) {
  if (active.size === 0) return null;
  const entries = ELEMENT_PALETTE
    .map((p, i) => ({ ...p, index: i }))
    .filter((p) => active.has(p.index));
  return (
    <div className="absolute top-2 left-2 bg-surface/90 backdrop-blur border border-border rounded px-2 py-1.5 text-[10px] flex flex-col gap-1 pointer-events-none">
      {entries.map((e) => (
        <div key={e.index} className="flex items-center gap-1.5">
          <span
            className="inline-block w-3 h-3 rounded-sm border border-border/50"
            style={{ backgroundColor: `rgb(${e.rgb.map((c) => Math.round(c * 255)).join(",")})` }}
          />
          <span className="text-muted">{e.label}</span>
        </div>
      ))}
    </div>
  );
}

/** Orbitable three.js view of a validated beamline mesh (see parseBeamlineMesh). */
export function BeamlineViewer({ mesh }: { mesh: BeamlineMesh }) {
  const frame: SceneFrame = useMemo(() => {
    const { min, max } = mesh.bounds;
    const center: [number, number, number] = [
      (min[0] + max[0]) / 2,
      (min[1] + max[1]) / 2,
      (min[2] + max[2]) / 2,
    ];
    const span = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2]) || 1;
    return { center, span };
  }, [mesh]);

  const cameraParams = useMemo(
    () => ({
      position: [
        frame.center[0] + frame.span * 1.5,
        frame.center[1] + frame.span * 1.5,
        frame.center[2] + frame.span * 2.5,
      ] as [number, number, number],
      fov: 45,
      near: frame.span / 1000,
      far: frame.span * 100,
    }),
    [frame]
  );

  const activeColors = useMemo(() => new Set(mesh.elements.map((e) => e.colorIndex)), [mesh]);
  const label = `3D view of the beamline: ${ELEMENT_PALETTE.filter((_, i) => activeColors.has(i))
    .map((p) => p.label)
    .join(", ")}. Drag to rotate, scroll to zoom.`;

  return (
    <div
      role="img"
      aria-label={label}
      className="relative aspect-video max-h-80 w-full rounded border border-border bg-surface overflow-hidden"
    >
      <Canvas camera={cameraParams} dpr={[1, 2]}>
        <Suspense fallback={null}>
          <Scene data={mesh} frame={frame} />
        </Suspense>
      </Canvas>
      <ColorLegend active={activeColors} />
    </div>
  );
}
