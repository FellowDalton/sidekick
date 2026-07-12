"""complete's CLI flags (--note, --via) must reach the ledger event, and --via must
default to "cli". Runs sidekick.py as a subprocess against a throwaway vault
(SIDEKICK_VAULT), so it exercises the real CLI. Requires pyyaml (the only dep)."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "sidekick.py"


class CliCompleteFlags(unittest.TestCase):
    def _run(self, vault, *args, check=True):
        env = {**os.environ, "SIDEKICK_VAULT": str(vault)}
        return subprocess.run([sys.executable, str(SCRIPT), *args],
                              check=check, env=env, cwd=str(vault),
                              capture_output=True, text=True)

    def _make_task(self, vault):
        (vault / "ledger.jsonl").write_text("", encoding="utf-8")
        out = self._run(vault, "new", "Fix the bike light", "--category", "chore").stdout
        return out.splitlines()[0].split()[1]          # "created <id>"

    def _event(self, vault):
        lines = [l for l in (vault / "ledger.jsonl").read_text(encoding="utf-8").splitlines()
                 if l.strip()]
        self.assertEqual(len(lines), 1)
        return json.loads(lines[0])

    def test_note_and_via_reach_the_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            tid = self._make_task(vault)
            self._run(vault, "complete", tid, "--note", "battery is CR2032", "--via", "agent")
            e = self._event(vault)
            self.assertEqual(e["note"], "battery is CR2032")
            self.assertEqual(e["via"], "agent")

    def test_via_defaults_to_cli_and_note_is_omitted(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            tid = self._make_task(vault)
            self._run(vault, "complete", tid)
            e = self._event(vault)
            self.assertEqual(e["via"], "cli")
            self.assertNotIn("note", e)

    def test_invalid_via_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            tid = self._make_task(vault)
            r = self._run(vault, "complete", tid, "--via", "carrier-pigeon", check=False)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("invalid choice", r.stderr)


if __name__ == "__main__":
    unittest.main()
