"""regenerate must mirror the live feed + shared render brain into chrome-extension/.
Runs sidekick.py as a subprocess against a throwaway vault (SIDEKICK_VAULT), so it
exercises the real CLI. Requires pyyaml (the project's only runtime dep)."""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "sidekick.py"

class RegenerateExtensionSync(unittest.TestCase):
    def test_mirrors_feed_and_render_into_extension(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "ledger.jsonl").write_text(
                json.dumps({"task": "X", "category": "chore",
                            "completed_at": "2026-06-18T00:00:00Z",
                            "sat_for_hours": 1, "orchestrator": None}) + "\n",
                encoding="utf-8")
            (vault / "sidekick-render.js").write_text("/* render brain marker */\n", encoding="utf-8")
            (vault / "chrome-extension").mkdir()

            env = {**os.environ, "SIDEKICK_VAULT": str(vault)}
            subprocess.run([sys.executable, str(SCRIPT), "regenerate"],
                           check=True, env=env, cwd=d)

            ext = vault / "chrome-extension"
            self.assertTrue((ext / "sidekick-data.js").exists(), "feed not mirrored")
            self.assertTrue((ext / "sidekick-render.js").exists(), "render brain not mirrored")
            self.assertEqual((ext / "sidekick-data.js").read_text(encoding="utf-8"),
                             (vault / "sidekick-data.js").read_text(encoding="utf-8"))
            self.assertEqual((ext / "sidekick-render.js").read_text(encoding="utf-8"),
                             "/* render brain marker */\n")
            # the retired JSON feed must not be produced
            self.assertFalse((ext / "sidekick-data.json").exists(), "stale .json feed still written")

    def test_skips_when_extension_absent(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "ledger.jsonl").write_text("", encoding="utf-8")
            (vault / "sidekick-render.js").write_text("/* x */\n", encoding="utf-8")
            env = {**os.environ, "SIDEKICK_VAULT": str(vault)}
            subprocess.run([sys.executable, str(SCRIPT), "regenerate"],
                           check=True, env=env, cwd=d)
            self.assertTrue((vault / "sidekick-data.js").exists())
            self.assertFalse((vault / "chrome-extension").exists())

if __name__ == "__main__":
    unittest.main()
