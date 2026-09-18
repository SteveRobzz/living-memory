"use client";
import { useEffect, useState } from "react";
import { api, Memory } from "@/lib/api";
import StatusChip from "./StatusChip";

const TABS = [
  { id: "ACTIVE,DISPUTED", label: "Current" },
  { id: "SUPERSEDED,ENDED", label: "History" },
  { id: "RETRACTED", label: "Retracted" },
];

export default function MemoryPanel({
  refreshKey, highlight, onOpen,
}: { refreshKey: number; highlight: number[]; onOpen: (id: number) => void }) {
  const [tab, setTab] = useState(TABS[0].id);
  const [rows, setRows] = useState<Memory[]>([]);

  useEffect(() => {
    api.memories(tab).then(setRows).catch(() => setRows([]));
  }, [tab, refreshKey]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex gap-1 px-3 pt-3">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-2.5 py-1 text-xs rounded-t border-b-2 ${
              tab === t.id
                ? "border-ink text-ink font-semibold"
                : "border-transparent text-muted hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-1.5">
        {rows.length === 0 && (
          <p className="text-xs text-muted pt-6 text-center">Nothing here yet.</p>
        )}
        {rows.map((m) => (
          <button
            key={m.id}
            onClick={() => onOpen(m.id)}
            className={`w-full text-left border border-hairline bg-surface rounded px-2.5 py-2 hover:border-ink/40 ${
              highlight.includes(m.id) ? "flash" : ""
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[10px] text-muted">{m.label}</span>
              <StatusChip status={m.status} />
            </div>
            <div className="mt-1 text-[13px] leading-snug">
              <span className="text-muted">{m.key}</span>
              <span className="text-muted"> = </span>
              <span className="font-medium">{m.value}</span>
            </div>
            <div className="mt-1 flex gap-3 text-[10px] text-muted font-mono">
              <span>conf {m.confidence.toFixed(2)}</span>
              <span>evid {m.evidence_count}</span>
              {m.superseded_by_id && <span>→ mem_{String(m.superseded_by_id).padStart(3, "0")}</span>}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
