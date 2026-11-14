"""Woodcraft 稳定性回归测试（task-9）。

依据：PR6 云端 woodcraft 公共失败轨迹
``ai-no-boundary-pr6-artifacts/world-nfiy9gyv``（seed 42，1500 步，3/5 目标）
以及本地 seed42 复现（review/runs/woodcraft-fix2-run2，3/5 同型失败）。

轨迹给出的两个真实根因（非猜测，均由 steps.jsonl 统计确认）：

1. **打掉原木但不去捡掉落物（主因，云端 3/5 与本地 run2 3/5 直接原因）**
   各次运行对同一原木块的连续攻击都是 65 帧左右（手打木头约需 60 tick），
   即**木块确实被打掉了**；但掉落物留在准星 2~4 格之外，旧逻辑打掉后立刻
   转去找下一格/走开，从不回到掉落点，于是背包里永远只有第 1~2 个原木。
   例：云端失败轨迹在 step 320-384 / 475-541 / 542-608 各打掉一根原木，
   全部没有 25 步内获得 log；成功轨迹则在 step 700-764 近距离（1.1 格）
   打断后 step 777 拿到 log。修复在检测到「正在打的木块准星换格（已打掉）」
   后，朝原方向前进 16 帧（`LOG_PICKUP_STEPS`）把掉落物收进背包，
   背包出现 log 立即恢复原进度。

2. **原地前进卡死（step 1358-1500）**
   连续 143 步 ``action[0]=1``（前进）但 ``position`` 冻结，准星 wood 距离
   恒为 5.0（>REACH）。导航状态机用「相对 anchor 的净位移」判进度：重锚
   要求 ``moved >= 2.0``，卡住判定是 ``moved < 1.0``，净位移落在
   ``[1.0, 2.0)`` 时既不重锚也永不恢复。修复用「每帧真实位移」短窗检测
   （曲线行走每帧仍有位移，不会误判），连续 12 帧零位移只做 90 度侧移 ——
   **不做** jump/dig（历史实测把 moved 门槛直接放宽到 <2.0 会触发
   jump/dig 循环，把已站立的 agent 挖进地下，本地已验证 5/5 路径从 step 430
   起回归成 0/5，见 review/WOODCRAFT_STABILITY_2026-11-14.md）。

以下用例只使用公开观测/动作契约复现上述序列，可在旧代码上失败。
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import agent as policy

GOALS = ["log", "planks", "stick", "crafting_table", "wooden_pickaxe"]


def observation(items=(), craftable=(), block=None, distance=None,
                position=None, pitch=0.0, traced=None):
    return {
        "noop_action": [0, 0, 0, 12, 12, 0, 0, 0],
        "inventory": [dict(item_id=name, quantity=count, slot=i, equipped=False)
                      for i, (name, count) in enumerate(items)],
        "craftable": list(craftable),
        "position": list(position if position is not None else [0, 64, 0]),
        "orientation": {"pitch": pitch},
        "crosshair_hit": {
            "block_name": block,
            "block_distance": distance,
            "traced_block_x": (traced or (None, None, None))[0],
            "traced_block_y": (traced or (None, None, None))[1],
            "traced_block_z": (traced or (None, None, None))[2],
        },
    }


def hit(name, distance, x, y, z):
    return {"block_name": name, "block_distance": distance,
            "traced_block_x": x, "traced_block_y": y, "traced_block_z": z}


class WoodcraftStabilityTests(unittest.TestCase):
    def setUp(self):
        self.visual = patch.object(policy, "vision", None)
        self.visual.start()
        self.addCleanup(self.visual.stop)
        self.agent = policy.Agent()
        self.agent.configure({"model": {}, "agent": {}})
        self.agent.reset(GOALS)

    # --------------------------- 根因 1（主因）：原木掉落物必须走过去捡
    def test_broken_log_is_walked_into_for_pickup(self):
        """打掉原木后（准星换格）必须朝掉落点前进，捡到 log 后立即继续合成。

        复现失败轨迹 step 1009-1073：位置 (-233.8, 69, -134.7)、准星
        wood(-237,70,-135)@2.27 连续攻击 65 帧后该格被打掉，准星换到远处
        leaves；旧代码直接走开，掉落物留在 3 格外，背包永远拿不到 log。
        修复后：进入 pickup，前进数帧；背包出现 log 后取消 pickup 并合成木板。
        """
        base = observation([("planks", 2), ("stick", 4)], ["stick"],
                           position=[-233.81, 69.0, -134.7], pitch=0.0)
        wood = hit("wood", 2.27, -237, 70, -135)
        for _ in range(70):
            self.agent.act(dict(base, crosshair_hit=dict(wood)))
        # 65 帧左右打掉木块：准星换成更远的 leaves
        far = hit("leaves", 6.41, -241, 70, -134)
        action = self.agent.act(dict(base, crosshair_hit=dict(far)))
        self.assertEqual(
            getattr(self.agent, "pickup_steps", 0), policy.LOG_PICKUP_STEPS,
            "broken log must start a bounded walk toward the drop")
        self.assertEqual((action[0], action[5]), (1, 0),
                         "first pickup frame must walk forward, not attack/turn")
        # 掉落点在前方：连续前进帧
        actions = [self.agent.act(dict(base, crosshair_hit=dict(far)))
                   for _ in range(6)]
        self.assertTrue(all(a[0] == 1 and a[5] == 0 for a in actions),
                        "pickup must be a committed forward approach, got %r" % (actions,))
        # 捡到 log：取消 pickup，恢复正常木制进度（这里应立刻合成 planks）
        picked = observation([("planks", 2), ("stick", 4), ("log", 1)], ["planks"],
                             position=[-233.81, 69.0, -134.7], pitch=0.0)
        action = self.agent.act(picked)
        self.assertEqual(self.agent.pickup_steps, 0)
        self.assertEqual(action[5], 4, "after pickup the agent must resume crafting")

    def test_short_wood_look_does_not_fake_a_break(self):
        """只打了几帧（<8）就丢目标不算打掉，不得触发捡取。"""
        base = observation([("planks", 2), ("stick", 4)], ["stick"],
                           position=[-233.81, 69.0, -134.7])
        wood = hit("wood", 2.27, -237, 70, -135)
        for _ in range(3):
            self.agent.act(dict(base, crosshair_hit=dict(wood)))
        far = hit("leaves", 6.41, -241, 70, -134)
        self.agent.act(dict(base, crosshair_hit=dict(far)))
        self.assertEqual(getattr(self.agent, "pickup_steps", 0), 0)

    # --------------------- 根因 2：短窗零位移 -> 轻量侧移（不 jump/dig）
    def test_blocked_walk_sidesteps_instead_of_walking_forever(self):
        """anchor 净位移停在 [1.0,2.0) 且每帧零位移时，必须侧移换方向。

        对应失败轨迹 step 1358-1500：旧代码 30 步内只有前进，nav_count
        无限增长；新代码在连续 12 帧零位移后转 90 度，且不得 jump/dig。
        """
        self.agent.nav_anchor = (0.0, 64.0, 0.0)
        self.agent.nav_state = "moving"
        self.agent.nav_count = 0
        obs = observation([("planks", 6), ("stick", 4)], ["crafting_table"],
                          block="wood", distance=5.0,
                          position=[1.2, 64.0, 0.0], pitch=-30.0)
        actions = [self.agent.act(obs) for _ in range(30)]
        turns = [i for i, action in enumerate(actions) if action[4] != 12]
        self.assertTrue(
            turns,
            "12 consecutive zero-movement frames must trigger a 90-degree "
            "sidestep; old code only walked: %r" % (actions,))
        self.assertLess(turns[0], 30)
        self.assertFalse(
            [action for action in actions if action[2] == 1],
            "blocked-walk recovery must not force jump/dig in the dead zone")

    def test_short_window_still_counts_curved_walking_as_progress(self):
        """每帧都有真实位移（哪怕净位移小）不得被误判为卡住并转向。"""
        self.agent.nav_anchor = (0.0, 64.0, 0.0)
        self.agent.nav_state = "moving"
        self.agent.nav_count = 0
        actions = []
        for i in range(30):
            obs = observation(block="leaves", distance=5.0,
                              position=[i * 0.3, 64.0, 0.0])
            actions.append(self.agent.nav_step(obs))
        self.assertFalse(
            [action for action in actions if action[4] != 12],
            "per-step movement is progress; do not sidestep")


if __name__ == "__main__":
    unittest.main()
