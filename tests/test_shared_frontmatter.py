"""Shared-list frontmatter (spec sub-project 2): create_task can stamp `from:` and
`shared: true`; read_active surfaces both so the API can enforce roles. Defaults are
unchanged — a plain create writes neither key (absent = personal)."""
import tempfile, unittest
from pathlib import Path

import sidekick


class SharedFrontmatter(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "tasks").mkdir()
        (self.vault / "ledger.jsonl").write_text("", encoding="utf-8")
        sidekick.configure(str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()

    def test_default_create_stays_personal(self):
        tid = sidekick.create_task("Buy milk", "errand")
        fm, _ = sidekick.read_note(sidekick.task_path(tid))
        self.assertNotIn("from", fm)
        self.assertNotIn("shared", fm)

    def test_create_writes_from_and_shared(self):
        tid = sidekick.create_task("Buy milk", "errand", from_="wife", shared=True)
        fm, _ = sidekick.read_note(sidekick.task_path(tid))
        self.assertEqual(fm["from"], "wife")
        self.assertIs(fm["shared"], True)

    def test_read_active_surfaces_the_fields(self):
        shared = sidekick.create_task("Buy milk", "errand", from_="wife", shared=True)
        personal = sidekick.create_task("File taxes", "admin")
        by_id = {a["id"]: a for a in sidekick.read_active()}
        self.assertEqual(by_id[shared]["from"], "wife")
        self.assertIs(by_id[shared]["shared"], True)
        self.assertIsNone(by_id[personal]["from"])
        self.assertIs(by_id[personal]["shared"], False)

    def test_complete_still_works_on_shared_tasks(self):
        tid = sidekick.create_task("Buy milk", "errand", from_="wife", shared=True)
        res = sidekick.complete(tid)
        self.assertEqual(res["status"], "done")


if __name__ == "__main__":
    unittest.main()
