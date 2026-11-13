"""Planner selection and fallback tests."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import planner


class PlannerTests(unittest.TestCase):
    def test_empty_key_uses_heuristic(self):
        with patch.dict(os.environ, {}, clear=True):
            result = planner.make_planner({"model": {
                "name": "deepseek-flash",
                "api_url": "https://example.test",
                "api_key": "",
            }, "agent": {}})
        self.assertIsInstance(result, planner.HeuristicPlanner)

    def test_evaluation_credentials_enable_model_without_config_url(self):
        config = {"model": {
            "name": "deepseek-flash", "api_url": "", "api_key": "",
        }, "agent": {}}
        with patch.dict(os.environ, {
            "EVALUATION_API_URL": "https://evaluation.test",
            "EVALUATION_API_TOKEN": "token",
        }, clear=True):
            result = planner.make_planner(config)
        self.assertIsInstance(result, planner.ModelPlanner)

    def test_model_falls_back_after_three_failures(self):
        model = object.__new__(planner.ModelPlanner)
        model.client = type("Client", (), {
            "chat": lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError())
        })()
        model.calls = model.errors = 0
        model.dead = False
        model.fallback = planner.HeuristicPlanner()
        for _ in range(3):
            decision = model.decide({}, {})
        self.assertIsNotNone(decision)
        self.assertTrue(model.dead)
        self.assertEqual(model.fallback.calls, 1)


if __name__ == "__main__":
    unittest.main()
