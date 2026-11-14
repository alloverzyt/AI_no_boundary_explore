"""Directional log-drop pickup regressions (v5, seed42/seed43 public-coordinate sequences).

Only public observation fields are used. Forward/yaw convention derived from saved
public steps: ``forward = (-sin(yaw), cos(yaw))`` and ``yaw += 15 * (action[4]-12)``.

v5 threshold evidence (wood-worker read-only analysis of stone-v4 public steps,
independently reproduced by us): with v4 code (``wood_hits >= 8``) there were 70
pickup triggers, but 65 were **false breaks** (wood_hits only 8 or 10; same wood
block reappeared) and only 5 were real breaks (hits 60-67, ~60-tick hand break).
The test matrix below pins the real/false fixtures from that public trajectory.
"""
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agent"))
import agent as policy

# (label, hits, player position, yaw, broken wood block)
REAL_BREAKS = [
    ("R1", 67, (-214.7, 70.0, -43.7), 150.0, (-217, 72, -48)),
    ("R2", 62, (-214.7, 70.0, -41.486), 75.0, (-217, 72, -41)),
    ("R3", 60, (-214.7, 70.0, -42.121), 60.0, (-217, 73, -41)),
    ("R4", 67, (-217.089, 71.0, -41.705), 90.0, (-221, 74, -42)),
    ("R5", 65, (-218.7, 71.0, -41.705), 90.0, (-221, 73, -42)),
]
FALSE_BREAKS = [
    ("F1", 10, (-214.7, 70.0, -40.015), 90.0, (-217, 73, -41)),
    ("F2", 10, (-214.7, 70.0, -40.015), 90.0, (-217, 73, -41)),
    ("F3", 8, (-214.7, 70.797, -40.01), -270.0, (-217, 74, -41)),
]


def obs(inventory=(), craftable=(), block=None, distance=None, pitch=-15.0,
        position=(0.0, 70.0, 0.0), yaw=0.0, last_action=None,
        traced=(-217, 72, -41)):
    hit = {"block_name": block, "block_distance": distance,
           "traced_block_x": traced[0], "traced_block_y": traced[1],
           "traced_block_z": traced[2]}
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


def row(item_id, quantity=1, slot=0, equipped=False):
    return {"slot": slot, "item_id": item_id, "quantity": quantity, "equipped": equipped}


def desired_turn_units(position, block, yaw):
    dx = block[0] + 0.5 - position[0]
    dz = block[2] + 0.5 - position[2]
    desired = math.degrees(math.atan2(-dx, dz))
    delta = (desired - yaw + 180.0) % 360.0 - 180.0
    return max(-12, min(12, int(round(delta / 15.0))))


class PickupDirectionTests(unittest.TestCase):
    def setUp(self):
        self.visual = patch.object(policy, "vision", None)
        self.visual.start()
        self.addCleanup(self.visual.stop)
        self.agent = policy.Agent()
        self.agent.configure({"model": {}, "agent": {}})
        self.agent.reset([])

    def _arm_pickup(self, position, broken_block, yaw=0.0, hits=60):
        """Attack a wood block enough times, then let it break (key change)."""
        kx, ky, kz = broken_block
        attacking = obs(inventory=[], block="wood", distance=2.0,
                        position=position, yaw=yaw, traced=(kx, ky, kz))
        for _ in range(hits):
            self.agent.act(attacking)
        after_break = obs(inventory=[], block="wood", distance=2.0,
                          position=position, yaw=yaw, traced=(kx, ky, kz + 1))
        self.agent.act(after_break)
        self.assertEqual(self.agent.pickup_target, (kx, ky, kz))
        self.assertGreater(self.agent.pickup_steps, 0)

    def _hit_wood_then_switch(self, position, block, yaw, hits):
        kx, ky, kz = block
        attacking = obs(inventory=[], block="wood", distance=2.0,
                        position=position, yaw=yaw, traced=(kx, ky, kz))
        actions = [self.agent.act(attacking) for _ in range(hits)]
        far = obs(inventory=[], block="leaves", distance=6.41,
                  position=position, yaw=yaw, traced=(kx + 2, ky, kz + 1))
        actions.append(self.agent.act(far))
        return actions

    # ------------------------------------------------ 真破坏：必须 arm（阈值 55）
    def test_real_breaks_arm_pickup_at_55_threshold(self):
        for label, hits, pos, yaw, block in REAL_BREAKS:
            with self.subTest(fixture=label, hits=hits):
                self.setUp()
                self._hit_wood_then_switch(pos, block, yaw, hits)
                self.assertEqual(self.agent.pickup_target, block,
                                 msg="%s real break (hits=%d) must arm pickup" % (label, hits))
                self.assertGreater(self.agent.pickup_steps, 0)
                action = self.agent.act(obs(inventory=[], block="leaves",
                                            distance=3.0, position=pos, yaw=yaw,
                                            traced=(block[0], block[1], block[2] + 1)))
                expected = desired_turn_units(pos, block, yaw)
                self.assertEqual(action[4] - 12, expected,
                                 msg="%s pickup must use public yaw direction" % label)

    # ------------------------------------------------ 假破坏：不得 arm（旧阈值 8 会红）
    def test_false_breaks_do_not_arm_pickup(self):
        for label, hits, pos, yaw, block in FALSE_BREAKS:
            with self.subTest(fixture=label, hits=hits):
                self.setUp()
                self._hit_wood_then_switch(pos, block, yaw, hits)
                self.assertEqual(self.agent.pickup_steps, 0,
                                 msg="%s false break (hits=%d) must not start pickup"
                                     % (label, hits))
                self.assertIsNone(self.agent.pickup_target)
                # 未确认破坏时保留 wood_key/wood_hits，允许连击继续累积
                self.assertEqual(self.agent.wood_key, block)
                self.agent.act(obs(inventory=[], block="wood", distance=2.0,
                                   position=pos, yaw=yaw, traced=block))
                self.assertEqual(self.agent.wood_hits, hits + 1)

    def test_replay_1800_1811_does_not_arm(self):
        """v4 公开轨迹：1 帧 jump + 10 帧 wood 同 key，随后准星换 leaves。"""
        pos = (-214.7, 70.0, -41.486)
        block = (-217, 72, -41)
        self._hit_wood_then_switch(pos, block, 75.0, 10)
        self.assertEqual(self.agent.pickup_steps, 0)
        self.assertIsNone(self.agent.pickup_target)

    # ------------------------------------------------ 方向/到达/阻塞（既有 v5 逻辑）
    def test_seed43_pickup_turns_toward_broken_log(self):
        position = (-214.7, 70.0, -41.5)
        broken = (-217, 72, -41)
        yaw = 0.0
        self._arm_pickup(position, broken, yaw, hits=65)
        expected_iter = desired_turn_units(position, broken, yaw)
        action = self.agent.act(obs(inventory=[], block="leaves", distance=3.0,
                                    position=position, yaw=yaw,
                                    traced=(broken[0], broken[1], broken[2] + 1)))
        self.assertEqual(action[4] - 12, expected_iter)
        self.assertNotEqual(action[4], 12, "pickup must turn toward broken block")
        self.assertEqual(action[5], 0)

    def test_seed42_pickup_walks_forward_when_facing_target(self):
        position = (-245.2, 69.0, -134.0)
        broken = (-246, 71, -131)   # roughly straight ahead when yaw=0 (+z)
        yaw = 0.0
        self._arm_pickup(position, broken, yaw, hits=65)
        action = self.agent.act(obs(inventory=[], block="leaves", distance=3.0,
                                    position=position, yaw=yaw,
                                    traced=(broken[0], broken[1], broken[2] + 1)))
        self.assertEqual(action[4], 12)
        self.assertEqual(action[0], 1)
        self.assertEqual(action[2], 0)

    def test_pickup_stops_when_reaching_drop_point(self):
        position = (0.0, 70.0, 0.0)
        broken = (0, 72, 0)         # player is already within pickup radius
        self._arm_pickup(position, broken, hits=60)
        for _ in range(3):
            action = self.agent.act(obs(inventory=[], block="leaves", distance=3.0,
                                        position=position, traced=(0, 72, 1)))
        self.assertEqual(self.agent.pickup_steps, 0)
        self.assertIsNone(self.agent.pickup_target)

    def test_pickup_blocked_jumps_and_is_bounded(self):
        position = (0.0, 70.0, 0.0)
        broken = (0, 72, 4)         # far, and the player cannot move in fixture
        self._arm_pickup(position, broken, hits=60)
        blocked = {"action": [1, 0, 0, 12, 12, 0, 0, 0], "valid": True,
                   "inventory_delta": {}, "position_delta": [0.0, 0.0, 0.0],
                   "health_delta": 0.0}
        actions = []
        for _ in range(16):
            actions.append(self.agent.act(obs(
                inventory=[], block="leaves", distance=3.0, position=position,
                traced=(0, 72, 5), last_action=blocked)))
        self.assertTrue(any(a[2] == 1 for a in actions), "blocked pickup must jump")
        self.assertTrue(any(a[4] != 12 for a in actions), "blocked pickup must sidestep")
        self.assertEqual(self.agent.pickup_steps, 0, "pickup budget must be bounded")


if __name__ == "__main__":
    unittest.main()
