<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { goto } from "$app/navigation";
  import Dashboard from "./Dashboard.svelte";
  import { getFeed, completeTask, setTaskDescription, startAgentJob, getAgentJob, ApiError, type AgentJob } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { Feed } from "$lib/types";

  let feed = $state<Feed | null>(null);
  let error = $state("");
  let pending = $state(new Set<string>());
  let agentJobs = $state<Record<string, AgentJob>>({});
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  async function load() {
    error = "";
    try { feed = await getFeed(); }
    catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  async function onComplete(id: string) {
    if (!feed || pending.has(id)) return;
    const removed = feed.active.find(t => t.id === id);
    if (!removed) return;
    pending = new Set(pending).add(id);
    feed = { ...feed, active: feed.active.filter(t => t.id !== id) };  // optimistic
    try {
      await completeTask(id, new Date().toISOString());
      await load();                                                    // reconcile (ledger/branches)
    } catch (e) {
      feed = { ...feed, active: [removed, ...feed.active] };           // roll back
      error = e instanceof Error ? e.message : "couldn't complete — try again";
    } finally {
      const next = new Set(pending); next.delete(id); pending = next;
    }
  }

  // Returns whether the save succeeded — Dashboard.svelte awaits this and only
  // clears its editing state on success, so a failed save leaves the user's
  // typed text in place instead of discarding it.
  async function onDescribe(id: string, text: string): Promise<boolean> {
    if (!feed) return false;
    const trimmed = text.trim();
    const prevDesc = feed.active.find(t => t.id === id)?.description ?? null;
    feed = {
      ...feed,
      active: feed.active.map(t => t.id === id ? { ...t, description: trimmed || null } : t)
    };  // optimistic — whitespace-only clears to null, server handles the actual clear
    try {
      await setTaskDescription(id, text);
      await load();                                                    // reconcile
      return true;
    } catch (e) {
      // targeted rollback: restore only this task's description in the CURRENT
      // feed, so an unrelated optimistic mutation that landed in between isn't reverted
      feed = feed ? { ...feed, active: feed.active.map(t => t.id === id ? { ...t, description: prevDesc } : t) } : feed;
      error = e instanceof Error ? e.message : "couldn't save — try again";
      return false;
    }
  }

  // ── agent jobs (spec sub-project 3) ───────────────────────────────────────
  function jobActive(j: AgentJob): boolean {
    return j.status === "queued" || j.status === "running";
  }
  function stopPolling() { if (pollTimer) { clearInterval(pollTimer); pollTimer = null; } }
  function startPolling() { if (!pollTimer) pollTimer = setInterval(poll, 5000); }

  async function poll() {
    const active = Object.values(agentJobs).filter(jobActive);
    if (active.length === 0) { stopPolling(); return; }
    for (const j of active) {
      try {
        const fresh = await getAgentJob(j.id);
        agentJobs = { ...agentJobs, [fresh.task_id]: fresh };
        // the agent's plan reaches this clone via the host's sync timer —
        // reload on done, but it may still take a couple of minutes to appear
        if (fresh.status === "done") await load();
      } catch (e) {
        if (e instanceof ApiError) {
          if (e.status === 401) {
            stopPolling();
            goto("/settings");
            return;
          }
          if (e.status === 404) {
            // job evaporated (server restart pruned it) — mark failed locally
            agentJobs = { ...agentJobs, [j.task_id]: { ...j, status: "failed", error: "job lost" } };
            continue;
          }
        }
        // anything else is transient — keep polling
      }
    }
    // after processing all active jobs, check if any remain; if not, stop
    const stillActive = Object.values(agentJobs).filter(jobActive);
    if (stillActive.length === 0) stopPolling();
  }

  async function onAgent(id: string) {
    if (agentJobs[id] && jobActive(agentJobs[id])) return;
    error = "";
    try {
      const job = await startAgentJob(id, "research");
      agentJobs = { ...agentJobs, [id]: job };
      startPolling();
    } catch (e) {
      error = e instanceof Error ? e.message : "couldn't start the agent — try again";
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
  onDestroy(stopPolling);
</script>

{#if error}
  <p class="msg-err">{error}</p>
  <button class="btn" onclick={load}>Retry</button>
{:else if feed}
  <Dashboard {feed} {onComplete} {pending} {onAgent} {agentJobs} {onDescribe} />
{:else}
  <p class="muted">Loading…</p>
{/if}
