<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { goto } from "$app/navigation";
  import { getFeed, createTask, completeTask, startAgentJob, getAgentJob, ApiError, type AgentJob } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { ActiveTask } from "$lib/types";

  let tasks = $state<ActiveTask[] | null>(null);
  let title = $state("");
  let busy = $state(false);
  let error = $state("");
  let pending = $state(new Set<string>());
  let agentJobs = $state<Record<string, AgentJob>>({});
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  // newest first: read_active sorts longest-sitting first, so invert by sat hours
  const newestFirst = (list: ActiveTask[]) =>
    [...list].sort((a, b) => (a.sat_for_hours ?? 0) - (b.sat_for_hours ?? 0));

  async function load() {
    error = "";
    try {
      const feed = await getFeed();
      // role `shared` gets a pre-filtered feed; for role `full` this filter does the same job
      tasks = newestFirst(feed.active.filter(t => t.shared));
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  async function add(e: Event) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    busy = true; error = "";
    try {
      await createTask(title.trim(), "chore", true);  // fixed category: the box has no picker
      title = "";
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : "couldn't add — try again";
    } finally {
      busy = false;
    }
  }

  async function tick(id: string) {
    if (!tasks || pending.has(id)) return;
    const removed = tasks.find(t => t.id === id);
    if (!removed) return;
    pending = new Set(pending).add(id);
    tasks = tasks.filter(t => t.id !== id);              // optimistic
    try {
      await completeTask(id, new Date().toISOString());
      await load();                                       // reconcile: fetch new items from other user
    } catch (e) {
      tasks = newestFirst([removed, ...tasks]);          // roll back
      error = e instanceof Error ? e.message : "couldn't complete — try again";
    } finally {
      const next = new Set(pending); next.delete(id); pending = next;
    }
  }

  // ── agent jobs (spec sub-project 3): breakdown, both roles ────────────────
  function jobActive(j: AgentJob): boolean {
    return j.status === "queued" || j.status === "running";
  }
  function chipText(j: AgentJob): string {
    // breakdown sub-tasks land via the host's sync timer, a few minutes after
    // the job itself finishes — don't imply they're already on the list
    if (j.status === "done") return "done — sub-tasks arrive in a few minutes";
    if (j.status === "failed") return j.error === "job lost" ? "failed (job lost)" : "failed";
    return j.status;
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
        // sub-tasks reach this list via the host's sync timer — reload on done,
        // but they may still take a couple of minutes to appear
        if (fresh.status === "done") await load();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          stopPolling();
          goto("/settings");
          return;
        }
        if (e instanceof ApiError && e.status === 404) {
          // job lost — mark as failed
          agentJobs = { ...agentJobs, [j.task_id]: { ...j, status: "failed", error: "job lost" } };
        }
        // else: transient — keep polling
      }
    }
  }

  async function breakItDown(id: string) {
    if (agentJobs[id] && jobActive(agentJobs[id])) return;
    error = "";
    try {
      const job = await startAgentJob(id, "breakdown");
      agentJobs = { ...agentJobs, [id]: job };
      startPolling();
    } catch (e) {
      error = e instanceof Error ? e.message : "couldn't start — try again";
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
  onDestroy(stopPolling);
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">Shared list</h1>

<form class="add-row" onsubmit={add}>
  <input type="text" bind:value={title} placeholder="Add to the list…"
         aria-label="New shared task" />
  <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
</form>

{#if error}
  <p class="msg-err">{error}</p>
  <button class="btn" onclick={load}>Retry</button>
{/if}

{#if tasks}
  {#if tasks.length === 0}
    <p class="muted">Nothing on the list.</p>
  {:else}
    <ul class="list">
      {#each tasks as t (t.id)}
        <li>
          <label>
            <input type="checkbox" disabled={pending.has(t.id)}
                   onchange={() => tick(t.id)} aria-label={"Complete " + t.task} />
            <span>{t.task}</span>
          </label>
          <div class="row-agent">
            <button class="btn btn-mini" disabled={!!agentJobs[t.id] && jobActive(agentJobs[t.id])}
                    onclick={() => breakItDown(t.id)} aria-label={"Break down " + t.task}>
              {!!agentJobs[t.id] && jobActive(agentJobs[t.id]) ? "Working…" : "Break it down"}
            </button>
            {#if agentJobs[t.id]}
              <span class="chip chip-{agentJobs[t.id].status}">{chipText(agentJobs[t.id])}</span>
            {/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
{:else if !error}
  <p class="muted">Loading…</p>
{/if}

<style>
  .add-row { display: flex; gap: 8px; margin-bottom: 18px; }
  .add-row input[type="text"] {
    flex: 1; min-width: 0; padding: 10px 12px; border-radius: 10px;
    border: 1px solid rgba(128, 128, 128, 0.35); background: transparent;
    color: inherit; font-size: 16px;   /* ≥16px prevents iOS focus zoom */
  }
  .list { list-style: none; padding: 0; margin: 0; }
  .list li { padding: 12px 0; border-bottom: 1px solid rgba(128, 128, 128, 0.2); }
  .list label { display: flex; align-items: center; gap: 12px; font-size: 17px; }
  .list input[type="checkbox"] { width: 22px; height: 22px; flex: none; }
  .row-agent { display: flex; align-items: center; gap: 8px; margin: 8px 0 0 34px; }
  .btn-mini { font-size: 13px; padding: 4px 10px; }
  .chip { font-size: 12px; padding: 2px 8px; border-radius: 999px;
          border: 1px solid rgba(128, 128, 128, 0.35); opacity: 0.85; }
  .chip-queued, .chip-running { animation: chip-pulse 1.5s ease-in-out infinite; }
  .chip-failed { border-color: rgba(220, 60, 60, 0.6); }
  @keyframes chip-pulse { 50% { opacity: 0.45; } }
</style>
