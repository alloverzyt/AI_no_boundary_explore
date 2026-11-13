"""Offline regression checks using only the public observation/action contract."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import agent as policy
from minecraft_actions import CRAFT_ITEMS


def observation(items=(), craftable=(), block=None, distance=None):
    return {
        "noop_action": [0, 0, 0, 12, 12, 0, 0, 0],
        "inventory": [dict(item_id=name, quantity=count, slot=i, equipped=False)
                      for i, (name, count) in enumerate(items)],
        "craftable": list(craftable),
        "position": [0, 64, 0],
        "orientation": {"pitch": 0},
        "crosshair_hit": {"block_name": block, "block_distance": distance},
    }


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.visual = patch.object(policy, "vision", None)
        self.visual.start()
        self.addCleanup(self.visual.stop)
        self.agent = policy.Agent()
        self.agent.configure({"model": {}, "agent": {}})
        self.agent.reset([])

    def assertCraft(self, action, item):
        self.assertEqual(action[5:7], [4, CRAFT_ITEMS.index(item)])

    def test_crafts_planks_without_visual_cooldown(self):
        self.assertCraft(self.agent.act(observation([("log", 1)], ["planks"])), "planks")

    def test_completed_goal_waits_even_with_tree_in_reach(self):
        self.agent.reset(["log"])
        obs = observation([("log", 1)], block="wood", distance=2)
        self.assertEqual(self.agent.act(obs), obs["noop_action"])

    def test_crafting_preempts_tree_and_active_recovery(self):
        self.agent.nav_state = "digging"
        self.assertCraft(self.agent.act(observation(
            [("planks", 3), ("stick", 2)], ["wooden_pickaxe"], "wood", 2)),
            "wooden_pickaxe")

    def test_places_table_before_gathering(self):
        action = self.agent.act(observation([("crafting_table", 1)], block="dirt", distance=2))
        self.assertEqual((action[5], action[7]), (6, 0))

    def test_equips_pickaxe_before_navigation(self):
        self.agent.spare_table = True
        action = self.agent.act(observation([("wooden_pickaxe", 1)]))
        self.assertEqual((action[5], action[7]), (5, 0))

    def test_stone_recipe_is_reachable(self):
        self.agent.spare_table = True
        self.assertCraft(self.agent.act(observation(
            [("wooden_pickaxe", 1), ("cobblestone", 3)], ["stone_pickaxe"])),
            "stone_pickaxe")

    def test_spare_table_can_be_placed_after_leaving_first_table(self):
        self.agent.spare_table = True
        self.agent.table_placed = True
        self.agent.table_pos = (20, 64, 0)
        obs = observation([("wooden_pickaxe", 1), ("crafting_table", 1),
                           ("cobblestone", 3)], block="dirt", distance=2)
        action = self.agent.act(obs)
        self.assertEqual((action[5], action[7]), (6, 1))

    def test_iron_phase_mines_until_three_total_iron(self):
        self.agent.spare_table = True
        obs = observation([("wooden_pickaxe", 1), ("stone_pickaxe", 1),
                           ("furnace", 1), ("iron_ore", 1)], [],
                          block="iron_ore", distance=2)
        obs["inventory"][1]["equipped"] = True
        action = self.agent.act(obs)
        self.assertEqual(action[5], 3)

    def test_iron_phase_only_smelt_when_legal(self):
        obs = observation([("wooden_pickaxe", 1), ("stone_pickaxe", 1),
                           ("furnace", 1), ("iron_ore", 1)], ["iron_ingot"])
        action = self.agent.act(obs)
        self.assertCraft(action, "iron_ingot")

    def test_reset_clears_episode_scoped_state(self):
        self.agent.table_placed = True
        self.agent.relocate = 12
        self.agent.spare_table = True
        self.agent.spare_deadline = 900
        self.agent.nav_state = "digging"
        self.agent.arb_cd = 3
        self.agent.walk_anchor = (10, 64, 10)
        self.agent.lock_key = (1, 2, 3)
        self.agent.reset(["iron_pickaxe"])
        self.assertFalse(self.agent.table_placed)
        self.assertFalse(self.agent.spare_table)
        self.assertIsNone(self.agent.spare_deadline)
        self.assertEqual(self.agent.relocate, 0)
        self.assertEqual(self.agent.nav_state, "moving")
        self.assertEqual(self.agent.arb_cd, 0)
        self.assertIsNone(self.agent.walk_anchor)
        self.assertIsNone(self.agent.lock_key)

    def test_gathering_keeps_continuous_attack(self):
        obs = observation(block="wood", distance=2)
        for _ in range(5):
            self.assertEqual(self.agent.act(obs)[5], 3)

    def test_wood_phase_looks_past_foliage_instead_of_mining_it(self):
        self.agent.reset(["wooden_pickaxe", "cobblestone", "stone_pickaxe", "furnace"])
        obs = observation(block="leaves", distance=2)
        action = self.agent.act(obs)
        self.assertNotEqual(action[5], 3)
        self.assertEqual(action[3], 10)
        obs["orientation"]["pitch"] = -30
        action = self.agent.act(obs)
        self.assertNotEqual(action[5], 3)
        self.assertEqual(action[4], 13)

    def test_stone_scene_looks_past_foliage_while_navigating(self):
        self.agent.reset(["wooden_pickaxe", "cobblestone", "stone_pickaxe", "furnace"])
        action = self.agent.act(observation(block="leaves", distance=2))
        self.assertNotEqual(action[5], 3)
        self.assertEqual(action[3], 10)

    def test_stone_scene_recovery_is_not_starved_by_close_leaves(self):
        self.agent.reset(["wooden_pickaxe", "cobblestone", "stone_pickaxe", "furnace"])
        self.agent.nav_state = "jumping"
        obs = observation(block="leaves", distance=2)
        for _ in range(80):
            action = self.agent.act(obs)
            self.assertNotEqual(action[5], 3)
            if self.agent.nav_state == "moving":
                break
        self.assertEqual(self.agent.nav_state, "moving")

    def test_woodcraft_still_mines_trunks_and_foliage(self):
        action = self.agent.act(observation(block="leaves", distance=2))
        self.assertEqual(action[5], 3)

    def test_wood_phase_does_not_dig_ground_as_an_exploration_obstacle(self):
        action = self.agent.act(observation(block="grass_block", distance=1))
        self.assertNotEqual(action[5], 3)

    def test_gathering_can_reach_planner(self):
        self.agent.planner = Mock()
        self.agent.planner.decide.return_value = {"goal": "find_tree", "turn": "left", "verb": "walk"}
        action = self.agent.act(observation())
        self.agent.planner.decide.assert_called_once()
        self.assertEqual(action[4], 11)

    def test_navigation_recovery_runs_jump_dig_and_detour_phases(self):
        obs = observation(block="dirt", distance=2)
        for _ in range(12):
            self.agent.nav_step(obs)
        self.assertEqual(self.agent.nav_state, "jumping")
        for _ in range(8):
            self.assertEqual(self.agent.nav_step(obs)[2], 1)
        self.assertEqual(self.agent.nav_step(obs)[3], 10)  # aim up before digging
        obs["orientation"]["pitch"] = -30
        for _ in range(40):
            self.assertEqual(self.agent.nav_step(obs)[5], 3)
        self.assertEqual(self.agent.nav_step(obs)[4], 18)
        for _ in range(10):
            action = self.agent.nav_step(obs)
            self.assertEqual(action[0], 1)
            self.assertEqual(action[5], 0)
        for _ in range(3):
            self.assertEqual(self.agent.nav_step(obs)[4], 8)
        self.agent.nav_step(obs)
        self.assertEqual(self.agent.nav_state, "moving")

    def test_failed_scan_allows_movement_before_rescanning(self):
        obs = observation()
        for _ in range(9):
            self.agent.nav_step(obs)
        for _ in range(12):
            self.assertEqual(self.agent.nav_step(obs)[4], 14)
        self.assertEqual(self.agent.nav_step(obs)[0], 1)
        self.assertEqual(self.agent.nav_step(obs)[0], 1)
        self.assertLess(self.agent.no_sight, 10)

    def test_navigation_tick_does_not_reenter_itself(self):
        obs = observation(block="dirt", distance=2)
        self.agent._walk_hist = [(0, 0)] * 11
        self.agent.nav_step(obs)
        self.assertEqual(self.agent.nav_count, 1)


if __name__ == "__main__":
    unittest.main()
