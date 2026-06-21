<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import Dashboard from "./Dashboard.svelte";
  import { getFeed, completeTask, ApiError } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { Feed } from "$lib/types";

  let feed = $state<Feed | null>(null);
  let error = $state("");
  let pending = $state(new Set<string>());

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

  onMount(() => {
    if (!hasToken()) { goto("/settings"); return; }
    load();
  });
</script>

{#if error}
  <p class="msg-err">{error}</p>
  <button class="btn" onclick={load}>Retry</button>
{:else if feed}
  <Dashboard {feed} {onComplete} {pending} />
{:else}
  <p class="muted">Loading…</p>
{/if}
