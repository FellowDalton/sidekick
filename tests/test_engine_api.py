"""Unit tests for the host-API engine extensions in sidekick.py: configure() and the
idempotent, completed_at-honoring complete(). Imports sidekick directly and repoints
it at a throwaway vault via configure()."""
import json, tempfile, unittest
from pathlib import Path

import sidekick


class EngineApiExtensions(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "tasks").mkdir()
        (self.vault / "ledger.jsonl").write_text("", encoding="utf-8")
        sidekick.configure(str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()

    def _ledger_lines(self):
        return [l for l in (self.vault / "ledger.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]

    def test_configure_repoints_paths(self):
        self.assertEqual(sidekick.VAULT, str(self.vault))
        self.assertEqual(sidekick.TASKS, str(self.vault / "tasks"))
        self.assertEqual(sidekick.LEDGER, str(self.vault / "ledger.jsonl"))
        self.assertEqual(sidekick.DATA_JS, str(self.vault / "sidekick-data.js"))
        self.assertEqual(sidekick.RENDER_JS, str(self.vault / "sidekick-render.js"))
        self.assertEqual(sidekick.WIKI, str(self.vault / "wiki"))
        self.assertEqual(sidekick.WIKI_INDEX, str(self.vault / "wiki" / "_index.md"))

    def test_complete_honors_completed_at_and_appends_once(self):
        tid = sidekick.create_task("Call dentist", "phone")
        res = sidekick.complete(tid, completed_at="2026-06-20T09:00:00Z")
        self.assertEqual(res["status"], "done")
        self.assertEqual(res["completed_at"], "2026-06-20T09:00:00Z")
        self.assertFalse(res["already_done"])
        lines = self._ledger_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["completed_at"], "2026-06-20T09:00:00Z")

    def test_complete_is_idempotent(self):
        tid = sidekick.create_task("Renew passport", "admin")
        first = sidekick.complete(tid)
        self.assertFalse(first["already_done"])
        again = sidekick.complete(tid)
        self.assertTrue(again["already_done"])
        self.assertEqual(len(self._ledger_lines()), 1)  # no second event

    def test_complete_missing_task_raises(self):
        with self.assertRaises(FileNotFoundError):
            sidekick.complete("nope-does-not-exist")


if __name__ == "__main__":
    unittest.main()
