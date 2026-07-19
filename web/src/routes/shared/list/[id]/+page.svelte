<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { getFeed, createTask, completeTask, startAgentJob, getAgentJob, ApiError, type AgentJob } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import { buildTree, doneCount, showNudge, type TreeNode } from "$lib/tree";
  import type { ActiveTask, Feed } from "$lib/types";

  const listId = $derived(page.params.id);

  let feed = $state<Feed | null>(null);
  let title = $state("");
  let busy = $state(false);
  let error = $state("");
  let pending = $state(new Set<string>());
  let agentJobs = $state<Record<string, AgentJob>>({});
  let pollTimer: ReturnType<typeof setInterval> | null = null;

  const listName = $derived(
    listId === "todos" ? "To-dos" : (feed?.lists ?? []).find(l => l.id === listId)?.name ?? null);

  const newestFirst = (list: ActiveTask[]) =>
    [...list].sort((a, b) => (a.sat_for_hours ?? 0) - (b.sat_for_hours ?? 0));

  // full tree of shared tasks, then keep only this list's roots — children follow
  const tree = $derived(feed
    ? buildTree(newestFirst(feed.active.filter(t => t.shared)))
        .filter(n => (n.task.list ?? "todos") === listId)
    : []);

  async function load() {
    error = "";
    try {
      feed = await getFeed();
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
      await createTask(title.trim(), "chore", true,
                       listId === "todos" ? undefined : listId);  // fixed category: the box has no picker
      title = "";
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : "couldn't add — try again";
    } finally {
      busy = false;
    }
  }

  async function tick(id: string) {
    if (!feed || pending.has(id)) return;
    const prev = feed;
    if (!prev.active.some(t => t.id === id)) return;
    pending = new Set(pending).add(id);
    feed = { ...prev, active: prev.active.map(t => t.id === id ? { ...t, status: "done" as const } : t) };  // optimistic
    try {
      await completeTask(id, new Date().toISOString());
      await load();                                       // reconcile: fetch new items from other user
    } catch (e) {
      feed = prev;                                        // roll back
      error = e instanceof Error ? e.message : "couldn't complete — try again";
    } finally {
      const next = new Set(pending); next.delete(id); pending = next;
    }
  }

  // ── agent jobs: breakdown, both roles (unchanged from the old shared page) ──
  function jobActive(j: AgentJob): boolean {
    return j.status === "queued" || j.status === "running";
  }
  function chipText(j: AgentJob): string {
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
        if (fresh.status === "done") await load();
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) { stopPolling(); goto("/settings"); return; }
        if (e instanceof ApiError && e.status === 404) {
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

<a href="/shared" class="muted back">← Lists</a>

{#if feed && listName === null}
  <p class="msg-err">List not found — it may have been deleted on another phone.</p>
{:else}
  <h1 class="tc-name" style="font-size:26px;margin:8px 0 18px">{listName ?? "…"}</h1>

  <form class="add-row" onsubmit={add}>
    <input type="text" bind:value={title} placeholder="Add to the list…" aria-label="New task" />
    <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? "Adding…" : "Add"}</button>
  </form>

  {#if error}
    <p class="msg-err">{error}</p>
    <button class="btn" onclick={load}>Retry</button>
  {/if}

  {#if feed}
    {#if tree.length === 0}
      <p class="muted">Nothing on the list.</p>
    {:else}
      {#snippet row(node: TreeNode)}
        {@const t = node.task}
        <li class:done-row={t.status === "done"}>
          <label>
            {#if t.status === "done"}
              <input type="checkbox" checked disabled aria-label={t.task + " — done"} />
              <span class="struck">{t.task}</span>
            {:else}
              <input type="checkbox" disabled={pending.has(t.id)}
                     onchange={() => tick(t.id)} aria-label={"Complete " + t.task} />
              <span>{t.task}</span>
              {#if showNudge(node)}
                <span class="chip nudge">{doneCount(node).done}/{doneCount(node).total} done — finish it?</span>
              {/if}
            {/if}
          </label>
          {#if t.status !== "done"}
            <div class="row-agent">
              <button class="btn btn-mini" disabled={!!agentJobs[t.id] && jobActive(agentJobs[t.id])}
                      onclick={() => breakItDown(t.id)} aria-label={"Break down " + t.task}>
                {!!agentJobs[t.id] && jobActive(agentJobs[t.id]) ? "Working…" : "Break it down"}
              </button>
              {#if agentJobs[t.id]}
                <span class="chip chip-{agentJobs[t.id].status}">{chipText(agentJobs[t.id])}</span>
              {/if}
            </div>
          {/if}
          {#if node.children.length}
            <ul class="list children">
              {#each node.children as c (c.task.id)}{@render row(c)}{/each}
            </ul>
          {/if}
        </li>
      {/snippet}
      <ul class="list">
        {#each tree as n (n.task.id)}{@render row(n)}{/each}
      </ul>
    {/if}
  {:else if !error}
    <p class="muted">Loading…</p>
  {/if}
{/if}

<style>
  .back { display: inline-block; font-size: 14px; text-decoration: none; }
  .add-row { display: flex; gap: 8px; margin-bottom: 18px; }
  .add-row input[type="text"] {
    flex: 1; min-width: 0; padding: 10px 12px; border-radius: 10px;
    border: 1px solid rgba(128, 128, 128, 0.35); background: transparent;
    color: inherit; font-size: 16px;   /* ≥16px prevents iOS focus zoom */
  }
  .list { list-style: none; padding: 0; margin: 0; }
  .list li { padding: 12px 0; border-bottom: 1px solid rgba(128, 128, 128, 0.2); }
  .list label { display: flex; align-items: center; gap: 12px; font-size: 17px; flex-wrap: wrap; }
  .list input[type="checkbox"] { width: 22px; height: 22px; flex: none; }
  .row-agent { display: flex; align-items: center; gap: 8px; margin: 8px 0 0 34px; }
  .btn-mini { font-size: 13px; padding: 4px 10px; }
  .chip { font-size: 12px; padding: 2px 8px; border-radius: 999px;
          border: 1px solid rgba(128, 128, 128, 0.35); opacity: 0.85; }
  .chip-queued, .chip-running { animation: chip-pulse 1.5s ease-in-out infinite; }
  .chip-failed { border-color: rgba(220, 60, 60, 0.6); }
  @keyframes chip-pulse { 50% { opacity: 0.45; } }
  .children { margin: 8px 0 0 22px; border-left: 2px solid rgba(128, 128, 128, 0.25); padding-left: 12px; }
  .children li:last-child { border-bottom: none; }
  .struck { text-decoration: line-through; opacity: 0.55; }
  .nudge { border-color: rgba(120, 200, 120, 0.5); }
</style>
