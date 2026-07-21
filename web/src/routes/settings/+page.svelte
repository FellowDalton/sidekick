<script lang="ts">
  import { settings } from "$lib/settings";
  import { enablePush, type EnableResult } from "$lib/push";

  let token = $state($settings.token);
  let apiBase = $state($settings.apiBase);
  let pushState = $state<"" | "working" | "error" | EnableResult>("");

  // keep the store in sync as the user types (persists to localStorage via the store)
  $effect(() => { settings.set({ token: token.trim(), apiBase: apiBase.trim() }); });

  // MUST run inside the click handler: iOS only grants Notification permission
  // from a user gesture, and only in the installed (Home-Screen) PWA.
  let pushError = $state("");

  async function onEnablePush() {
    pushState = "working";
    pushError = "";
    try {
      pushState = await enablePush();
    } catch (e) {
      pushError = e instanceof Error ? e.message : "";
      pushState = "error";
    }
  }
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

<h2 class="tc-name" style="font-size:18px;margin:26px 0 10px">Notifications</h2>
<button class="btn btn-primary" onclick={onEnablePush} disabled={pushState === "working"}>
  {pushState === "working" ? "Enabling…" : "Enable notifications"}
</button>
{#if pushState === "enabled"}
  <p class="msg-ok">Notifications enabled on this device.</p>
{:else if pushState === "denied"}
  <p class="muted">Permission denied — allow notifications for Sidekick in the phone's settings, then try again.</p>
{:else if pushState === "unsupported"}
  <p class="muted">This browser can't receive push. On iPhone, add Sidekick to the Home Screen and open it from there first.</p>
{:else if pushState === "error"}
  <p class="muted">Couldn't subscribe{pushError ? ` (${pushError})` : " — check the API token, then try again."}</p>
{/if}
<p class="muted">One nudge a day at 09:00, and only when something's genuinely stalled.</p>
