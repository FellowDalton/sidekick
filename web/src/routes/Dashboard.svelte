<script lang="ts">
  import type { Feed } from "$lib/types";
  import { hero, branchVMs, recentLog, catHue, dur } from "$lib/game";

  let { feed, onComplete = (_id: string) => {}, pending = new Set<string>() }:
    { feed: Feed; onComplete?: (id: string) => void; pending?: Set<string> } = $props();

  const h = $derived(hero(feed));
  const branches = $derived(branchVMs(feed));
  const log = $derived(recentLog(feed, 7));
  const R = 52, C = 2 * Math.PI * R;

  function safeHref(h: string | undefined): string | null {
    return h && /^(https?|tel|mailto):/i.test(h) ? h : null;
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

<div class="head"><h2>Recently cleared</h2><span class="rule"></span></div>
<section class="section">
  {#each log as r}
    <div class="row"><span class="task">{r.task}</span><span class="when">{r.when}</span></div>
  {/each}
</section>
