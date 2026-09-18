"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const FILL: Record<string, string> = {
  ACTIVE: "#12734F", SUPERSEDED: "#94A3B8", ENDED: "#3F4C5D",
  DISPUTED: "#A85B06", ARCHIVED: "#B6BFC9",
};

/** Deterministic layout: one row per attribute, versions left to right.
 *  Supersession chains are linear, so a fixed layout reads better than a
 *  force-directed one and can't jitter during a demo. */
export default function GraphView({ refreshKey, onOpen }:
  { refreshKey: number; onOpen: (id: number) => void }) {
  const [g, setG] = useState<any>({ nodes: [], edges: [] });
  useEffect(() => { api.graph().then(setG).catch(() => setG({ nodes: [], edges: [] })); },
    [refreshKey]);

  if (!g.nodes.length)
    return <p className="text-xs text-muted p-4 text-center">No memories yet.</p>;

  const keys = Array.from(new Set(g.nodes.map((n: any) => n.key))) as string[];
  const pos: Record<number, { x: number; y: number }> = {};
  keys.forEach((k, row) => {
    g.nodes.filter((n: any) => n.key === k)
      .sort((a: any, b: any) => a.id - b.id)
      .forEach((n: any, col: number) => {
        pos[n.id] = { x: 90 + col * 150, y: 40 + row * 78 };
      });
  });
  const width = 90 + Math.max(...Object.values(pos).map((p) => p.x)) + 80;
  const height = 40 + keys.length * 78 + 20;

  return (
    <div className="p-3 overflow-auto h-full">
      <p className="text-[11px] text-muted mb-2">
        Nodes are memories; arrows are supersession. Derived from the same
        columns the engine uses — no separate graph database.
      </p>
      <svg width={width} height={height} className="min-w-full">
        <defs>
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3"
                  orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#64748B" /></marker>
        </defs>
        {keys.map((k, i) => (
          <text key={k} x={6} y={44 + i * 78} fontSize="10" fill="#5A6675"
                fontFamily="IBM Plex Mono">{k}</text>
        ))}
        {g.edges.filter((e: any) => e.type === "SUPERSEDES").map((e: any, i: number) => {
          const a = pos[e.source], b = pos[e.target];
          if (!a || !b) return null;
          return (
            <g key={i}>
              <line x1={a.x + 58} y1={a.y} x2={b.x - 6} y2={b.y}
                    stroke="#64748B" strokeWidth="1.5" markerEnd="url(#arrow)" />
              <text x={(a.x + b.x) / 2 - 2} y={a.y - 8} fontSize="8" fill="#64748B"
                    textAnchor="middle" fontFamily="IBM Plex Mono">supersedes</text>
            </g>
          );
        })}
        {g.edges.filter((e: any) => e.type === "DISPUTES").map((e: any, i: number) => {
          const a = pos[e.source], b = pos[e.target];
          if (!a || !b) return null;
          return <line key={`d${i}`} x1={a.x + 58} y1={a.y} x2={b.x - 6} y2={b.y}
                       stroke="#A85B06" strokeWidth="1.5" strokeDasharray="4 3" />;
        })}
        {g.nodes.map((n: any) => {
          const p = pos[n.id];
          if (!p) return null;
          return (
            <g key={n.id} onClick={() => onOpen(n.id)} style={{ cursor: "pointer" }}>
              <rect x={p.x - 6} y={p.y - 17} width={116} height={34} rx={4}
                    fill="#FFFFFF" stroke={FILL[n.status]} strokeWidth="1.6" />
              <text x={p.x + 2} y={p.y - 4} fontSize="9" fill="#5A6675"
                    fontFamily="IBM Plex Mono">{n.label}</text>
              <text x={p.x + 2} y={p.y + 9} fontSize="11" fill="#0F1722"
                    fontWeight="600">{n.value}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
