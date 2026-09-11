"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { Canvas, useFrame, useThree, type ThreeEvent } from "@react-three/fiber"
import { Html, OrbitControls } from "@react-three/drei"
import type { OrbitControls as OrbitControlsImpl } from "three-stdlib"
import * as THREE from "three"

import { kindHex, kindLabel, nodeRadius } from "@/components/graph/kind-meta"
import type { GraphLink, GraphNode } from "@/lib/api"

const SPHERE_RADIUS = 4.5
const DAMPING = 0.08
const AUTO_SPIN_RAD_PER_SEC = 0.18

/** 给定 N 个节点的 hop 分层与角度：hop=0 在中心（最多 3 个贴近原点），hop=1/2/... 在不同球壳上均匀分布。
 *  使用确定性算法 —— 同一组 nodes 永远得到同一组坐标，旋转只是用户视角。 */
function layoutPositions(nodes: GraphNode[]): Map<string, THREE.Vector3> {
  const out = new Map<string, THREE.Vector3>()
  const anchors = nodes.filter((node) => node.hop === 0)
  const h1 = nodes.filter((node) => node.hop === 1)
  const h2 = nodes.filter((node) => node.hop === 2)
  const rest = nodes.filter((node) => node.hop > 2)

  // 锚点：≤3 时贴近原点；>3 时排在第一壳
  if (anchors.length <= 3) {
    anchors.forEach((node, index) => {
      const a = (index / Math.max(anchors.length, 1)) * Math.PI * 2
      out.set(node.entity_id, new THREE.Vector3(Math.cos(a) * 0.6, Math.sin(a) * 0.6, 0))
    })
  } else {
    anchors.forEach((node, index) => {
      const a = (index / anchors.length) * Math.PI * 2
      out.set(node.entity_id, spherePoint(a, 0, SPHERE_RADIUS * 0.35))
    })
  }

  const shells: { items: GraphNode[]; radius: number }[] = [
    { items: h1, radius: SPHERE_RADIUS * 0.55 },
    { items: h2, radius: SPHERE_RADIUS * 0.85 },
    { items: rest, radius: SPHERE_RADIUS },
  ]

  for (const { items, radius } of shells) {
    if (!items.length) continue
    const phiOffset = items.length * 0.61803398875 * Math.PI  // 黄金角偏移，避免同层节点共线
    items.forEach((node, index) => {
      const phi = Math.acos(1 - (2 * (index + 0.5)) / items.length)
      const theta = phiOffset + index * 2.39996323
      out.set(node.entity_id, spherePointFromPhiTheta(phi, theta, radius))
    })
  }

  return out
}

function spherePoint(theta: number, phi: number, radius: number): THREE.Vector3 {
  return spherePointFromPhiTheta(phi, theta, radius)
}

function spherePointFromPhiTheta(phi: number, theta: number, radius: number): THREE.Vector3 {
  return new THREE.Vector3(
    radius * Math.sin(phi) * Math.cos(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.sin(theta),
  )
}

interface SceneProps {
  nodes: GraphNode[]
  edges: GraphLink[]
  positions: Map<string, THREE.Vector3>
  selectedId: string | null
  highlight: Set<string>
  onSelect: (id: string) => void
  onExpand: (id: string) => void
}

function Scene({ nodes, edges, positions, selectedId, highlight, onSelect, onExpand }: SceneProps) {
  const group = useRef<THREE.Group>(null)

  useFrame((_, delta) => {
    if (!group.current) return
    // 自动缓慢自转；用户交互期间 OrbitControls 接管，rotateY 不会冲突
    group.current.rotation.y += AUTO_SPIN_RAD_PER_SEC * delta
  })

  return (
    <group ref={group}>
      <ambientLight intensity={0.85} />
      <directionalLight position={[6, 6, 6]} intensity={0.7} />
      <directionalLight position={[-6, -3, -4]} intensity={0.35} />

      {edges.map((edge, index) => {
        const from = positions.get(edge.src)
        const to = positions.get(edge.dst)
        if (!from || !to) return null
        const isFocus = selectedId === edge.src || selectedId === edge.dst
        return (
          <EdgeLine
            key={`${edge.src}-${edge.dst}-${index}`}
            from={from}
            to={to}
            focus={isFocus}
            weight={edge.weight}
            highlight={highlight}
          />
        )
      })}

      {nodes.map((node) => {
        const point = positions.get(node.entity_id)
        if (!point) return null
        const radius = nodeRadius(node, 0.45)
        const selected = node.entity_id === selectedId
        const dimmed = highlight.size > 0 && !highlight.has(node.entity_id) && !selected
        return (
          <NodeSphere
            key={node.entity_id}
            position={point}
            radius={radius}
            color={kindHex(node.kind)}
            selected={selected}
            dimmed={dimmed}
            label={node.name}
            kindLabel={kindLabel(node.kind)}
            mentions={node.mentions}
            anchor={node.hop === 0}
            onClick={() => onSelect(node.entity_id)}
            onDoubleClick={() => onExpand(node.entity_id)}
          />
        )
      })}
    </group>
  )
}

function NodeSphere({
  position,
  radius,
  color,
  selected,
  dimmed,
  label,
  kindLabel,
  mentions,
  anchor,
  onClick,
  onDoubleClick,
}: {
  position: THREE.Vector3
  radius: number
  color: string
  selected: boolean
  dimmed: boolean
  label: string
  kindLabel: string
  mentions: number
  anchor: boolean
  onClick: () => void
  onDoubleClick: () => void
}) {
  const mesh = useRef<THREE.Mesh>(null)
  const [hover, setHover] = useState(false)

  // 选中时让球面有轻微脉动，避免静态感
  useFrame((state) => {
    if (!mesh.current) return
    const t = state.clock.elapsedTime
    const pulse = selected ? 1 + Math.sin(t * 2.4) * 0.06 : 1
    mesh.current.scale.setScalar(pulse)
  })

  return (
    <group position={position}>
      <mesh
        ref={mesh}
        onPointerOver={(event: ThreeEvent<PointerEvent>) => {
          event.stopPropagation()
          setHover(true)
          document.body.style.cursor = "pointer"
        }}
        onPointerOut={() => {
          setHover(false)
          document.body.style.cursor = "default"
        }}
        onClick={(event: ThreeEvent<MouseEvent>) => {
          event.stopPropagation()
          onClick()
        }}
        onDoubleClick={(event: ThreeEvent<MouseEvent>) => {
          event.stopPropagation()
          onDoubleClick()
        }}
      >
        <sphereGeometry args={[radius, 24, 24]} />
        <meshStandardMaterial
          color={color}
          emissive={color}
          emissiveIntensity={selected ? 0.6 : hover ? 0.35 : 0.15}
          roughness={0.4}
          metalness={0.2}
          transparent={dimmed}
          opacity={dimmed ? 0.25 : 1}
        />
      </mesh>
      {anchor ? (
        <mesh>
          <sphereGeometry args={[radius * 1.55, 24, 24]} />
          <meshBasicMaterial color={color} transparent opacity={0.18} />
        </mesh>
      ) : null}
      {(hover || selected) ? (
        <Html
          center
          distanceFactor={10}
          style={{
            pointerEvents: "none",
            background: "var(--popover)",
            color: "var(--popover-foreground)",
            padding: "4px 8px",
            borderRadius: 6,
            fontSize: 11,
            border: "1px solid var(--border)",
            whiteSpace: "nowrap",
            boxShadow: "0 4px 12px rgb(0 0 0 / 0.12)",
          }}
        >
          {`${label} · ${kindLabel} · ${mentions} 次`}
        </Html>
      ) : null}
    </group>
  )
}

function EdgeLine({
  from,
  to,
  focus,
  weight,
  highlight,
}: {
  from: THREE.Vector3
  to: THREE.Vector3
  focus: boolean
  weight: number
  highlight: Set<string>
}) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry().setFromPoints([from, to])
    return g
  }, [from, to])

  useEffect(() => {
    return () => geometry.dispose()
  }, [geometry])

  const dimmed = highlight.size > 0 && !focus
  const opacity = dimmed ? 0.06 : focus ? 0.85 : 0.35
  const lineWidth = Math.min(0.4 + Math.log2(Math.max(weight, 1)) * 0.6, 3)
  return (
    <line>
      <primitive attach="geometry" object={geometry} />
      <lineBasicMaterial
        color={focus ? "#f97316" : "#94a3b8"}
        transparent
        opacity={opacity}
        linewidth={lineWidth}
      />
    </line>
  )
}

function CameraAutoFit({ count }: { count: number }) {
  const { camera } = useThree()
  useEffect(() => {
    // 节点越多拉远一点，避免拥挤
    const target = 5 + count * 0.02
    camera.position.setLength(Math.max(camera.position.length(), target))
  }, [count, camera])
  return null
}

export function GraphCanvas({
  nodes,
  edges,
  selectedId,
  onSelect,
  onExpand,
}: {
  nodes: GraphNode[]
  edges: GraphLink[]
  selectedId: string | null
  onSelect: (entityId: string) => void
  onExpand: (entityId: string) => void
}) {
  const positions = useMemo(() => layoutPositions(nodes), [nodes])
  const highlight = useMemo(() => {
    if (!selectedId) return new Set<string>()
    const set = new Set<string>([selectedId])
    for (const edge of edges) {
      if (edge.src === selectedId) set.add(edge.dst)
      if (edge.dst === selectedId) set.add(edge.src)
    }
    return set
  }, [edges, selectedId])

  const orbitRef = useRef<OrbitControlsImpl | null>(null)

  return (
    <div className="relative h-full w-full overflow-hidden rounded-md border border-[var(--border)] bg-[var(--background)]">
      <Canvas
        camera={{ position: [6, 4, 7], fov: 50 }}
        dpr={[1, 2]}
        onPointerMissed={() => onSelect("")}
        gl={{ antialias: true, alpha: true }}
      >
        <CameraAutoFit count={nodes.length} />
        <Scene
          nodes={nodes}
          edges={edges}
          positions={positions}
          selectedId={selectedId}
          highlight={highlight}
          onSelect={onSelect}
          onExpand={onExpand}
        />
        <OrbitControls
          ref={orbitRef}
          enablePan
          enableZoom
          enableRotate
          enableDamping
          dampingFactor={DAMPING}
          rotateSpeed={0.8}
          minDistance={3}
          maxDistance={20}
          autoRotate={false}
        />
      </Canvas>
      <OverlayHints />
    </div>
  )
}

function OverlayHints() {
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 flex gap-1.5 text-[11px] text-[var(--muted-foreground)]">
      <span className="rounded bg-[var(--popover)] px-2 py-1 shadow-sm border border-[var(--border)]">拖拽旋转</span>
      <span className="rounded bg-[var(--popover)] px-2 py-1 shadow-sm border border-[var(--border)]">滚轮缩放</span>
      <span className="rounded bg-[var(--popover)] px-2 py-1 shadow-sm border border-[var(--border)]">双击节点换中心</span>
    </div>
  )
}
