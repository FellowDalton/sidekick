<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { getFeed, createList, deleteList, ApiError } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import { buildTree } from "$lib/tree";
  import type { Feed, TaskList } from "$lib/types";

  const DEFAULT_LIST: TaskList = { id: "todos", name: "To-dos", created: "" };

  let feed = $state<Feed | null>(null);
  let error = $state("");
  let adding = $state(false);          // the "+ New list" form is open
  let newName = $state("");
  let busy = $state(false);

  async function load() {
    error = "";
    try {
      feed = await getFeed();
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
    }
  }

  // full tree of shared tasks — children follow their root's list automatically
  const roots = $derived(feed ? buildTree(feed.active.filter(t => t.shared)) : []);
  const cards = $derived([DEFAULT_LIST, ...(feed?.lists ?? [])].map(l => {
    const mine = roots.filter(n => (n.task.list ?? "todos") === l.id && n.task.status !== "done");
    return {
      list: l,
      previews: mine.slice(0, 5).map(n => n.task.task),
      more: Math.max(0, mine.length - 5),
      openCount: mine.length,
      deletable: l.id !== "todos" &&
        roots.every(n => (n.task.list ?? "todos") !== l.id),
    };
  }));

  async function addList(e: Event) {
    e.preventDefault();
    if (!newName.trim() || busy) return;
    busy = true; error = "";
    try {
      const entry = await createList(newName.trim());
      goto(`/shared/list/${entry.id}`);
    } catch (err) {
      error = err instanceof Error ? err.message : "couldn't create — try again";
    } finally {
      busy = false;
    }
  }

  async function removeList(id: string) {
    error = "";
    try {
      await deleteList(id);
      await load();
    } catch (err) {
      error = err instanceof Error ? err.message : "couldn't delete — try again";
    }
  }

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">Shared lists</h1>

{#if error}
  <p class="msg-err">{error}</p>
  <button class="btn" onclick={load}>Retry</button>
{/if}

{#if feed}
  <div class="grid">
    {#each cards as c (c.list.id)}
      <a class="card" href={"/shared/list/" + c.list.id}
         aria-label={"Open list " + c.list.name}>
        <div class="card-head">
          <span class="card-name">{c.list.name}</span>
          <span class="count">{c.openCount} open</span>
        </div>
        {#if c.previews.length === 0}
          <p class="muted empty">Nothing here.</p>
        {:else}
          <ul class="preview">
            {#each c.previews as p}<li><span aria-hidden="true">☐</span> <span>{p}</span></li>{/each}
          </ul>
          {#if c.more > 0}<div class="muted more">+{c.more} more</div>{/if}
        {/if}
        {#if c.deletable}
          <button class="btn btn-mini del" aria-label={"Delete " + c.list.name}
                  onclick={(e) => { e.preventDefault(); removeList(c.list.id); }}>
            Delete
          </button>
        {/if}
      </a>
    {/each}
  </div>

  {#if adding}
    <form class="add-row" onsubmit={addList}>
      <input type="text" bind:value={newName} placeholder="List name…" aria-label="List name" />
      <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? "Creating…" : "Create"}</button>
    </form>
  {:else}
    <button class="btn" onclick={() => { adding = true; }}>+ New list</button>
  {/if}
{:else if !error}
  <p class="muted">Loading…</p>
{/if}

<style>
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 18px; }
  .card { display: block; padding: 12px 14px; border-radius: 14px;
          border: 1px solid rgba(128, 128, 128, 0.35); text-decoration: none; color: inherit;
          position: relative; }
  .card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
               margin-bottom: 8px; }
  .card-name { font-weight: 600; font-size: 16px; }
  .count { font-size: 12px; opacity: 0.7; flex: none; }
  .preview { list-style: none; padding: 0; margin: 0; font-size: 13px; line-height: 1.7; }
  .preview li { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .more { font-size: 12px; margin-top: 4px; }
  .empty { font-size: 13px; }
  .del { position: absolute; right: 10px; bottom: 10px; }
  .add-row { display: flex; gap: 8px; }
  .add-row input[type="text"] {
    flex: 1; min-width: 0; padding: 10px 12px; border-radius: 10px;
    border: 1px solid rgba(128, 128, 128, 0.35); background: transparent;
    color: inherit; font-size: 16px;   /* ≥16px prevents iOS focus zoom */
  }
</style>
