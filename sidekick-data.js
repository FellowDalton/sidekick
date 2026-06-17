/* ════════════════════════════════════════════════════════════════════
   sidekick-data.js — the frontend's data feed. GENERATED, never hand-edited.

   Claude Code rebuilds this each session:
     events  <- parsed lines of ledger.jsonl  (canonical append-only store, §6)
     active  <- open items from the Google Tasks API + their prepared plans (§5)

   sidekick.html is static and does not change when this data changes — that
   is the decoupling. Replace this file, reload the page, the dashboard updates.

   Event:  { task, category, completed_at(ISO), sat_for_hours, orchestrator|null }
   Active: { id, task, category, sat_for_hours,
             plan: null | { summary, steps:[ { text, href? } ] } }
   ════════════════════════════════════════════════════════════════════ */
window.SIDEKICK = {
  events: [
  { task:"Call the dentist",             category:"phone",  completed_at:"2026-06-16T09:12:00Z", sat_for_hours:52,  orchestrator:"found the number and opening hours" },
  { task:"Cancel the gym membership",    category:"admin",  completed_at:"2026-06-15T17:40:00Z", sat_for_hours:121, orchestrator:"located the cancellation form" },
  { task:"Book the car service",         category:"phone",  completed_at:"2026-06-15T11:05:00Z", sat_for_hours:40,  orchestrator:null },
  { task:"Renew the library card",       category:"admin",  completed_at:"2026-06-14T15:22:00Z", sat_for_hours:18,  orchestrator:null },
  { task:"Sort the insurance email",     category:"admin",  completed_at:"2026-06-13T20:01:00Z", sat_for_hours:64,  orchestrator:null },
  { task:"Ring the landlord re: heating",category:"phone",  completed_at:"2026-06-12T10:18:00Z", sat_for_hours:33,  orchestrator:null },
  { task:"Return the package",           category:"errand", completed_at:"2026-06-16T14:30:00Z", sat_for_hours:28,  orchestrator:null },
  { task:"Pick up the prescription",     category:"errand", completed_at:"2026-06-14T12:00:00Z", sat_for_hours:9,   orchestrator:null },
  { task:"Buy a birthday gift for mum",  category:"errand", completed_at:"2026-06-11T16:45:00Z", sat_for_hours:70,  orchestrator:"shortlisted three gifts in budget" },
  { task:"Unload the dishwasher",        category:"chore",  completed_at:"2026-06-16T08:00:00Z", sat_for_hours:14,  orchestrator:null },
  { task:"Fix the kitchen drawer",       category:"chore",  completed_at:"2026-06-15T19:30:00Z", sat_for_hours:300, orchestrator:null },
  { task:"Take out the recycling",       category:"chore",  completed_at:"2026-06-14T07:50:00Z", sat_for_hours:30,  orchestrator:null },
  { task:"Wipe the kitchen counters",    category:"chore",  completed_at:"2026-06-13T21:10:00Z", sat_for_hours:20,  orchestrator:null },
  { task:"Water the plants",             category:"chore",  completed_at:"2026-06-12T18:00:00Z", sat_for_hours:16,  orchestrator:null }
],
  active: [
  { id:"t1", task:"Sort the car insurance renewal", category:"admin", sat_for_hours:122,
    plan:{ summary:"Compared three renewal quotes — your current insurer is no longer the cheapest.",
      steps:[
        { text:"Call Topdanmark on 70 11 50 50 and ask them to match the lower quote", href:"tel:+4570115050" },
        { text:"If they won't match, switch to the Alm. Brand quote", href:"https://www.almbrand.dk" },
        { text:"Cancel the old direct debit once the switch confirms" }
      ] } },
  { id:"t2", task:"Book the kids' dentist check-up", category:"phone", sat_for_hours:49,
    plan:{ summary:"Found the clinic's online booking — two slots open next week.",
      steps:[
        { text:"Open the booking page", href:"https://example-dentist.dk/book" },
        { text:"Take the Tuesday 15:30 slot" },
        { text:"Add it to the family calendar" }
      ] } },
  { id:"t3", task:"Replace the bathroom extractor fan", category:"chore", sat_for_hours:210,
    plan:{ summary:"Shortlisted two fans that fit a 100 mm duct, both under 400 kr.",
      steps:[
        { text:"Measure the existing duct to confirm it's 100 mm" },
        { text:"Order the Vortice Punto", href:"https://example.com/vortice-punto" },
        { text:"Book the handyman for fitting" }
      ] } },
  { id:"t4", task:"Renew your passport", category:"admin", sat_for_hours:70, plan:null }
]
};
