"""`sidekick wiki` rebuilds wiki/_index.md — a deterministic map-of-content over
wiki/*.md. Runs sidekick.py as a subprocess against a throwaway vault
(SIDEKICK_VAULT), so it exercises the real CLI. Requires pyyaml."""
import os, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "sidekick.py"


def run_wiki(vault):
    """Run `sidekick.py wiki` against `vault`; return the CompletedProcess."""
    env = {**os.environ, "SIDEKICK_VAULT": str(vault)}
    return subprocess.run([sys.executable, str(SCRIPT), "wiki"],
                          env=env, capture_output=True, text=True)


def seed(wiki, name, text):
    (wiki / name).write_text(text, encoding="utf-8")


class WikiIndex(unittest.TestCase):
    def test_build_sorts_and_formats(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d); wiki = vault / "wiki"; wiki.mkdir()
            seed(wiki, "car-insurance.md",
                 "---\nsummary: Renewal facts and account refs.\n"
                 "updated: 2026-06-13\n---\n\n# Car insurance\n\nbody\n")
            seed(wiki, "dentist.md",
                 "---\nsummary: Checkup cadence and contact.\n"
                 "updated: 2026-06-16\n---\n\n# Dentist\n\nbody\n")

            r = run_wiki(vault)
            self.assertEqual(r.returncode, 0, r.stderr)

            idx = wiki / "_index.md"
            self.assertTrue(idx.exists(), "index not written")
            text = idx.read_text(encoding="utf-8")

            self.assertIn("do not hand-edit", text)
            self.assertIn("# Wiki — reusable memory", text)
            self.assertIn("[[car-insurance|Car insurance]] — Renewal facts and account refs.", text)
            self.assertIn("[[dentist|Dentist]] — Checkup cadence and contact.", text)
            self.assertIn("updated 2026-06-16", text)
            # newer `updated` first: dentist (06-16) precedes car-insurance (06-13)
            self.assertLess(text.index("[[dentist"), text.index("[[car-insurance"))
            self.assertIn("2 topics", r.stdout)

    def test_degrades_on_malformed_frontmatter(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d); wiki = vault / "wiki"; wiki.mkdir()
            # unterminated quoted scalar -> yaml.safe_load raises -> must degrade to stem
            seed(wiki, "broken.md", '---\nsummary: "oops never closed\n---\n\n# Ignored\n')

            r = run_wiki(vault)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = (wiki / "_index.md").read_text(encoding="utf-8")
            self.assertIn("[[broken|broken]]", text)   # title falls back to the stem
            self.assertNotIn("_No topics yet._", text)

    def test_no_churn_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d); wiki = vault / "wiki"; wiki.mkdir()
            seed(wiki, "landlord.md",
                 "---\nsummary: Lease + contacts.\nupdated: 2026-06-10\n---\n\n# Landlord\n")
            seed(wiki, "passport.md",
                 "---\nsummary: Renewal steps.\nupdated: 2026-06-11\n---\n\n# Passport\n")

            self.assertEqual(run_wiki(vault).returncode, 0)
            first = (wiki / "_index.md").read_text(encoding="utf-8")
            self.assertEqual(run_wiki(vault).returncode, 0)
            second = (wiki / "_index.md").read_text(encoding="utf-8")
            self.assertEqual(first, second, "re-run produced a different index (timestamp leak?)")

    def test_no_wiki_dir_noops(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)   # deliberately NO wiki/ dir
            r = run_wiki(vault)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("no wiki/", r.stdout)
            self.assertFalse((vault / "wiki").exists(), "wiki/ must not be created")

    def test_empty_wiki_writes_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d); (vault / "wiki").mkdir()
            r = run_wiki(vault)
            self.assertEqual(r.returncode, 0, r.stderr)
            text = (vault / "wiki" / "_index.md").read_text(encoding="utf-8")
            self.assertIn("_No topics yet._", text)
            self.assertIn("0 topics", r.stdout)


if __name__ == "__main__":
    unittest.main()
