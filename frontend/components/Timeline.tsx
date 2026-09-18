"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";

const FILL: Record<string, string> = {
  ACTIVE: "#12734F", SUPERSEDED: "#94A3B8", ENDED: "#3F4C5D",
  DISPUTED: "#A85B06", ARCHIVED: "#B6BFC9",
};

export default function Timeline({ refreshKey }: { refreshKey: number }) {
  const [slots, setSlots] = useState<any[]>([]);
  useEffect(() => { api.timeline().then(setSlots).catch(() => setSlots([])); }, [refreshKey]);

  if (slots.length === 0)
    return <p className="text-xs text-muted p-4 text-center">No history yet.</p>;

  const dates: number[] = [];
  slots.forEach((s) =>
    s.entries.forEach((e: any) => {
      if (e.valid_from) dates.push(Date.parse(e.valid_from));
      dates.push(e.valid_until ? Date.parse(e.valid_until) : Date.now());
    })
  );
  const min = Math.min(...dates);
  const max = Math.max(...dates);
  const span = Math.max(max - min, 1);
  const pct = (t: number) => ((t - min) / span) * 100;

  return (
    <div className="p-3 space-y-4 overflow-y-auto h-full">
      <p className="text-[11px] text-muted">
        Each bar is one version of an attribute, positioned by when it was true.
      </p>
      {slots.map((s) => (
        <div key={s.slot_id}>
          <div className="text-[11px] font-medium mb-1">{s.key}</div>
          <div className="relative h-7 bg-ground border border-hairline rounded overflow-hidden">
            {[...s.entries]
              // draw shortest-lived entries last so a real dispute sliver
              // is visible as a thin marker on top, never buried under a
              // long bar that started at nearly the same instant
              .sort((a: any, b: any) => {
                const spanA = (a.valid_until ? Date.parse(a.valid_until) : Date.now()) - Date.parse(a.valid_from);
                const spanB = (b.valid_until ? Date.parse(b.valid_until) : Date.now()) - Date.parse(b.valid_from);
                return spanB - spanA;
              })
              .map((e: any) => {
                const from = pct(Date.parse(e.valid_from));
                const to = pct(e.valid_until ? Date.parse(e.valid_until) : Date.now());
                const widthPct = Math.max(to - from, 0.4);
                const tooSmallForLabel = widthPct < 3;
                return (
                  <div
                    key={e.id}
                    title={`${e.label} · ${e.value} · ${e.status} · ${(e.valid_from || "").slice(0, 10)} → ${(e.valid_until || "now").slice(0, 10)}`}
                    className="absolute top-0 h-full flex items-center overflow-hidden rounded"
                    style={{
                      left: `${from}%`,
                      width: `${widthPct}%`,
                      minWidth: "6px",
                      background: FILL[e.status] || "#B6BFC9",
                      paddingLeft: tooSmallForLabel ? 0 : 6,
                      paddingRight: tooSmallForLabel ? 0 : 6,
                      boxShadow: tooSmallForLabel ? "0 0 0 1px rgba(255,255,255,0.6)" : "none",
                    }}
                  >
                    {!tooSmallForLabel && (
                      <span className="text-[10px] text-white font-medium truncate whitespace-nowrap">
                        {e.value}
                      </span>
                    )}
                  </div>
                );
              })}
          </div>
        </div>
      ))}
      <div className="flex justify-between text-[10px] font-mono text-muted">
        <span>{new Date(min).toISOString().slice(0, 10)}</span>
        <span>{new Date(max).toISOString().slice(0, 10)}</span>
      </div>
    </div>
  );
}
