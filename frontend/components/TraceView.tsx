"use client";
import StatusChip from "./StatusChip";

export default function TraceView({ trace }: { trace: any }) {
  if (!trace) return null;
  const used = trace.used || [];
  const considered = trace.considered_not_used || [];
  const p = trace.pipeline || {};

  return (
    <div className="mt-2 border border-hairline bg-surface rounded p-3 text-[12px]">
      <div className="flex items-center gap-2 mb-2">
        <span className="font-semibold">Retrieval trace</span>
        <span className="font-mono text-[10px] text-muted border border-hairline rounded px-1">
          scope: {trace.time_scope}
        </span>
      </div>

      <div className="font-mono text-[10px] text-muted mb-2">
        {p.candidates ?? 0} candidates → {p.after_temporal ?? "–"} after status/temporal
        → {p.after_similarity ?? "–"} after relevance → {used.length} used
      </div>

      {used.length === 0 && (
        <p className="text-muted">No stored memory was used for this answer.</p>
      )}

      {used.map((m: any) => (
        <div key={m.id} className="border-l-2 border-active pl-2.5 py-1.5 mb-2">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px]">{m.label}</span>
            <StatusChip status={m.status} />
            <span className="font-mono text-[10px] text-muted">
              sim {m.similarity} · score {m.memory_score}
            </span>
          </div>
          <div className="mt-0.5">
            {m.key} → <span className="font-medium">{m.value}</span>
          </div>
          <div className="text-muted text-[11px] mt-0.5">
            valid {(m.valid_from || "").slice(0, 10)} → {(m.valid_until || "now").slice(0, 10)}
            {" · "}evidence {m.evidence_count} ({m.evidence_type?.toLowerCase()})
          </div>
          {m.source?.excerpt && (
            <div className="text-muted text-[11px] mt-0.5 italic">
              source: message #{m.source.message_id} — “{m.source.excerpt}”
            </div>
          )}
          {m.supersedes && (
            <div className="mt-1 text-[11px] text-muted">
              replaced <span className="font-mono">{m.supersedes.label}</span> (
              {m.supersedes.value}) — {m.status_reason?.toLowerCase().replace(/_/g, " ")}
            </div>
          )}
        </div>
      ))}

      {considered.length > 0 && (
        <details className="mt-1">
          <summary className="cursor-pointer text-muted text-[11px]">
            Considered but not used ({considered.length})
          </summary>
          <ul className="mt-1 space-y-0.5">
            {considered.map((m: any) => (
              <li key={m.id} className="text-[11px] text-muted">
                <span className="font-mono">{m.label}</span> {m.key} = {m.value} —{" "}
                {m.excluded_because}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
