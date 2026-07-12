"""Prompt templates are deterministic strings that carry the orchestrator rules
INLINE — a job must not depend on pi going off to read CLAUDE.md. No model
logic here; pi does the reasoning on the VPS."""
from server import agent_prompts


def test_research_prompt_carries_task_and_workflow():
    p = agent_prompts.research_prompt("20260712-fix-the-bike", "Fix the bike", "errand")
    assert "Fix the bike" in p
    assert "20260712-fix-the-bike" in p
    assert "errand" in p
    # the CLAUDE.md orchestrator steps, present and in order
    assert "wiki/_index.md" in p
    assert "raw/" in p
    assert "python3 sidekick.py wiki" in p
    assert "set-plan 20260712-fix-the-bike" in p
    assert p.index("raw/") < p.index("python3 sidekick.py wiki") < p.index("set-plan")
    # ground rules: engine-only mutations, no git, no completing
    assert "ledger.jsonl" in p
    assert "Do NOT run any git command" in p
    assert "Do NOT complete any task" in p


def test_research_prompt_is_deterministic():
    a = agent_prompts.research_prompt("id-1", "T", "phone")
    assert a == agent_prompts.research_prompt("id-1", "T", "phone")


def test_breakdown_prompt_shared_parent_inherits_shared():
    p = agent_prompts.breakdown_prompt("20260712-plan-trip", "Plan the trip",
                                       "admin", shared=True)
    assert "--from sidekick --shared" in p
    assert "set-plan 20260712-plan-trip" in p
    assert "Do NOT run any git command" in p


def test_breakdown_prompt_personal_parent_never_shared():
    p = agent_prompts.breakdown_prompt("x", "Plan the trip", "admin", shared=False)
    assert "--shared" not in p          # the flag must not appear ANYWHERE
    assert "--from sidekick" in p


def test_breakdown_prompt_defaults_bad_category():
    # frontmatter is hand-editable; a missing/unknown category must not produce
    # an invalid `sidekick.py new` command in the prompt
    p = agent_prompts.breakdown_prompt("x", "T", None, shared=False)
    assert "--category chore" in p
