<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { getFeed, createTask, completeTask, ApiError } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { ActiveTask } from "$lib/types";

  let tasks = $state<ActiveTask[] | null>(null);
  let title = $state("");
  let busy = $state(false);
  let error = $state("");
  let pending = $state(new Set<string>());

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

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
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
</style>
