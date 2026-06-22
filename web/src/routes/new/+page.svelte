<script lang="ts">
  import { goto } from "$app/navigation";
  import { createTask } from "$lib/api";
  import type { Category } from "$lib/types";

  const CATEGORIES: Category[] = ["phone", "admin", "errand", "chore"];
  let title = $state("");
  let category = $state<Category>("phone");
  let busy = $state(false);
  let error = $state("");

  async function submit(e: Event) {
    e.preventDefault();
    if (!title.trim() || busy) return;
    busy = true; error = "";
    try { await createTask(title.trim(), category); goto("/"); }
    catch (err) { error = err instanceof Error ? err.message : "couldn't capture — try again"; busy = false; }
  }
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">New task</h1>
<form onsubmit={submit}>
  <label class="field">
    <span>Title</span>
    <input type="text" bind:value={title} placeholder="What needs doing?" />
  </label>
  <label class="field">
    <span>Category</span>
    <select bind:value={category}>
      {#each CATEGORIES as c}<option value={c}>{c}</option>{/each}
    </select>
  </label>
  {#if error}<p class="msg-err">{error}</p>{/if}
  <button class="btn btn-primary" type="submit" disabled={busy}>{busy ? "Capturing…" : "Capture"}</button>
</form>
