<script lang="ts">
  import { settings } from "$lib/settings";

  let token = $state($settings.token);
  let apiBase = $state($settings.apiBase);

  // keep the store in sync as the user types (persists to localStorage via the store)
  $effect(() => { settings.set({ token: token.trim(), apiBase: apiBase.trim() }); });
</script>

<h1 class="tc-name" style="font-size:26px;margin-bottom:18px">Settings</h1>
<label class="field">
  <span>API token</span>
  <input type="password" bind:value={token} placeholder="paste your bearer token" autocomplete="off" />
</label>
<label class="field">
  <span>API base URL (optional)</span>
  <input type="text" bind:value={apiBase} placeholder="leave blank to use this site (/api)" autocomplete="off" />
</label>
<p class="muted">Stored only in this browser. Leave the base URL blank in normal use — the app proxies <code>/api</code> to the host.</p>
{#if token.trim()}<p class="msg-ok">Token saved. Open the Dashboard.</p>{/if}
