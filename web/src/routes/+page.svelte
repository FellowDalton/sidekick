<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import Dashboard from "./Dashboard.svelte";
  import { getFeed, ApiError } from "$lib/api";
  import { hasToken } from "$lib/settings";
  import type { Feed } from "$lib/types";

  let feed = $state<Feed | null>(null);
  let error = $state("");

  async function load() {
    error = "";
    try { feed = await getFeed(); }
    catch (e) {
      if (e instanceof ApiError && e.status === 401) { goto("/settings"); return; }
      error = e instanceof Error ? e.message : "couldn't reach the host";
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
  <Dashboard {feed} />
{:else}
  <p class="muted">Loading…</p>
{/if}
