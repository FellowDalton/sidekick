<script lang="ts">
  import type { Feed } from "$lib/types";
  import type { AgentJob } from "$lib/api";
  import { hero, branchVMs, recentLog, catHue, dur } from "$lib/game";
  import { computeStats, WEEKDAY_NAMES } from "$lib/stats";

  let { feed, onComplete = (_id: string) => {}, pending = new Set<string>(),
        onAgent = (_id: string) => {}, agentJobs = {} }:
    { feed: Feed; onComplete?: (id: string) => void; pending?: Set<string>;
      onAgent?: (id: string) => void; agentJobs?: Record<string, AgentJob> } = $props();

  const h = $derived(hero(feed));
  const branches = $derived(branchVMs(feed));
  const log = $derived(recentLog(feed, 7));
  const stats = $derived(computeStats(feed.events));
  const wkMax = $derived(Math.max(1, ...stats.byWeekday));
  const R = 52, C = 2 * Math.PI * R;

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

<div class="head"><h2>In front of you</h2><span class="count">{feed.active.length} open</span><span class="rule"></span></div>
<section class="section">
  {#each feed.active as t (t.id)}
    <article class="task-card" class:noplan={!t.plan}>
      <div class="tc-head">
        <h3 class="tc-name">{t.task}</h3>
        <span class="tc-meta">
          <span class="cat" style="--cl:{catHue(t.category)}">{t.category}</span>
          <span class="sat">{dur(t.sat_for_hours)}</span>
        </span>
      </div>
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
      {:else}
        <div class="noplan-msg muted">No plan yet — ask the orchestrator to clear the first step.</div>
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
    </article>
  {/each}
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
</style>
