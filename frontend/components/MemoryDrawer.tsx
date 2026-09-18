"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import StatusChip from "./StatusChip";

export default function MemoryDrawer({ id, onClose, onChanged }:
  { id: number | null; onClose: () => void; onChanged: () => void }) {
  const [m, setM] = useState<any>(null);
  useEffect(() => {
    if (id == null) { setM(null); return; }
    api.memory(id).then(setM).catch(() => setM(null));
  }, [id]);

  if (id == null) return null;

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-ink/20" onClick={onClose}>
      <aside
        className="w-[420px] max-w-full h-full bg-surface border-l border-hairline overflow-y-auto p-5"
        onClick={(e) => e.stopPropagation()}
      >
        {!m && <p className="text-sm text-muted">Loading…</p>}
        {m && (
          <>
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-muted">{m.label}</span>
              <button onClick={onClose} className="text-muted text-sm hover:text-ink">close</button>
            </div>
            <h2 className="mt-2 text-xl font-semibold">{m.value}</h2>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-xs text-muted">{m.key}</span>
              <StatusChip status={m.status} />
            </div>

            <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
              {[
                ["type", m.memory_type], ["assertion", m.assertion],
                ["confidence", m.confidence], ["importance", m.importance],
                ["evidence", `${m.evidence_count} (${m.evidence_type?.toLowerCase()})`],
                ["used in answers", m.access_count],
                ["valid from", (m.valid_from || "").slice(0, 10)],
                ["valid until", (m.valid_until || "now").slice(0, 10)],
                ["reason", (m.status_reason || "").toLowerCase().replace(/_/g, " ")],
              ].map(([k, v]) => (
                <div key={k as string}>
                  <dt className="text-muted text-[10px] font-mono">{k}</dt>
                  <dd>{String(v)}</dd>
                </div>
              ))}
            </dl>

            <h3 className="mt-5 text-sm font-semibold">Evidence</h3>
            <ul className="mt-1 space-y-1">
              {m.sources?.map((s: any, i: number) => (
                <li key={i} className="text-[12px] text-muted">
                  <span className="font-mono text-[10px]">{s.relation.toLowerCase()}</span>{" "}
                  message #{s.message_id} — “{s.excerpt}”
                </li>
              ))}
              {!m.sources?.length && <li className="text-[12px] text-muted">None recorded.</li>}
            </ul>

            <h3 className="mt-5 text-sm font-semibold">State changes</h3>
            <ol className="mt-1 space-y-1">
              {m.events?.map((e: any, i: number) => (
                <li key={i} className="text-[12px]">
                  <span className="font-mono text-[10px] text-muted">
                    {(e.at || "").slice(0, 10)}
                  </span>{" "}
                  {e.from_status ? `${e.from_status} → ` : ""}{e.to_status}
                  <span className="text-muted"> · {e.reason_code.toLowerCase().replace(/_/g, " ")}</span>
                </li>
              ))}
            </ol>

            <h3 className="mt-5 text-sm font-semibold">Slot history</h3>
            <ol className="mt-1 space-y-1">
              {m.slot_history?.map((h: any) => (
                <li key={h.id} className={`text-[12px] ${h.id === m.id ? "font-semibold" : ""}`}>
                  <span className="font-mono text-[10px] text-muted">{h.label}</span>{" "}
                  {h.value} <StatusChip status={h.status} />
                </li>
              ))}
            </ol>

            {m.status !== "RETRACTED" && (
              <button
                onClick={async () => { await api.forget(m.id); onChanged(); onClose(); }}
                className="mt-6 text-[12px] text-retracted border border-retracted/40 rounded px-2.5 py-1 hover:bg-retracted/5"
              >
                Forget this memory
              </button>
            )}
          </>
        )}
      </aside>
    </div>
  );
}
