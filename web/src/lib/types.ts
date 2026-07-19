export type Category = "phone" | "admin" | "errand" | "chore";

export interface PlanStep { text: string; href?: string; }
export interface Plan { summary: string; steps: PlanStep[]; }

export interface ActiveTask {
  id: string;
  task: string;
  category: Category | string;
  sat_for_hours: number | null;
  plan: Plan | null;
  from?: string | null;   // who created it — server-assigned from the token identity
  shared?: boolean;       // membership in the shared list
  parent?: string | null; // sub-task linkage — id of the parent task
  status?: "open" | "done"; // "done" = completed child still shown under its open parent
  completed_at?: string | null; // set on done children only
  list?: string | null;   // named-list membership — id of the list
}

export interface TaskList { id: string; name: string; created: string; }

export interface LedgerEvent {
  task: string;
  category: string | null;
  completed_at: string;
  sat_for_hours: number | null;
  orchestrator?: string | null;
  /* learning-layer fields — absent on pre-learning-layer ledger lines */
  note?: string | null;
  via?: string | null;
  from?: string | null;
}

export interface Feed { events: LedgerEvent[]; active: ActiveTask[]; lists?: TaskList[]; }
