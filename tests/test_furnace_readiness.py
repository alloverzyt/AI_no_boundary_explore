"""Furnace readiness gate regressions (v5c, from v5b public trajectory).

v5b (seed43) after stone_pickaxe at step 2493: tables=0, planks=3, log=0,
position y=69 while table was at (-222,69,-40); after digging to y=46 with
cobble>=8 the agent had no crafting table and no wood underground, and repeated
`stone dependencies unavailable -> explore for wood` 37 times, never crafting
the furnace. These fixtures pin the public observation contract only
(inventory / craftable / position / table_pos tracked from crosshair hits).
"""
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import agent as policy
from minecraft_actions import CRAFT_ITEMS

DEEP_CRAFTABLE = ["stick", "stone_button", "stone_pressure_plate", "stonebrick",
                  "wooden_button", "wooden_pressure_plate"]


def row(item_id, quantity=1, slot=0, equipped=False):
    return {"slot": slot, "item_id": item_id, "quantity": quantity, "equipped": equipped}


def obs(inventory=(), craftable=(), block=None, distance=None, pitch=-15.0,
        position=(0.0, 64.0, 0.0), yaw=0.0, last_action=None, traced=None):
    hit = {"block_name": block, "block_distance": distance,
           "traced_block_x": None, "traced_block_y": None,
           "traced_block_z": None}
    if traced is not None:
        hit["traced_block_x"], hit["traced_block_y"], hit["traced_block_z"] = traced
    return {
        "noop_action": [0, 0, 0, 12, 12, 0, 0, 0],
        "inventory": list(inventory),
        "craftable": list(craftable),
        "position": list(position),
        "orientation": {"pitch": pitch, "yaw": yaw},
        "health": 20.0,
        "crosshair_hit": hit,
        "last_action": last_action,
    }


def stone_pick(**extra):
    return row("stone_pickaxe", 1, 0, True), extra


class FurnaceReadinessTests(unittest.TestCase):
    def setUp(self):
        self.visual = patch.object(policy, "vision", None)
        self.visual.start()
        self.addCleanup(self.visual.stop)
        self.agent = policy.Agent()
        self.agent.configure({"model": {}, "agent": {}})
        self.agent.reset([])
        self.agent.spare_table = True

    # T1: 石镐瞬间，planks=3 + log=1，craftable 有 planks -> 先补板（再做台），
    # 不得直接 dig_down（旧输出会是 pitch=90 的 aim/dig）。
    def test_t1_stone_pick_crafts_planks_before_descending(self):
        inventory = [row("stone_pickaxe", 1, 0, True), row("wooden_pickaxe", 1, 1),
                     row("planks", 3, 2), row("log", 1, 3), row("stick", 2, 4)]
        action = self.agent.act(obs(inventory=inventory, craftable=["planks"],
                                    position=(-220.6, 69.0, -40.0)))
        self.assertEqual(action[5:7], [4, CRAFT_ITEMS.index("planks")])

    # T2: v5b 2493/2494 真实快照——石镐完成瞬间台子就在旁边（准星命中
    # crafting_table d=1.76、table_pos=(-222,69,-40)），但背包 tables=0、
    # planks=3、log=0。近台不得成为“可以下井”的充分条件：必须先在地表
    # 有界找木补一张便携台，否则会重演离台 23.5 格后的 37 次无效循环。
    def test_t2_stone_pick_searches_wood_bounded_at_surface(self):
        inventory = [row("stone_pickaxe", 1, 0, True), row("wooden_pickaxe", 1, 1),
                     row("planks", 3, 2), row("stick", 2, 4)]
        action = self.agent.act(obs(inventory=inventory, craftable=[],
                                    position=(-220.6, 69.0, -40.0),
                                    block="crafting_table", distance=1.76,
                                    traced=(-222, 69, -40)))
        self.assertNotEqual(action[3], 18,
                            "must not start dig_down (pitch 90) before table prep")
        self.assertGreaterEqual(getattr(self.agent, "furnace_prep_steps", 0), 1)

    # T3: 有 4 木板且可做台 -> 先做便携台携带。
    def test_t3_stone_pick_crafts_portable_table(self):
        inventory = [row("stone_pickaxe", 1, 0, True), row("wooden_pickaxe", 1, 1),
                     row("planks", 4, 2), row("stick", 2, 4)]
        action = self.agent.act(obs(inventory=inventory,
                                    craftable=["crafting_table"],
                                    position=(-220.6, 69.0, -40.0)))
        self.assertEqual(action[5:7], [4, CRAFT_ITEMS.index("crafting_table")])

    # T4: v5b step 2936 精确深井快照：无台无料、cobble=8，必须有界回台/向上，
    # 不得 37 次 stone dependencies unavailable。
    def test_t4_deep_without_table_returns_bounded(self):
        inventory = [row("stone_pickaxe", 1, 0, True), row("wooden_pickaxe", 1, 1),
                     row("planks", 3, 2), row("stick", 2, 4),
                     row("cobblestone", 8, 5)]
        self.agent.table_placed = True
        self.agent.table_pos = (-222, 69, -40)
        base = obs(inventory=inventory, craftable=DEEP_CRAFTABLE,
                   position=(-220.7, 46.0, -39.3))
        actions = [self.agent.act(base) for _ in range(40)]
        self.assertGreater(getattr(self.agent, "furnace_return_steps", 0), 0,
                           "deep no-table state must enter bounded return path")
        self.assertTrue(
            any(a[4] != 12 or a[2] == 1 or a[3] != 12 for a in actions),
            "bounded return must turn/jump/climb, got %r" % (actions[:10],))
        buf = io.StringIO()
        with redirect_stdout(buf):
            for _ in range(200):
                self.agent.act(base)
        self.assertLessEqual(buf.getvalue().count("stone dependencies unavailable"), 1,
                             "must not repeat infinite explore-for-wood loop")

    # T5 (guard): 携带台 + cobble=8 -> 先放置台（旧路径），不得空等。
    def test_t5_carried_table_is_placed_for_furnace(self):
        inventory = [row("stone_pickaxe", 1, 0, True), row("wooden_pickaxe", 1, 1),
                     row("planks", 3, 2), row("stick", 2, 4),
                     row("cobblestone", 8, 5), row("crafting_table", 1, 6)]
        action = self.agent.act(obs(inventory=inventory, craftable=[],
                                    position=(-220.7, 46.0, -39.3)))
        self.assertEqual(action[5], 6)

    # T6 (guard): 已在台旁且 furnace 可做 -> 直接合成熔炉。
    def test_t6_near_table_crafts_furnace(self):
        inventory = [row("stone_pickaxe", 1, 0, True), row("wooden_pickaxe", 1, 1),
                     row("planks", 3, 2), row("stick", 2, 4),
                     row("cobblestone", 8, 5)]
        self.agent.table_placed = True
        self.agent.table_pos = (1, 64, 0)
        action = self.agent.act(obs(inventory=inventory, craftable=["furnace"],
                                    position=(0.0, 64.0, 0.0)))
        self.assertEqual(action[5:7], [4, CRAFT_ITEMS.index("furnace")])

    # T7: reset 清理新状态。
    def test_t7_reset_clears_furnace_gate_state(self):
        self.agent.furnace_prep_steps = 5
        self.agent.furnace_return_steps = 7
        self.agent.furnace_return_last = (1.0, 2.0, 3.0)
        self.agent.reset([])
        self.assertEqual(self.agent.furnace_prep_steps, 0)
        self.assertEqual(self.agent.furnace_return_steps, 0)
        self.assertIsNone(self.agent.furnace_return_last)

    # T8: v5c 精确快照——石镐未做、携带台 slot4 在地下连续 9 次放置失败，
    # 旧代码 table_fail>=9 后每步 "abandoned" + dependencies explore，永不回台。
    def test_t8_abandoned_table_returns_instead_of_seek_wood(self):
        inventory = [row("wooden_pickaxe", 1, 0, True), row("stick", 2, 1),
                     row("planks", 3, 2), row("cobblestone", 3, 3),
                     row("crafting_table", 1, 4), row("dirt", 2, 5),
                     row("apple", 1, 6), row("sapling", 2, 7)]
        self.agent.table_fail = 9
        self.agent.table_placed = True
        self.agent.table_pos = (-216, 72, -54)   # v5c 报告确认的地表台坐标
        base = obs(inventory=inventory, craftable=[],
                   position=(-215.5, 67.0, -52.4), pitch=60.0)
        actions = [self.agent.act(base) for _ in range(30)]
        self.assertGreater(getattr(self.agent, "furnace_return_steps", 0), 0,
                           "abandoned table must enter bounded return path")
        self.assertTrue(
            any(a[4] != 12 or a[2] == 1 or a[3] != 12 for a in actions),
            "return path must turn/jump/climb, got %r" % (actions[:10],))
        buf = io.StringIO()
        with redirect_stdout(buf):
            for _ in range(200):
                self.agent.act(base)
        out = buf.getvalue()
        self.assertLessEqual(out.count("table placement abandoned"), 2,
                             "abandoned log must be one-shot, got many")
        self.assertLessEqual(out.count("stone dependencies unavailable"), 1,
                             "must not fall back into infinite explore-for-wood")


if __name__ == "__main__":
    unittest.main()
