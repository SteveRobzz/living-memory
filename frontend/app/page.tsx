"use client";

import { useEffect, useRef, useState } from "react";
import { api, setToken } from "@/lib/api";
import MemoryPanel from "@/components/MemoryPanel";
import MemoryDrawer from "@/components/MemoryDrawer";
import TraceView from "@/components/TraceView";
import Timeline from "@/components/Timeline";
import GraphView from "@/components/GraphView";
import StatusChip from "@/components/StatusChip";

type Turn = {
  id: number;
  role: "user" | "assistant";
  content: string;
  trace?: any;
  changes?: any[];
};

const VIEWS = ["Memories", "Timeline", "Graph"] as const;

const DEMO_DATES = [
  { label: "Jan 2026", iso: "2026-01-05T09:00:00+00:00" },
  { label: "Mar 2026", iso: "2026-03-02T09:00:00+00:00" },
  { label: "May 2026", iso: "2026-05-09T09:00:00+00:00" },
  { label: "Real time", iso: null },
];

export default function Page() {
  const [users, setUsers] = useState<any[]>([]);
  const [user, setUser] = useState<any>(null);
  const [conv, setConv] = useState<number | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<(typeof VIEWS)[number]>("Memories");
  const [refreshKey, setRefreshKey] = useState(0);
  const [openTrace, setOpenTrace] = useState<number | null>(null);
  const [drawer, setDrawer] = useState<number | null>(null);
  const [highlight, setHighlight] = useState<number[]>([]);
  const [simDate, setSimDate] = useState<string | null>(null);
  const [health, setHealth] = useState<any>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.users().then(setUsers).catch(() => {});
    api.health().then(setHealth).catch(() => {});
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  async function pickUser(handle: string) {
    const r = await api.login(handle);
    setToken(r.token);
    setUser(r.user);
    const c = await api.newConversation("Session");
    setConv(c.id);
    setTurns([]);
    setRefreshKey((k) => k + 1);
  }

  async function newSession() {
    const c = await api.newConversation("Session");
    setConv(c.id);
    setTurns([]);
  }

  async function send() {
    if (!input.trim() || !conv || busy) return;
    const text = input.trim();
    setInput("");
    setBusy(true);
    setTurns((t) => [...t, { id: Date.now(), role: "user", content: text }]);
    try {
      const r = await api.send(conv, text);
      setTurns((t) => [
        ...t,
        {
          id: r.assistant_message.id,
          role: "assistant",
          content: r.assistant_message.content,
          trace: r.trace,
          changes: r.memory_changes,
        },
      ]);
      setHighlight((r.memory_changes || []).map((c: any) => c.memory_id));
      setRefreshKey((k) => k + 1);
    } catch (e: any) {
      setTurns((t) => [
        ...t,
        { id: Date.now() + 1, role: "assistant", content: `Request failed: ${e.message}` },
      ]);
    } finally {
      setBusy(false);
    }
  }

  async function jump(iso: string | null) {
    await api.setClock(iso);
    setSimDate(iso);
  }

  if (!user) {
    return (
      <main className="min-h-screen flex items-center justify-center p-6">
        <div className="max-w-lg w-full">
          <p className="font-mono text-[11px] text-muted">living memory</p>
          <h1 className="mt-2 text-3xl font-bold leading-tight">
            RAG retrieves information.
            <br />
            This decides what is still true.
          </h1>
          <p className="mt-3 text-sm text-muted">
            A temporal memory engine. Every fact carries a status, a validity
            interval, the evidence behind it and the reason it changed — and no
            answer can cite a memory it was not shown.
          </p>
          <div className="mt-6 space-y-2">
            {users.map((u) => (
              <button
                key={u.id}
                onClick={() => pickUser(u.handle)}
                className="w-full flex items-center gap-3 border border-hairline bg-surface rounded px-3 py-2.5 hover:border-ink/40"
              >
                <span
                  className="w-3 h-3 rounded-full"
                  style={{ background: u.color }}
                />
                <span className="font-medium">{u.display_name}</span>
                <span className="font-mono text-[11px] text-muted ml-auto">
                  @{u.handle}
                </span>
              </button>
            ))}
          </div>
          {health && (
            <p className="mt-5 font-mono text-[10px] text-muted">
              analyzer: {health.analyzer} · llm: {String(health.llm_enabled)}
            </p>
          )}
        </div>
      </main>
    );
  }

  return (
    <main className="h-screen flex flex-col">
      {/* header */}
      <header className="flex items-center gap-3 px-4 h-12 border-b border-hairline bg-surface">
        <span className="font-mono text-[11px] text-muted">living memory</span>

        <div className="ml-4 flex items-center gap-1">
          {users.map((u) => (
            <button
              key={u.id}
              onClick={() => pickUser(u.handle)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[12px] border ${
                user.id === u.id
                  ? "border-ink font-semibold"
                  : "border-hairline text-muted hover:text-ink"
              }`}
              style={user.id === u.id ? { background: `${u.color}14` } : {}}
            >
              <span className="w-2 h-2 rounded-full" style={{ background: u.color }} />
              {u.display_name}
            </button>
          ))}
        </div>

        <div className="ml-auto flex items-center gap-1">
          {DEMO_DATES.map((d) => (
            <button
              key={d.label}
              onClick={() => jump(d.iso)}
              className={`px-2 py-1 text-[11px] font-mono rounded border ${
                simDate === d.iso
                  ? "border-ink bg-ground"
                  : "border-hairline text-muted hover:text-ink"
              }`}
            >
              {d.label}
            </button>
          ))}
          <button
            onClick={newSession}
            className="ml-2 px-2 py-1 text-[11px] rounded border border-hairline text-muted hover:text-ink"
          >
            new session
          </button>
          <button
            onClick={async () => {
              await api.reset();
              setTurns([]);
              await newSession();
              setRefreshKey((k) => k + 1);
            }}
            className="px-2 py-1 text-[11px] rounded border border-hairline text-muted hover:text-retracted"
          >
            reset
          </button>
        </div>
      </header>

      {simDate && (
        <div className="px-4 py-1 bg-disputed/10 border-b border-disputed/30 text-[11px] font-mono text-disputed">
          demo clock active — the engine's "now" is {simDate.slice(0, 10)}
        </div>
      )}

      <div className="flex-1 flex min-h-0">
        {/* chat */}
        <section className="flex-1 flex flex-col min-w-0 border-r border-hairline">
          <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            {turns.length === 0 && (
              <div className="text-sm text-muted max-w-md">
                <p className="font-medium text-ink">Try this sequence:</p>
                <ol className="mt-2 space-y-1 list-decimal list-inside">
                  <li>Set the clock to Jan, then: I'm building a game in Unity.</li>
                  <li>Set the clock to Mar, then: I switched my game to Godot.</li>
                  <li>What engine am I currently using?</li>
                  <li>What engine was I using in February?</li>
                  <li>Switch user and ask the same question.</li>
                </ol>
              </div>
            )}

            {turns.map((t) => (
              <div key={t.id}>
                <div
                  className={`max-w-2xl ${
                    t.role === "user" ? "ml-auto" : ""
                  }`}
                >
                  <div
                    className={`rounded px-3 py-2 text-[14px] leading-relaxed ${
                      t.role === "user"
                        ? "bg-ink text-white"
                        : "bg-surface border border-hairline"
                    }`}
                  >
                    {t.content}
                  </div>

                  {t.role === "assistant" && t.changes && t.changes.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {t.changes.map((c: any, i: number) => (
                        <button
                          key={i}
                          onClick={() => setDrawer(c.memory_id)}
                          className="flex items-center gap-1.5 border border-hairline bg-surface rounded px-2 py-1 text-[11px] hover:border-ink/40"
                        >
                          <StatusChip status={c.status} />
                          <span className="font-mono text-[10px] text-muted">
                            mem_{String(c.memory_id).padStart(3, "0")}
                          </span>
                          <span>{c.key} = {c.value}</span>
                          <span className="text-muted">
                            {c.reason_code.toLowerCase().replace(/_/g, " ")}
                          </span>
                        </button>
                      ))}
                    </div>
                  )}

                  {t.role === "assistant" && t.trace && (
                    <>
                      <button
                        onClick={() => setOpenTrace(openTrace === t.id ? null : t.id)}
                        className="mt-1.5 text-[11px] text-muted underline underline-offset-2 hover:text-ink"
                      >
                        Why did I say this?
                      </button>
                      {openTrace === t.id && <TraceView trace={t.trace} />}
                    </>
                  )}
                </div>
              </div>
            ))}
            <div ref={endRef} />
          </div>

          <div className="border-t border-hairline p-3 flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Tell it something, or ask what it knows…"
              className="flex-1 border border-hairline rounded px-3 py-2 text-[14px] bg-surface outline-none focus:border-ink"
            />
            <button
              onClick={send}
              disabled={busy}
              className="px-4 py-2 rounded bg-ink text-white text-[13px] disabled:opacity-40"
            >
              {busy ? "…" : "Send"}
            </button>
          </div>
        </section>

        {/* observatory */}
        <aside className="w-[380px] flex flex-col bg-ground/60">
          <div className="flex items-center gap-1 px-3 h-10 border-b border-hairline">
            <span className="font-mono text-[10px] text-muted mr-2">observatory</span>
            {VIEWS.map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-2 py-0.5 text-[11px] rounded ${
                  view === v ? "bg-ink text-white" : "text-muted hover:text-ink"
                }`}
              >
                {v}
              </button>
            ))}
          </div>
          <div className="flex-1 min-h-0">
            {view === "Memories" && (
              <MemoryPanel
                refreshKey={refreshKey}
                highlight={highlight}
                onOpen={setDrawer}
              />
            )}
            {view === "Timeline" && <Timeline refreshKey={refreshKey} />}
            {view === "Graph" && (
              <GraphView refreshKey={refreshKey} onOpen={setDrawer} />
            )}
          </div>
        </aside>
      </div>

      <MemoryDrawer
        id={drawer}
        onClose={() => setDrawer(null)}
        onChanged={() => setRefreshKey((k) => k + 1)}
      />
    </main>
  );
}
