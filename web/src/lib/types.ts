export type Category = "phone" | "admin" | "errand" | "chore";

export interface PlanStep { text: string; href?: string; }
export interface Plan { summary: string; steps: PlanStep[]; }

export interface ActiveTask {
  id: string;
  task: string;
  category: Category | string;
  sat_for_hours: number | null;
  plan: Plan | null;
}

export interface LedgerEvent {
  task: string;
  category: string | null;
  completed_at: string;
  sat_for_hours: number | null;
  orchestrator?: string | null;
}

export interface Feed { events: LedgerEvent[]; active: ActiveTask[]; }
