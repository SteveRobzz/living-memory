const BASE = process.env.NEXT_PUBLIC_API || "http://localhost:8000";

let token = "";
export function setToken(t: string) { token = t; }
export function getToken() { return token; }

async function call(path: string, init: RequestInit = {}) {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
}

export const api = {
  health: () => call("/health"),
  users: () => call("/users"),
  login: (handle: string) =>
    call("/auth/demo-login", { method: "POST", body: JSON.stringify({ handle }) }),
  conversations: () => call("/conversations"),
  newConversation: (title?: string) =>
    call("/conversations", { method: "POST", body: JSON.stringify({ title }) }),
  messages: (id: number) => call(`/conversations/${id}/messages`),
  send: (id: number, content: string) =>
    call(`/conversations/${id}/messages`, { method: "POST", body: JSON.stringify({ content }) }),
  memories: (status?: string) => call(`/memories${status ? `?status=${status}` : ""}`),
  memory: (id: number) => call(`/memories/${id}`),
  forget: (id: number) => call(`/memories/${id}`, { method: "DELETE" }),
  graph: () => call("/memories/graph"),
  timeline: () => call("/memories/timeline"),
  events: () => call("/events"),
  setClock: (as_of: string | null) =>
    call("/demo/clock", { method: "POST", body: JSON.stringify({ as_of }) }),
  reset: () => call("/demo/reset", { method: "POST" }),
};

export type Memory = {
  id: number; label: string; key: string; value: string;
  memory_type: string; status: string; status_reason?: string;
  confidence: number; importance: number; evidence_count: number;
  evidence_type: string; valid_from: string | null; valid_until: string | null;
  supersedes_id: number | null; superseded_by_id: number | null;
  access_count: number;
};
