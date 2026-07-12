/* Data is provided by sidekick-data.js as window.SIDEKICK (see that file for the contract). */
const EVENTS = (window.SIDEKICK && window.SIDEKICK.events) || [];
const ACTIVE = (window.SIDEKICK && window.SIDEKICK.active) || [];
const DATA_LOADED = typeof window.SIDEKICK !== "undefined";
const STATS  = (window.SIDEKICK && window.SIDEKICK.stats) || null;   // absent on pre-learning-layer feeds

/* ── TUNING 1: branch rules — predicates over events, not categories ───── */
const BRANCHES = [
  { key:"diplomat",     name:"Diplomat",     hue:"var(--h-diplomat)",     test:e => e.category==="phone"||e.category==="admin", invite:"Untapped — clear a call or an admin task." },
  { key:"pathfinder",   name:"Pathfinder",   hue:"var(--h-pathfinder)",   test:e => e.category==="errand",                      invite:"Untapped — run an errand." },
  { key:"hearthkeeper", name:"Hearthkeeper", hue:"var(--h-hearthkeeper)", test:e => e.category==="chore",                       invite:"Untapped — knock out a chore." },
  { key:"loremaster",   name:"Loremaster",   hue:"var(--h-loremaster)",   test:e => !!e.orchestrator,                          invite:"Untapped — let the orchestrator take one on." },
  { key:"swift",        name:"Swift",        hue:"var(--h-swift)",        test:e => e.sat_for_hours!=null && e.sat_for_hours<=2, invite:"Untapped — clear one within a couple of hours." }
];
const CAT_HUE = { phone:"var(--h-diplomat)", admin:"var(--h-diplomat)", errand:"var(--h-pathfinder)", chore:"var(--h-hearthkeeper)" };

/* ── TUNING 2: the level curve — flat XP, linearly rising cost ─────────── */
function progress(count, base, step){
  let lvl=0, used=0, cost=base;
  while(used+cost<=count){ used+=cost; lvl++; cost=base+step*lvl; }
  const into=count-used, span=cost;
  return { level:lvl, into, span, toNext:span-into, pct: span?into/span:0 };
}
const OVERALL_CURVE = { base:4, step:2 };
const BRANCH_CURVE  = { base:2, step:1 };

/* ── helpers ───────────────────────────────────────────────────────────── */
const LEVEL_WORDS = ["Getting started","Finding the rhythm","Warmed up","In the swing","Hitting stride","On a roll","Dialled in","Unstoppable"];
const esc = s => String(s).replace(/[&<>"]/g, c=>({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;" }[c]));
const fmtDate = iso => new Date(iso).toLocaleDateString(undefined,{month:"short",day:"numeric"});
const dur = h => h==null ? "—" : (h<24 ? Math.round(h)+"h" : Math.round(h/24)+"d");
function ago(iso){ const h=Math.round((Date.now()-new Date(iso))/36e5); if(h<1)return"just now"; if(h<24)return h+"h ago"; return Math.round(h/24)+"d ago"; }

/* ── render ────────────────────────────────────────────────────────────── */
function render(){
  if(!DATA_LOADED){
    document.querySelector(".wrap").innerHTML =
      '<p class="foot-note" style="margin-top:40px">Couldn\'t load <code>sidekick-data.js</code> — it should sit in the same '
      + 'folder as this page. If your browser is blocking local files, serve the folder instead: '
      + '<code>python3 -m http.server</code>, then open the address it prints.</p>';
    return;
  }

  // hero
  const total = EVENTS.length;
  const ov = progress(total, OVERALL_CURVE.base, OVERALL_CURVE.step);
  document.getElementById("asOf").textContent = "as of " + fmtDate(new Date().toISOString());
  document.getElementById("level").textContent = ov.level;
  document.getElementById("levelWord").textContent = LEVEL_WORDS[Math.min(ov.level, LEVEL_WORDS.length-1)];
  document.getElementById("heroStats").innerHTML =
    `<b>${total}</b> tasks cleared <span class="dot">·</span> <b>${ov.toNext}</b> to level ${ov.level+1}`;
  const r=52, C=2*Math.PI*r, arc=document.getElementById("arc");
  arc.style.strokeDasharray=C; arc.style.strokeDashoffset=C;
  requestAnimationFrame(()=>requestAnimationFrame(()=>{ arc.style.strokeDashoffset=C*(1-ov.pct); }));

  // active tasks + prepared plans
  const host = document.getElementById("active");
  document.getElementById("activeCount").textContent = ACTIVE.length + " open";
  ACTIVE.forEach(t=>{
    const card = document.createElement("article");
    card.className = "task-card" + (t.plan ? "" : " noplan");
    const hue = CAT_HUE[t.category] || "var(--line)";
    let body = `
      <div class="tc-head">
        <h3 class="tc-name">${esc(t.task)}</h3>
        <span class="tc-meta">
          <span class="cat" style="--cl:${hue}">${esc(t.category)}</span>
          <span class="sat">${dur(t.sat_for_hours)}</span>
        </span>
      </div>`;
    if (t.plan){
      const steps = t.plan.steps.map((s,i)=>{
        const inner = s.href
          ? `<a href="${esc(s.href)}"${s.href.startsWith("tel:")?"":' target="_blank" rel="noopener"'}>${esc(s.text)}</a>`
          : esc(s.text);
        return `<li${i===0?' class="next"':""}>${inner}</li>`;
      }).join("");
      body += `<div class="plan-sum"><span class="prep">Prepared</span>${esc(t.plan.summary)}</div><ol class="steps">${steps}</ol>`;
    } else {
      body += `<div class="noplan-msg">No plan yet — ask the orchestrator to clear the first step.</div>`;
    }
    card.innerHTML = body;
    host.appendChild(card);
  });

  // branches
  const bhost = document.getElementById("branches");
  let litIndex = 0;
  BRANCHES.forEach(b=>{
    const count = EVENTS.filter(b.test).length;
    const el = document.createElement("div");
    el.tabIndex = 0;
    if (count>0){
      const p = progress(count, BRANCH_CURVE.base, BRANCH_CURVE.step);
      el.className = "branch lit";
      el.style.setProperty("--hue", b.hue);
      el.style.animationDelay = (litIndex++ * 0.09) + "s";
      el.innerHTML = `
        <div class="bname">${b.name}</div>
        <div class="blvl">Level ${p.level}</div>
        <div class="bar"><i></i></div>
        <div class="foot"><span>${p.into}/${p.span} to next</span><span class="mono">${count} done</span></div>`;
      bhost.appendChild(el);
      const bar = el.querySelector(".bar > i");
      requestAnimationFrame(()=>requestAnimationFrame(()=>{ bar.style.width=(p.pct*100)+"%"; }));
    } else {
      el.className = "branch unlit";
      el.innerHTML = `<div class="bname">${b.name}</div><div class="blvl">Unlit</div><div class="invite">${b.invite}</div>`;
      bhost.appendChild(el);
    }
  });

  // patterns — deterministic aggregates computed by `sidekick.py regenerate`.
  // Older feeds have no stats key: hide the section instead of rendering zeros.
  // Pages without a patterns host (e.g. older chrome-extension mirrors) are guarded too.
  const phost = document.getElementById("patterns"), phead = document.getElementById("patternsHead");
  if (STATS && phost){
    const cats = Object.entries(STATS.by_category||{}).sort((a,b)=>b[1]-a[1] || (a[0]<b[0]?-1:1));
    const wk = STATS.by_weekday || [0,0,0,0,0,0,0];
    const wkMax = Math.max(1, ...wk);
    const WD = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];
    const busiest = wk.some(v=>v>0) ? WD[wk.indexOf(Math.max(...wk))] : "—";
    phost.innerHTML = `
      <div class="stat"><div class="slabel">Streak</div><div class="sval">${STATS.streak_days||0}d</div><div class="ssub">consecutive days cleared · UTC</div></div>
      <div class="stat"><div class="slabel">Median to done</div><div class="sval">${dur(STATS.median_sat_hours)}</div><div class="ssub">capture → cleared</div></div>
      <div class="stat"><div class="slabel">Top category</div><div class="sval sm">${cats.length?esc(cats[0][0]):"—"}</div><div class="ssub">${cats.map(([c,n])=>esc(c)+" "+n).join(" · ")||"nothing yet"}</div></div>
      <div class="stat"><div class="slabel">By weekday</div>
        <div class="wk">${wk.map(v=>`<i style="height:${Math.round(v/wkMax*100)}%"></i>`).join("")}</div>
        <div class="wkl">${WD.map(n=>`<span>${n}</span>`).join("")}</div>
        <div class="ssub">busiest: ${busiest} · UTC days</div></div>`;
  } else {
    if (phost) phost.style.display = "none";
    if (phead) phead.style.display = "none";
  }

  // recently cleared — newest first, top 7
  const log = document.getElementById("log");
  [...EVENTS].sort((a,b)=>new Date(b.completed_at)-new Date(a.completed_at)).slice(0,7).forEach(e=>{
    const chips = BRANCHES.filter(b=>b.test(e)).map(b=>`<span class="chip" style="--cl:${b.hue}">${b.name}</span>`).join("");
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `<span class="task">${esc(e.task)}</span><span class="chips">${chips}</span><span class="when">${ago(e.completed_at)}</span>`;
    log.appendChild(row);
  });
}
render();
