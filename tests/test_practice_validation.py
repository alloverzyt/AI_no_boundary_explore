"""Regression tests for scripts/validate_practice.py.

The fixtures mirror the official developer-package result contract:

* ``practice.py`` writes ``<output>/world-*/result.json`` as
  ``{"episodes": [...], "summary": aggregate(episodes)}``.
* Each episode comes from ``evaluation_adapters/pdf_runner.py`` ``outcome()``:
  ``scenario``, ``status``, ``termination``, ``scoring``, ``metrics``,
  ``objectives``, ``api``, ``scored``, ``note``.
* A tutorial (woodcraft) world succeeds with ``status == "completed"``,
  ``termination == "tutorial_goals"`` and ``metrics.task_success is True``.

No MineDojo, Docker, network or API key is required here.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import validate_practice  # noqa: E402

SCRIPT = SCRIPTS / "validate_practice.py"
GOALS = ["log", "planks", "stick", "crafting_table", "wooden_pickaxe"]


def episode(**overrides):
    value = {
        "scenario": {
            "id": "woodcraft",
            "label": "教学例子一：木制工具链（不计分）",
            "mode": "tutorial",
            "goals": GOALS,
        },
        "status": "completed",
        "termination": "tutorial_goals",
        "scoring": None,
        "metrics": {
            "task_success": True,
            "action_count": 1170,
            "deaths": 0,
            "invalid_actions": 0,
            "execution_seconds": 123.4,
        },
        "objectives": [{"id": goal, "completed": True} for goal in GOALS],
        "api": {"total": 0},
        "scored": False,
        "note": "教学练习，不计入平均分",
    }
    value.update(overrides)
    return value


def result_document(episodes):
    return {
        "episodes": episodes,
        "summary": {
            "full_worlds": 0,
            "eligible": False,
            "mean_score": None,
            "notice": "本地规则自测分；正式成绩以组织方隐藏种子及平台核验为准。",
        },
    }


class PracticeValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name) / "practice-output"

    def write_result(self, document, world="world-abc123", raw=None):
        directory = self.output / world
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "result.json"
        path.write_text(raw if raw is not None else json.dumps(document, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def validate(self):
        return validate_practice.validate_directory(self.output)

    def run_cli(self):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--output", str(self.output)],
            capture_output=True, text=True)

    def test_missing_output_directory_fails(self):
        self.assertTrue(self.validate())
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PRACTICE_VALIDATION_ERROR", result.stderr)

    def test_output_directory_without_result_files_fails(self):
        self.output.mkdir(parents=True)
        self.assertTrue(self.validate())
        self.assertNotEqual(self.run_cli().returncode, 0)

    def test_world_directory_without_result_json_fails(self):
        (self.output / "world-abc123" / "evidence").mkdir(parents=True)
        self.assertTrue(self.validate())
        self.assertNotEqual(self.run_cli().returncode, 0)

    def test_empty_episode_list_fails(self):
        self.write_result(result_document([]))
        self.assertTrue(self.validate())
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("PRACTICE_VALIDATION_ERROR", result.stderr)

    def test_empty_result_document_fails(self):
        self.write_result({})
        self.assertTrue(self.validate())

    def test_malformed_json_fails(self):
        self.write_result(None, raw="{not valid json")
        self.assertTrue(self.validate())
        self.assertNotEqual(self.run_cli().returncode, 0)

    def test_missing_summary_fails(self):
        self.write_result({"episodes": [episode()]})
        self.assertTrue(self.validate())

    def test_failed_termination_fails(self):
        failed = episode(termination="tutorial_step_limit")
        failed["metrics"]["task_success"] = False
        self.write_result(result_document([failed]))
        self.assertTrue(self.validate())
        self.assertNotEqual(self.run_cli().returncode, 0)

    def test_incomplete_status_fails(self):
        self.write_result(result_document([episode(status="running")]))
        self.assertTrue(self.validate())

    def test_error_status_fails(self):
        self.write_result(result_document([episode(status="error")]))
        self.assertTrue(self.validate())

    def test_task_success_false_fails(self):
        self.write_result(result_document([episode(
            metrics={"task_success": False, "action_count": 1500, "deaths": 1,
                     "invalid_actions": 3, "execution_seconds": 900.0})]))
        self.assertTrue(self.validate())

    def test_missing_task_success_fails(self):
        self.write_result(result_document([episode(
            metrics={"action_count": 1500, "deaths": 0, "invalid_actions": 0,
                     "execution_seconds": 900.0})]))
        self.assertTrue(self.validate())

    def test_non_boolean_task_success_fails(self):
        self.write_result(result_document([episode(
            metrics={"task_success": 1, "action_count": 1500, "deaths": 0,
                     "invalid_actions": 0, "execution_seconds": 900.0})]))
        self.assertTrue(self.validate())

    def test_valid_single_episode_passes(self):
        self.write_result(result_document([episode()]))
        self.assertEqual(self.validate(), [])
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("PRACTICE_VALIDATION_OK", result.stdout)

    def test_valid_multiple_episodes_pass(self):
        self.write_result(result_document([episode(), episode()]))
        self.assertEqual(self.validate(), [])
        self.assertEqual(self.run_cli().returncode, 0)

    def test_one_bad_world_among_two_fails(self):
        self.write_result(result_document([episode()]), world="world-good")
        self.write_result(result_document([]), world="world-bad")
        self.assertTrue(self.validate())
        self.assertNotEqual(self.run_cli().returncode, 0)

    def test_non_episode_object_in_episodes_fails(self):
        self.write_result(result_document([episode(), "not-an-episode"]))
        self.assertTrue(self.validate())


if __name__ == "__main__":
    unittest.main()
