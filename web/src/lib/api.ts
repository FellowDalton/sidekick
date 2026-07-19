import { get } from "svelte/store";
import { settings } from "./settings";
import type { Feed, ActiveTask, Category, TaskList } from "./types";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); this.name = "ApiError"; }
}

export interface CompleteResult {
  id: string; status: string; completed_at: string | null;
  sat_for_hours: number | null; already_done: boolean;
}

const base = () => get(settings).apiBase || "";   // "" => relative /api via the proxy

function headers(extra: Record<string, string> = {}): Record<string, string> {
  return { Authorization: `Bearer ${get(settings).token}`, ...extra };
}

async function handle(res: Response): Promise<any> {
  if (res.status === 401) throw new ApiError(401, "unauthorized");
  if (!res.ok) {
    let msg = `request failed (${res.status})`;
    try { const b = await res.json(); if (b && b.error) msg = b.error; } catch { /* ignore */ }
    throw new ApiError(res.status, msg);
  }
  return res.json();
}

export async function getFeed(): Promise<Feed> {
  return handle(await fetch(`${base()}/api/feed`, { headers: headers() }));
}

export interface Identity { name: string; role: "full" | "shared"; }

export async function getMe(): Promise<Identity> {
  return handle(await fetch(`${base()}/api/me`, { headers: headers() }));
}

export async function createTask(title: string, category: Category, shared = false, list?: string): Promise<ActiveTask> {
  const body: Record<string, unknown> = { title, category };
  if (shared) body.shared = true;
  if (list) body.list = list;
  return handle(await fetch(`${base()}/api/tasks`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify(body)
  }));
}

export async function createList(name: string): Promise<TaskList> {
  return handle(await fetch(`${base()}/api/lists`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify({ name })
  }));
}

export async function deleteList(id: string): Promise<void> {
  await handle(await fetch(`${base()}/api/lists/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: headers()
  }));
}

export async function completeTask(id: string, completedAt: string): Promise<CompleteResult> {
  return handle(await fetch(`${base()}/api/tasks/${encodeURIComponent(id)}/complete`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify({ completed_at: completedAt })
  }));
}

export async function getVapidPublicKey(): Promise<string> {
  const res = await handle(await fetch(`${base()}/api/push/vapid-public-key`, { headers: headers() }));
  return res.key;
}

export async function subscribePush(sub: PushSubscriptionJSON): Promise<void> {
  await handle(await fetch(`${base()}/api/push/subscribe`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify(sub)
  }));
}

export type AgentAction = "research" | "breakdown";
export type AgentJobStatus = "queued" | "running" | "done" | "failed";

export interface AgentJob {
  id: string;
  task_id: string;
  action: AgentAction;
  status: AgentJobStatus;
  summary: string | null;
  error: string | null;
  log_tail: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export async function startAgentJob(taskId: string, action: AgentAction): Promise<AgentJob> {
  return handle(await fetch(`${base()}/api/tasks/${encodeURIComponent(taskId)}/agent`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() }),
    body: JSON.stringify({ action })
  }));
}

export async function getAgentJob(id: string): Promise<AgentJob> {
  return handle(await fetch(`${base()}/api/agent/jobs/${encodeURIComponent(id)}`, { headers: headers() }));
}
