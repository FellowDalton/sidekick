<script lang="ts">
  import type { Feed } from "$lib/types";
  import type { AgentJob } from "$lib/api";
  import { hero, branchVMs, recentLog, catHue, dur } from "$lib/game";
  import { computeStats, WEEKDAY_NAMES } from "$lib/stats";
  import { buildTree, doneCount, showNudge, type TreeNode } from "$lib/tree";

  let { feed, onComplete = (_id: string) => {}, pending = new Set<string>(),
        onAgent = (_id: string) => {}, agentJobs = {},
        onDescribe = async (_id: string, _text: string) => true }:
    { feed: Feed; onComplete?: (id: string) => void; pending?: Set<string>;
      onAgent?: (id: string) => void; agentJobs?: Record<string, AgentJob>;
      onDescribe?: (id: string, text: string) => Promise<boolean> } = $props();

  // ── description display/edit (cards), keyed by task id ──
  let expanded = $state(new Set<string>());
  let editing = $state(new Set<string>());
  let editText = $state<Record<string, string>>({});

  function toggleExpanded(id: string) {
    const next = new Set(expanded);
    if (next.has(id)) next.delete(id); else next.add(id);
    expanded = next;
  }

  function startEdit(id: string, current: string | null | undefined) {
    editText = { ...editText, [id]: current ?? "" };
    editing = new Set(editing).add(id);
  }

  function cancelEdit(id: string) {
    const next = new Set(editing); next.delete(id); editing = next;
  }

  async function saveDescription(id: string) {
    const text = editText[id] ?? "";
    const ok = await onDescribe(id, text);
    // only leave editing on success — a failed save keeps the editor open with
    // the user's typed text still in editText, instead of discarding it
    if (ok) {
      const next = new Set(editing); next.delete(id); editing = next;
    }
  }

  const h = $derived(hero(feed));
  const branches = $derived(branchVMs(feed));
  const log = $derived(recentLog(feed, 7));
  const stats = $derived(computeStats(feed.events));
  const wkMax = $derived(Math.max(1, ...stats.byWeekday));
  const R = 52, C = 2 * Math.PI * R;
  const tree = $derived(buildTree(feed.active));
  const openCount = $derived(feed.active.filter(t => t.status !== "done").length);

  function safeHref(h: string | undefined): string | null {
    return h && /^(https?|tel|mailto):/i.test(h) ? h : null;
  }

  function isAgentBusy(id: string): boolean {
    const j = agentJobs[id];
    return !!j && (j.status === "queued" || j.status === "running");
  }
  function chipText(j: AgentJob): string {
    if (j.status === "done") return j.summary ? `done — ${j.summary}` : "done";
    if (j.status === "failed") return "failed";
    return j.status;
  }
</script>

<section class="hero">
  <div class="sigil">
    <svg viewBox="0 0 120 120" aria-hidden="true">
      <circle class="track" cx="60" cy="60" r={R}></circle>
      <circle class="arc" cx="60" cy="60" r={R}
        style="stroke-dasharray:{C};stroke-dashoffset:{C * (1 - h.pct)}"></circle>
    </svg>
    <div class="numeral">{h.level}</div>
  </div>
  <div>
    <div class="eyebrow">Level</div>
    <h1>{h.word}</h1>
    <div class="stats"><b>{h.total}</b> tasks cleared <span class="dot">·</span> <b>{h.toNext}</b> to level {h.level + 1}</div>
  </div>
</section>

<div class="head"><h2>In front of you</h2><span class="count">{openCount} open</span><span class="rule"></span></div>
<section class="section">
  {#snippet taskNode(node: TreeNode)}
    {@const t = node.task}
    <article class="task-card" class:noplan={!t.plan} class:done-card={t.status === "done"}>
      <div class="tc-head">
        <h3 class="tc-name">{t.task}</h3>
        <span class="tc-meta">
          <span class="cat" style="--cl:{catHue(t.category)}">{t.category}</span>
          {#if t.status !== "done"}<span class="sat">{dur(t.sat_for_hours)}</span>{/if}
        </span>
      </div>
      {#if t.status === "done"}
        <div class="muted done-note">✓ done</div>
      {:else}
        {#if t.description}
          {@const isExpanded = expanded.has(t.id)}
          {@const isEditing = editing.has(t.id)}
          <div class="desc">
            {#if isEditing}
              <textarea class="desc-textarea" bind:value={editText[t.id]} rows="3"
                        aria-label={"Edit details for " + t.task}></textarea>
              <div class="desc-edit-actions">
                <button type="button" class="btn btn-mini" onclick={() => saveDescription(t.id)}>Save</button>
                <button type="button" class="btn btn-mini" onclick={() => cancelEdit(t.id)}>Cancel</button>
              </div>
            {:else}
              <button type="button" class="desc-text {isExpanded ? 'expanded' : ''}"
                      aria-label={"Details for " + t.task}
                      onclick={() => toggleExpanded(t.id)}>
                {t.description}
              </button>
              {#if isExpanded}
                <button type="button" class="btn btn-mini" onclick={() => startEdit(t.id, t.description)}>Edit</button>
              {/if}
            {/if}
          </div>
        {/if}
        {#if t.plan}
          <div class="plan-sum"><span class="prep">Prepared</span>{t.plan.summary}</div>
          <ol class="steps">
            {#each t.plan.steps as s, i}
              {@const href = safeHref(s.href)}
              <li class:next={i === 0}>
                {#if href}<a {href} target={href.startsWith("tel:") ? undefined : "_blank"} rel="noopener">{s.text}</a>{:else}{s.text}{/if}
              </li>
            {/each}
          </ol>
        {:else if node.children.length === 0}
          <div class="noplan-msg muted">No plan yet — ask the orchestrator to clear the first step.</div>
        {/if}
        {#if showNudge(node)}
          <span class="nudge">{doneCount(node).done}/{doneCount(node).total} done — finish it?</span>
        {/if}
        <button class="btn btn-done" aria-label="Done" aria-busy={pending.has(t.id)} disabled={pending.has(t.id)} onclick={() => onComplete(t.id)}>
          {pending.has(t.id) ? "Completing…" : "Done"}
        </button>
        <div class="tc-agent">
          <button class="btn" disabled={isAgentBusy(t.id)} onclick={() => onAgent(t.id)}
                  aria-label={"Ask Sidekick about " + t.task}>
            {isAgentBusy(t.id) ? "Sidekick working…" : "Ask Sidekick"}
          </button>
          {#if agentJobs[t.id]}
            <span class="chip chip-{agentJobs[t.id].status}">{chipText(agentJobs[t.id])}</span>
          {/if}
        </div>
      {/if}
      {#if node.children.length}
        <div class="children">
          {#each node.children as c (c.task.id)}{@render taskNode(c)}{/each}
        </div>
      {/if}
    </article>
  {/snippet}
  {#each tree as n (n.task.id)}{@render taskNode(n)}{/each}
</section>

<div class="head"><h2>Skill branches</h2><span class="rule"></span></div>
<section class="section branches">
  {#each branches as b (b.key)}
    {#if b.lit}
      <div class="branch" style="--hue:{b.hue}">
        <div class="bname">{b.name}</div>
        <div class="blvl">Level {b.level}</div>
        <div class="bar"><i style="width:{b.pct * 100}%"></i></div>
        <div class="foot"><span>{b.into}/{b.span} to next</span><span>{b.count} done</span></div>
      </div>
    {:else}
      <div class="branch unlit">
        <div class="bname">{b.name}</div>
        <div class="blvl">Unlit</div>
        <div class="invite">{b.invite}</div>
      </div>
    {/if}
  {/each}
</section>

<div class="head"><h2>Patterns</h2><span class="rule"></span></div>
<section class="section patterns">
  <div class="stat"><div class="slabel">Streak</div><div class="sval">{stats.streakDays}d</div><div class="ssub">consecutive days cleared · UTC</div></div>
  <div class="stat"><div class="slabel">Median to done</div><div class="sval">{dur(stats.medianSatHours)}</div><div class="ssub">capture → cleared</div></div>
  <div class="stat"><div class="slabel">Top category</div>
    <div class="sval sm">{stats.byCategory[0]?.[0] ?? "—"}</div>
    <div class="ssub">{stats.byCategory.map(([c, n]) => `${c} ${n}`).join(" · ") || "nothing yet"}</div></div>
  <div class="stat"><div class="slabel">By weekday</div>
    <div class="wk">{#each stats.byWeekday as v}<i style="height:{Math.round((v / wkMax) * 100)}%"></i>{/each}</div>
    <div class="wkl">{#each WEEKDAY_NAMES as n}<span>{n}</span>{/each}</div>
    <div class="ssub">UTC days</div></div>
</section>

<div class="head"><h2>Recently cleared</h2><span class="rule"></span></div>
<section class="section">
  {#each log as r}
    <div class="row"><span class="task">{r.task}</span><span class="when">{r.when}</span></div>
  {/each}
</section>

<style>
  .tc-agent { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  .chip { font-size: 12px; padding: 2px 8px; border-radius: 999px;
          border: 1px solid rgba(128, 128, 128, 0.35); opacity: 0.85; }
  .chip-queued, .chip-running { animation: chip-pulse 1.5s ease-in-out infinite; }
  .chip-failed { border-color: rgba(220, 60, 60, 0.6); }
  @keyframes chip-pulse { 50% { opacity: 0.45; } }
  .children { margin-top: 10px; padding-left: 14px; border-left: 2px solid rgba(128, 128, 128, 0.25); }
  .done-card .tc-name { text-decoration: line-through; opacity: 0.55; }
  .done-note { font-size: 13px; }
  .nudge { display: inline-block; font-size: 13px; margin: 6px 0; padding: 2px 10px;
           border-radius: 999px; border: 1px solid rgba(120, 200, 120, 0.5); }
  .desc { margin: 4px 0 8px; }
  .desc-text {
    margin: 0; width: 100%; padding: 0; border: none; background: none; color: inherit;
    font: inherit; font-size: 14px; text-align: left; opacity: 0.8; cursor: pointer;
    display: -webkit-box; -webkit-line-clamp: 2; line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
  }
  .desc-text.expanded { -webkit-line-clamp: unset; line-clamp: unset; overflow: visible; }
  .desc-textarea {
    display: block; width: 100%; box-sizing: border-box; margin-top: 6px;
    padding: 8px 10px; border-radius: 10px; border: 1px solid rgba(128, 128, 128, 0.35);
    background: transparent; color: inherit; font: inherit; font-size: 15px; resize: none;
    field-sizing: content;
    max-height: 160px; overflow-y: auto;
  }
  .desc-edit-actions { display: flex; gap: 8px; margin-top: 6px; }
  .btn-mini { font-size: 13px; padding: 4px 10px; }
</style>
