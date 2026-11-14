"""Stone-stage public-observation sequence regressions (task-8).

All fixtures use only the official public observation contract:

* ``inventory`` rows: ``{slot, item_id, quantity, equipped, ...}``
* ``craftable``: the environment's current legal craft/smelt catalogue
* ``crosshair_hit``: first ray hit (``block_name``/``block_distance``/traced coords)
* ``last_action``: ``{action, valid, inventory_delta, position_delta, health_delta}``
  for the previously executed action; ``None`` on the first observation.

``valid`` only proves the 8-integer action vector was legal (pdf_runner.py:72-81);
placement/crafting success is therefore detected from ``inventory_delta`` and the
inventory itself. No MineDojo internals, hidden state or model calls are used.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import agent as policy
from minecraft_actions import CRAFT_ITEMS

WOODCRAFT_GOALS = ["log", "planks", "stick", "crafting_table", "wooden_pickaxe"]


def row(item_id, quantity=1, slot=0, equipped=False):
    return {"slot": slot, "item_id": item_id, "quantity": quantity, "equipped": equipped}


def obs(inventory=(), craftable=(), block=None, distance=None, pitch=0.0,
        position=(0.0, 64.0, 0.0), last_action=None, health=20.0, traced=None):
    hit = {"block_name": block, "block_distance": distance,
           "traced_block_x": None, "traced_block_y": None, "traced_block_z": None}
    if traced is not None:
        hit["traced_block_x"], hit["traced_block_y"], hit["traced_block_z"] = traced
    return {
        "noop_action": [0, 0, 0, 12, 12, 0, 0, 0],
        "inventory": list(inventory),
        "craftable": list(craftable),
        "position": list(position),
        "orientation": {"pitch": pitch, "yaw": 0.0},
        "health": health,
        "crosshair_hit": hit,
        "last_action": last_action,
    }


def last_attack(inventory_delta=None, position_delta=(0.0, 0.0, 0.0), valid=True):
    return {"action": [0, 0, 0, 12, 12, 3, 0, 0], "valid": valid,
            "inventory_delta": dict(inventory_delta or {}),
            "position_delta": list(position_delta), "health_delta": 0.0}


def last_place(consumed=True, valid=True, item="crafting_table"):
    return {"action": [0, 0, 0, 12, 12, 6, 0, 0], "valid": valid,
            "inventory_delta": {item: -1} if consumed else {},
            "position_delta": [0.0, 0.0, 0.0], "health_delta": 0.0}


class StoneProgressionTests(unittest.TestCase):
    def setUp(self):
        self.visual = patch.object(policy, "vision", None)
        self.visual.start()
        self.addCleanup(self.visual.stop)
        self.agent = policy.Agent()
        self.agent.configure({"model": {}, "agent": {}})
        self.agent.reset([])

    def craft_op(self, item):
        return [4, CRAFT_ITEMS.index(item)]

    # ---------------------------------------------------- P1-02 材料依赖恢复
    def test_missing_sticks_with_logs_crafts_planks_then_sticks(self):
        self.agent.spare_table = True
        pick = row("wooden_pickaxe", 1, 0, True)
        cobble = row("cobblestone", 3, 1)
        first = self.agent.act(obs(inventory=[pick, cobble, row("log", 1, 2)],
                                   craftable=["planks"]))
        self.assertEqual(first[5:7], self.craft_op("planks"))
        second = self.agent.act(obs(inventory=[pick, cobble, row("planks", 2, 2)],
                                    craftable=["stick"]))
        self.assertEqual(second[5:7], self.craft_op("stick"))
        third = self.agent.act(obs(inventory=[pick, cobble, row("stick", 4, 2)],
                                   craftable=["stone_pickaxe"]))
        self.assertEqual(third[5:7], self.craft_op("stone_pickaxe"))

    def test_far_stale_table_is_rebuilt_from_planks(self):
        self.agent.spare_table = True
        self.agent.table_placed = True
        self.agent.table_pos = (40.0, 64.0, 0.0)
        inventory = [row("wooden_pickaxe", 1, 0, True),
                     row("cobblestone", 3, 1),
                     row("planks", 4, 2)]
        action = self.agent.act(obs(inventory=inventory, craftable=["crafting_table"],
                                    block="dirt", distance=2))
        self.assertEqual(action[5:7], self.craft_op("crafting_table"))

    def test_legal_recipe_is_preferred_over_navigation(self):
        self.agent.spare_table = True
        inventory = [row("wooden_pickaxe", 1, 0, True),
                     row("cobblestone", 3, 1), row("stick", 4, 2)]
        action = self.agent.act(obs(inventory=inventory, craftable=["stone_pickaxe"]))
        self.assertEqual(action[5:7], self.craft_op("stone_pickaxe"))

    # ---------------------------------------------------- P1-03 放置确认与有界重试
    def test_unconfirmed_place_retries_are_bounded_then_relocates(self):
        inventory = [row("crafting_table", 1, 0)]
        first = self.agent.act(obs(inventory=inventory, block="dirt", distance=2))
        self.assertEqual(first[5], 6)
        place_count = 1
        actions = []
        for _ in range(8):
            action = self.agent.act(obs(inventory=inventory, block="dirt", distance=2,
                                        last_action=last_place(consumed=False)))
            actions.append(action)
            if action[5] == 6:
                place_count += 1
        self.assertFalse(self.agent.table_placed)
        self.assertLessEqual(place_count, 3)
        self.assertTrue(any(a[5] != 6 and a[0] == 1 for a in actions))

    def test_confirmed_place_marks_table_available(self):
        inventory = [row("crafting_table", 1, 0)]
        self.assertEqual(self.agent.act(obs(inventory=inventory, block="dirt",
                                            distance=2))[5], 6)
        action = self.agent.act(obs(inventory=[], block="dirt", distance=2,
                                    last_action=last_place(consumed=True)))
        self.assertTrue(self.agent.table_placed)
        self.assertNotEqual(action[5], 6)

    def test_table_refresh_wait_does_not_block_material_crafting(self):
        # 历史问题：table_placed=True 后先进入 60 步 tbl_wait，木板/棍补料在
        # 该分支之后，导致“放着可制作配方空转”。
        self.agent.table_placed = True
        action = self.agent.act(obs(inventory=[row("log", 1, 0)],
                                    craftable=["planks"]))
        self.assertEqual(action[5:7], self.craft_op("planks"))

    def test_woodcraft_path_still_crafts_pickaxe_after_confirmed_table(self):
        self.agent.reset(list(WOODCRAFT_GOALS))
        self.agent.table_placed = True
        inventory = [row("planks", 3, 0), row("stick", 4, 1)]
        action = self.agent.act(obs(inventory=inventory,
                                    craftable=["wooden_pickaxe"]))
        self.assertEqual(action[5:7], self.craft_op("wooden_pickaxe"))

    # ---------------------------------------------------- 高级工具不强制回木制
    def test_advanced_stone_pickaxe_does_not_force_wood_gathering(self):
        self.agent.spare_table = True
        inventory = [row("stone_pickaxe", 1, 0, True), row("furnace", 1, 1),
                     row("iron_ore", 1, 2)]
        action = self.agent.act(obs(inventory=inventory, block="iron_ore", distance=2))
        self.assertEqual(action[5], 3)  # attack iron ore, do not go back to wood

    # ---------------------------------------------------- P1-04 竖井有界恢复
    def dig_setup(self, block, distance=2, pitch=90.0, last_action=None):
        self.agent.spare_table = True
        return obs(inventory=[row("wooden_pickaxe", 1, 0, True)], block=block,
                   distance=distance, pitch=pitch, last_action=last_action)

    def test_unbreakable_bedrock_is_not_attacked(self):
        base = self.dig_setup("bedrock")
        attacks = 0
        for _ in range(6):
            action = self.agent.act(base)
            if action[5] == 3:
                attacks += 1
        self.assertEqual(attacks, 0)
        self.assertGreaterEqual(self.agent.dig_fail, 1)

    def test_liquids_are_not_attacked(self):
        for name in ("water", "flowing_water", "lava", "flowing_lava"):
            with self.subTest(block=name):
                self.setUp()
                base = self.dig_setup(name)
                attacks = sum(1 for _ in range(4) if self.agent.act(base)[5] == 3)
                self.assertEqual(attacks, 0, msg=name)

    def test_vertical_dig_no_progress_recovers_within_bound(self):
        base = self.dig_setup("dirt", last_action=last_attack())
        attacks = recovery = 0
        for _ in range(140):
            action = self.agent.act(base)
            if action[5] == 3:
                attacks += 1
            else:
                recovery += 1
        self.assertGreater(attacks, 0)
        self.assertGreater(recovery, 0)
        self.assertGreaterEqual(self.agent.dig_fail, 1)

    def test_vertical_dig_keeps_attacking_with_public_progress(self):
        base = self.dig_setup("dirt",
                              last_action=last_attack(inventory_delta={"dirt": 1}))
        for _ in range(5):
            self.assertEqual(self.agent.act(base)[5], 3)
        self.assertEqual(self.agent.dig_stall, 0)

    # ---------------------------------------------------- reset
    def test_reset_clears_stone_stage_state(self):
        self.agent.table_pending = True
        self.agent.table_pending_slot = 3
        self.agent.table_confirm_wait = 2
        self.agent.table_fail = 2
        self.agent.dep_fail = 5
        self.agent.dig_stall = 7
        self.agent.dig_escape = 3
        self.agent.dig_last_key = (1, 2, 3)
        self.agent.reset([])
        self.assertFalse(self.agent.table_pending)
        self.assertIsNone(self.agent.table_pending_slot)
        self.assertEqual(self.agent.table_confirm_wait, 0)
        self.assertEqual(self.agent.table_fail, 0)
        self.assertEqual(self.agent.dep_fail, 0)
        self.assertEqual(self.agent.dig_stall, 0)
        self.assertEqual(self.agent.dig_escape, 0)
        self.assertIsNone(self.agent.dig_last_key)
        self.assertIsNone(self.agent.table_recover)

    # ---------------------------------------------------- STONE_DESIGN S04/S05/S10 缺口
    def test_finished_recipe_precedes_spare_table_gathering(self):
        # S04：成品 recipe 已可用时直接制作，不让备用台的 900 步采木挡路。
        self.agent.spare_table = False
        inventory = [row("wooden_pickaxe", 1, 0, True),
                     row("cobblestone", 3, 1), row("stick", 4, 2)]
        action = self.agent.act(obs(inventory=inventory, craftable=["stone_pickaxe"]))
        self.assertEqual(action[5:7], self.craft_op("stone_pickaxe"))

    def test_spare_table_flag_not_set_when_only_craft_is_requested(self):
        # S05：发出 craft crafting_table 不等于已经携带台子。
        inventory = [row("wooden_pickaxe", 1, 0, True),
                     row("planks", 4, 1), row("log", 2, 2)]
        action = self.agent.act(obs(inventory=inventory, craftable=["crafting_table"]))
        self.assertEqual(action[5:7], self.craft_op("crafting_table"))
        self.assertFalse(self.agent.spare_table)

    def test_spare_table_flag_set_when_table_really_carried(self):
        # S05：只有背包里真实存在 crafting_table 才标记 spare_table。
        inventory = [row("wooden_pickaxe", 1, 0, True), row("crafting_table", 1, 1)]
        self.agent.act(obs(inventory=inventory, craftable=[]))
        self.assertTrue(self.agent.spare_table)

    def test_iron_phase_equips_best_available_pickaxe(self):
        # S10：同时有铁镐/石镐时选最高级，不强制低级镐。
        self.agent.spare_table = True
        inventory = [row("iron_pickaxe", 1, 0, False), row("stone_pickaxe", 1, 1, False),
                     row("furnace", 1, 2), row("iron_ore", 1, 3)]
        action = self.agent.act(obs(inventory=inventory, block="iron_ore", distance=2))
        self.assertEqual((action[5], action[7]), (5, 0))

    def test_stone_phase_equips_best_pickaxe_without_wooden(self):
        # S10：只有铁镐（无木镐/石镐）时也装备最高级镐，而不是空手前进。
        self.agent.spare_table = True
        inventory = [row("iron_pickaxe", 1, 0, False)]
        action = self.agent.act(obs(inventory=inventory, craftable=[]))
        self.assertEqual((action[5], action[7]), (5, 0))

    def test_failed_table_placement_has_bounded_recovery(self):
        # 4593 步实跑的阻塞点：石器阶段连续 1200+ 次 place 全部失败仍不复位。
        self.agent.spare_table = True
        inventory = [row("wooden_pickaxe", 1, 0, True), row("cobblestone", 3, 1),
                     row("stick", 2, 2), row("crafting_table", 1, 5)]
        first = self.agent.act(obs(inventory=inventory, craftable=[], block="stone",
                                   distance=2, pitch=90.0))
        self.assertEqual(first[5], 6)
        actions = []
        for _ in range(15):
            actions.append(self.agent.act(
                obs(inventory=inventory, craftable=[], block="stone", distance=2,
                    pitch=90.0, last_action=last_place(consumed=False))))
        places = sum(1 for a in actions if a[5] == 6)
        self.assertLess(places, 12)
        self.assertTrue(any(a[5] != 6 for a in actions))

    # ------------------------------- stone-v2 实跑瓶颈：假近台 / 无限等待
    def test_near_table_requires_vertical_proximity(self):
        # v2 实跑：台子在 y=79，玩家下挖到 y=70（水平 1.35、垂直差 9），
        # 旧 _near_table 只看 dx/dz 判成“在旁边”，导致 48% 预算空转。
        # 修复后应判定不在旁 -> 强制放置背包里的备用台。
        self.agent.spare_table = True
        self.agent.table_placed = True
        self.agent.table_pos = (0.0, 79.0, 0.0)
        inventory = [row("wooden_pickaxe", 1, 0, True), row("cobblestone", 3, 1),
                     row("stick", 2, 2), row("crafting_table", 1, 5)]
        base = obs(inventory=inventory, craftable=[], block="stone", distance=2,
                   pitch=90.0, position=(0.0, 70.0, 0.0))
        actions = [self.agent.act(base) for _ in range(8)]
        self.assertTrue(any(a[5] == 6 for a in actions),
                        msg="vertical 9 blocks away must trigger a real placement")

    def test_near_table_accepts_true_3d_nearby_table(self):
        self.agent.spare_table = True
        self.agent.table_placed = True
        self.agent.table_pos = (2.0, 64.0, 0.0)
        inventory = [row("wooden_pickaxe", 1, 0, True), row("cobblestone", 3, 1),
                     row("stick", 4, 2)]
        action = self.agent.act(obs(inventory=inventory, craftable=["stone_pickaxe"],
                                    position=(0.0, 64.0, 0.0)))
        self.assertEqual(action[5:7], self.craft_op("stone_pickaxe"))

    def test_stone_recipe_wait_is_capped_to_five_steps(self):
        # recipe 缺失且无备用台时最多等 5 步，之后必须采矿/行动，不能长 noop。
        self.agent.spare_table = True
        self.agent.table_placed = True
        self.agent.table_pos = (1.0, 64.0, 0.0)
        inventory = [row("wooden_pickaxe", 1, 0, True), row("cobblestone", 3, 1),
                     row("stick", 2, 2)]
        base = obs(inventory=inventory, craftable=[], block="stone", distance=2,
                   pitch=90.0, position=(0.0, 64.0, 0.0))
        noop = list(base["noop_action"])
        actions = [self.agent.act(base) for _ in range(6)]
        self.assertTrue(any(a != noop for a in actions),
                        msg="wait must be capped and fall through to mining")

    def test_spare_table_deadline_skip_does_not_restart_gathering(self):
        # stone-v3 实跑：deadline 跳过后 spare_deadline 被清空，下一帧又重置
        # 900 步并重新囤木，导致 2600+ 步卡在找树（position 冻结）。
        # 跳过必须是一次性决定，不能重启备用台囤料。
        self.agent.spare_table = False
        self.agent.spare_deadline = 900
        self.agent.ticks = 1000
        inventory = [row("wooden_pickaxe", 1, 0, True)]
        self.agent.act(obs(inventory=inventory, craftable=[]))
        self.assertTrue(self.agent.spare_table)
        self.agent.act(obs(inventory=inventory, craftable=[]))
        self.assertIsNone(self.agent.spare_deadline)

    # ------------------------------- v5：dig_down walk 分支短窗停滞恢复
    def test_dig_down_walk_stall_jumps_then_turns(self):
        # stone-v4 实跑：目标 stone d=4.62>REACH 时 walk 分支连续 851 步原地不动。
        self.agent.spare_table = True
        inventory = [row("wooden_pickaxe", 1, 0, True)]
        base = obs(inventory=inventory, block="stone", distance=4.62, pitch=90.0,
                   position=(-218.7, 71.0, -41.7))
        actions = [self.agent.act(base) for _ in range(14)]
        self.assertTrue(any(a[2] == 1 for a in actions),
                        msg="12 帧零位移后必须 jump+forward")
        actions2 = [self.agent.act(base) for _ in range(28)]
        self.assertTrue(any(a[4] != 12 for a in actions2),
                        msg="36 帧仍无进展必须转向/换路线")

    def test_dig_down_stall_recovery_does_not_break_continuous_attack(self):
        # 目标在 REACH 内时保持连续攻击，dig_stall/dig_escape 不参与。
        self.agent.spare_table = True
        inventory = [row("wooden_pickaxe", 1, 0, True)]
        base = obs(inventory=inventory, block="stone", distance=3.6, pitch=90.0,
                   position=(-218.7, 71.0, -41.7))
        for _ in range(6):
            self.assertEqual(self.agent.act(base)[5], 3)
        self.assertEqual(self.agent.dig_walk_stall, 0)

    def test_reset_clears_v5_pickup_and_walk_state(self):
        self.agent.pickup_target = (1, 2, 3)
        self.agent.pickup_last_pos = (1.0, 2.0, 3.0)
        self.agent.pickup_stall = 4
        self.agent.pickup_blocked = 1
        self.agent.dig_walk_last = (1.0, 2.0, 3.0)
        self.agent.dig_walk_stall = 7
        self.agent.dig_walk_turns = 2
        self.agent.reset([])
        self.assertIsNone(self.agent.pickup_target)
        self.assertIsNone(self.agent.pickup_last_pos)
        self.assertEqual(self.agent.pickup_stall, 0)
        self.assertEqual(self.agent.pickup_blocked, 0)
        self.assertIsNone(self.agent.dig_walk_last)
        self.assertEqual(self.agent.dig_walk_stall, 0)
        self.assertEqual(self.agent.dig_walk_turns, 0)


if __name__ == "__main__":
    unittest.main()
