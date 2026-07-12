"""The daily nudge job. Deterministic decide ported from nudge.py; optional model
WORDING (never decision); delivery via server.push to dalton only. Web-push send
is always mocked; the decide logic runs pure and against a real throwaway vault."""
import datetime as dt
import shlex
import sys

import pytest

from server import nudge_job


def _t(task="Pay tax", sat=100, plan=None, category="admin"):
    return {"id": "x", "task": task, "category": category,
            "sat_for_hours": sat, "plan": plan, "from": None, "shared": False}


PLAN = {"summary": "ready", "steps": [{"text": "Call SKAT", "href": "https://skat.dk"}]}


# ── pick_task (ported behavior) ─────────────────────────────────────────────
def test_pick_prefers_planned_over_longer_unplanned():
    a, b = _t("no plan", sat=120), _t("planned", sat=60, plan=PLAN)
    assert nudge_job.pick_task([a, b], 48) is b


def test_pick_longest_among_planned():
    older, newer = _t("older", sat=90, plan=PLAN), _t("newer", sat=60, plan=PLAN)
    assert nudge_job.pick_task([newer, older], 48) is older


def test_pick_silent_when_nothing_stalled():
    assert nudge_job.pick_task([], 48) is None
    assert nudge_job.pick_task([_t(sat=10)], 48) is None


def test_pick_falls_back_to_unplanned_when_no_plans():
    a = _t("bare", sat=80)
    assert nudge_job.pick_task([a], 48) is a


# ── deterministic wording ───────────────────────────────────────────────────
def test_message_with_plan_names_first_step_and_href():
    m = nudge_job.deterministic_message(_t(sat=72, plan=PLAN))
    assert "Pay tax" in m and "3d" in m and "Call SKAT" in m and "https://skat.dk" in m


def test_message_without_plan_suggests_asking():
    m = nudge_job.deterministic_message(_t(sat=20))
    assert "Pay tax" in m and "20h" in m and "first step" in m


# ── model wording: ANY failure → None (fallback fires) ──────────────────────
def _cmd(tmp_path, script):
    p = tmp_path / "fake-pi.py"
    p.write_text(script, encoding="utf-8")
    return f"{shlex.quote(sys.executable)} {shlex.quote(str(p))}"


def test_model_message_returns_first_line(tmp_path):
    cmd = _cmd(tmp_path, 'print("A kind nudge about tax")\n')
    assert nudge_job.model_message(cmd, _t(plan=PLAN)) == "A kind nudge about tax"


def test_model_message_none_on_missing_binary():
    assert nudge_job.model_message("/nonexistent/pi -p", _t()) is None


def test_model_message_none_on_nonzero_exit(tmp_path):
    cmd = _cmd(tmp_path, 'import sys; sys.exit(3)\n')
    assert nudge_job.model_message(cmd, _t()) is None


def test_model_message_none_on_none_reply(tmp_path):
    cmd = _cmd(tmp_path, 'print("NUDGE: NONE")\n')
    assert nudge_job.model_message(cmd, _t()) is None


# ── decide ──────────────────────────────────────────────────────────────────
def test_decide_silent_when_nothing_stalled():
    assert nudge_job.decide([_t(sat=5)], 48) is None


def test_decide_deterministic_without_cmd():
    title, body, source = nudge_job.decide([_t(sat=72, plan=PLAN)], 48, cmd="")
    assert title == "Sidekick" and source == "deterministic" and "Call SKAT" in body


def test_decide_uses_model_wording(monkeypatch):
    monkeypatch.setattr(nudge_job, "model_message", lambda cmd, t: "worded!")
    _, body, source = nudge_job.decide([_t(sat=72, plan=PLAN)], 48, cmd="pi -p")
    assert body == "worded!" and source == "model"


def test_decide_falls_back_when_model_fails(monkeypatch):
    monkeypatch.setattr(nudge_job, "model_message", lambda cmd, t: None)
    _, body, source = nudge_job.decide([_t(sat=72, plan=PLAN)], 48, cmd="pi -p")
    assert source == "deterministic" and "Call SKAT" in body


# ── run (vault-backed) ──────────────────────────────────────────────────────
def _write_task(vault, tid, title, hours_ago, plan_step=None):
    created = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours_ago)).isoformat()
    plan = f"plan:\n  summary: ready\n  steps:\n    - text: {plan_step}\n" if plan_step else ""
    (vault / "tasks" / f"{tid}.md").write_text(
        f"---\ncategory: admin\ncreated: '{created}'\nstatus: open\n{plan}---\n# {title}\n",
        encoding="utf-8")


def _config(vault_repo):
    from server.config import Config
    return Config(vault=str(vault_repo), token="test-token", push=False)


@pytest.fixture(autouse=True)
def _clean_nudge_env(monkeypatch):
    monkeypatch.delenv("SIDEKICK_NUDGE_CMD", raising=False)
    monkeypatch.delenv("SIDEKICK_NUDGE_MIN_SAT_HOURS", raising=False)


def test_run_dry_run_decides_but_never_sends(vault_repo, monkeypatch, capsys):
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    monkeypatch.setattr(nudge_job.push, "send_to_identity",
                        lambda *a, **kw: pytest.fail("dry-run must not send"))
    assert nudge_job.run(_config(vault_repo), dry_run=True) == 0
    assert "DRY-RUN" in capsys.readouterr().out


def test_run_sends_to_dalton_only(vault_repo, monkeypatch, capsys):
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    sent = []
    monkeypatch.setattr(nudge_job.push, "send_to_identity",
                        lambda config, name, title, body: (sent.append((name, title, body)), 1)[1])
    assert nudge_job.run(_config(vault_repo)) == 0
    assert len(sent) == 1
    name, title, body = sent[0]
    assert name == "dalton"                    # spec: wife receives no push this phase
    assert title == "Sidekick" and "Call SKAT" in body


def test_run_silent_when_everything_fresh(vault_repo, monkeypatch, capsys):
    _write_task(vault_repo, "20260710-new", "Fresh task", hours_ago=2)
    monkeypatch.setattr(nudge_job.push, "send_to_identity",
                        lambda *a, **kw: pytest.fail("must stay silent"))
    assert nudge_job.run(_config(vault_repo)) == 0
    assert "silent" in capsys.readouterr().out


def test_run_min_sat_hours_from_env(vault_repo, monkeypatch, capsys):
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    monkeypatch.setenv("SIDEKICK_NUDGE_MIN_SAT_HOURS", "1000")
    monkeypatch.setattr(nudge_job.push, "send_to_identity",
                        lambda *a, **kw: pytest.fail("must stay silent"))
    assert nudge_job.run(_config(vault_repo)) == 0
    assert "silent" in capsys.readouterr().out


def test_run_never_writes_vault_data(vault_repo, monkeypatch):
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    task_before = (vault_repo / "tasks" / "20260701-pay-tax.md").read_text(encoding="utf-8")
    ledger_before = (vault_repo / "ledger.jsonl").read_text(encoding="utf-8")
    monkeypatch.setattr(nudge_job.push, "send_to_identity", lambda *a, **kw: 1)
    nudge_job.run(_config(vault_repo))
    assert (vault_repo / "tasks" / "20260701-pay-tax.md").read_text(encoding="utf-8") == task_before
    assert (vault_repo / "ledger.jsonl").read_text(encoding="utf-8") == ledger_before


def test_main_exit_codes(vault_repo, monkeypatch, capsys):
    monkeypatch.setenv("SIDEKICK_VAULT", str(vault_repo))
    monkeypatch.setenv("SIDEKICK_API_TOKEN", "test-token")
    _write_task(vault_repo, "20260701-pay-tax", "Pay tax", hours_ago=72, plan_step="Call SKAT")
    assert nudge_job.main(["--dry-run"]) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    # actually sending without VAPID keys configured must fail LOUDLY (exit 1)
    monkeypatch.delenv("SIDEKICK_VAPID_PRIVATE", raising=False)
    monkeypatch.delenv("SIDEKICK_VAPID_SUB", raising=False)
    assert nudge_job.main([]) == 1
    assert "nudge:" in capsys.readouterr().err
