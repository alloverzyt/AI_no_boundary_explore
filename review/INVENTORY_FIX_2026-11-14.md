# 重复物品槽覆盖装备状态修复（task-6）

- 日期：2026-11-14（Asia/Shanghai）
- 仓库：`C:\Users\31193\Documents\Dsh\AI_no_boundary_explore`
- 依据：task-6（负责人从 `agent/agent.py:133-140` 确认）；前置 task-3 已完成
- 写入范围（严格遵守）：`agent/agent.py`（仅 `inv` 解析）、`tests/test_agent.py`、本文件
- 未改其他策略、未改官方开发包、未推送、未启动游戏；游戏复验按顺序放到 task-5，且**必须用包含本修复的当前源码重新打包**（不复用旧 zip）。

## 1. 缺陷

修复前 `agent/agent.py` 的观测解析（原第 131-140 行）：

```python
@staticmethod
def inv(obs):
    counts, slots, equipped = {}, {}, {}
    for row in obs.get("inventory", []):
        name = row["item_id"]
        counts[name] = counts.get(name, 0) + int(row["quantity"])
        slots.setdefault(name, int(row["slot"]))
        equipped[name] = bool(row.get("equipped"))
    return counts, slots, equipped
```

同一个 `item_id` 可以占多个槽位（例如捡到/合成出第二把镐，public observation 的 inventory 是逐槽位记录）。旧实现有两个缺陷：

1. **装备状态被后行覆盖**：`equipped[name] = bool(row.get("equipped"))` 取最后一行。若已装备槽位行在前、未装备同类行在后，聚合结果变成 `False`；
2. **槽位固定首槽**：`slots.setdefault(...)` 总是第一行的槽位。若已装备行不是首行，`slots` 指向未装备槽。

### 触发条件与后果

- 触发：`inventory` 中存在 ≥2 行相同 `item_id`，且其中一行 `equipped=True`、另一行 `equipped=False`。
- 后果：石器阶段 `agent.py:875-876`
  ```python
  if not equipped.get(pick_name) and slots.get(pick_name) is not None:
      return slot_action(observation, "equip", slots[pick_name])
  ```
  在“已装备行在前”的情况下 `equipped` 聚合为 `False`，Agent 每步都发 `equip`（操作码 5），**永远推进不到攻击（操作码 3）**，卡住采矿；在“已装备行在后”情况下虽判定已装备，但 `slots` 指向未装备槽，后续放置/装备类动作可能选错槽。
- 与任务描述一致，未见其他策略代码需要改动；本次只修聚合。

## 2. 复现（先红）

在不改源码的前提下，把旧 `inv` 逻辑 monkeypatch 回 `Agent.inv`，运行新增的 5 个回归用例：

```text
FAIL test_act_attacks_instead_of_reequipping_with_duplicate_unequipped_row
     AssertionError: 5 != 3          # 旧逻辑在“已装备镐 + 重复未装备镐”时发 equip(5)，不攻击
FAIL test_inv_duplicate_equipped_row_first_keeps_equipped
     AssertionError: False is not true   # equipped 被未装备行覆盖
FAIL test_inv_duplicate_equipped_row_last_uses_equipped_slot
     AssertionError: 5 != 2          # slots 固定首槽，未指向已装备槽 2
OK   test_inv_duplicate_unequipped_keeps_first_available_slot
OK   test_inv_duplicate_state_is_isolated_per_item
→ RED: 3 failures / 5 tests
```

失败信息直接对应任务给的触发条件（两种行顺序）与 act 行为要求（先进攻而非重复 equip）。

## 3. 修复

`agent/agent.py` 的 `inv` 聚合改为（数量仍求和，仅改装备/槽位聚合）：

```python
for row in obs.get("inventory", []):
    name = row["item_id"]
    slot = int(row["slot"])
    counts[name] = counts.get(name, 0) + int(row["quantity"])
    if bool(row.get("equipped")):
        equipped[name] = True
        slots[name] = slot
    else:
        equipped.setdefault(name, False)
        slots.setdefault(name, slot)
```

规则：

1. 同名**任一**槽位 `equipped=True` → `equipped[name] = True`；
2. `slots[name]` 优先指向**已装备槽**；多个已装备槽时取最后一个出现者（任一都可用）；
3. 全都没装备时 `slots[name]` 保持**首个可用槽**（与旧行为一致）；
4. 数量仍按同名全部行求和；不同 `item_id` 之间互不影响；
5. 两种行顺序结果一致（equipped 状态与 slots 均不受行序影响）。

## 4. 回归测试（`tests/test_agent.py`，新增 5 例）

| 用例 | 断言 |
|---|---|
| `test_inv_duplicate_equipped_row_first_keeps_equipped` | 已装备行在前：counts=3、equipped=True、slots=2 |
| `test_inv_duplicate_equipped_row_last_uses_equipped_slot` | 已装备行在后：counts=3、equipped=True、slots=2（不再固定首槽 5） |
| `test_inv_duplicate_unequipped_keeps_first_available_slot` | 两行都未装备：equipped=False、slots=首槽 3、数量求和 |
| `test_inv_duplicate_state_is_isolated_per_item` | 不同物品装配状态互不污染（wooden_pickaxe=False / stone_pickaxe=True / cobblestone=False，slots 各自正确） |
| `test_act_attacks_instead_of_reequipping_with_duplicate_unequipped_row` | 已装备木镐 + 重复未装备行 + 准星内 stone：`act` 返回 `action[5] == 3`（攻击），不是 5（equip） |

测试 fixture 仍只用公开 observation 契约（`inventory` 行结构 `{item_id, quantity, slot, equipped}`），不访问 MineDojo 内部。

## 5. 验收结果

| 项目 | 命令 | 退出码 | 结果 |
|---|---|---|---|
| 缺陷复现（旧逻辑 monkeypatch） | 见 §2 | — | 3/5 失败（红） |
| 新增用例（修复后） | `python -m unittest tests.test_agent.AgentTests.<5 个用例> -v` | 0 | 5/5 OK（绿） |
| **全套单测** | `python -m unittest discover -s tests -v` | **0** | **Ran 43 tests，OK**（原 21 + CI 17 + 本任务 5），约 0.9 s |
| 编译 | `python -m py_compile agent/agent.py scripts/validate_practice.py` | 0 | 无输出 |
| 差异范围 | `git diff agent/agent.py tests/test_agent.py` | — | 仅 `inv` 方法（+11/−2 行）与测试新增（+61/−3 行），无其他策略改动 |

## 6. 限制与后续

1. 本任务只做**单元级**验证；真实游戏行为需用**包含本修复的当前源码重新打包**后在 task-5 跑一次 woodcraft 复验，失败/成功如实记录，不能用旧包冒充。
2. 旧的“已装备行在前”聚合错误在历史轨迹里可能已造成 equip 抖动；本次修复不回溯历史日志，也不调整 equip 之外的状态机。
3. 若环境会在同一 `item_id` 多槽位中把“已装备”标记放在任意行，本修复均已覆盖；若未来 inventory 结构变化（如增加 `count` 字段名），需同步 fixture。

## 7. 变更文件

- `agent/agent.py`：仅 `inv()` 装备/槽位聚合逻辑（数量语义不变）
- `tests/test_agent.py`：`observation()` 增加可选 `inventory` 参数；新增 `row()` 辅助与 5 个回归用例
- `review/INVENTORY_FIX_2026-11-14.md`：本报告
