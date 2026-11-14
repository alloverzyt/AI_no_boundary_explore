# 石器阶段依赖与采矿恢复实现（task-8）

- 日期：2026-11-14（Asia/Shanghai）
- 仓库/分支：`AI_no_boundary_explore` / `feature/stone-checkpoint`（基线 `c0619a0`，与 PR #6 同源；PR6 未合并）
- 依据：task-8、`review/STONE_PLAN_2026-11-14.md`、`review/STATIC_REVIEW_2026-11-14.md`（P1-02/P1-03/P1-04/P1-05）、官方开发包源码
- 写入范围（严格遵守）：`agent/agent.py`、新增 `tests/test_stone_progression.py`、本报告。未改 `tests/test_agent.py`；未改官方包/评测器/模型配置；**未 commit/push**。
- 后续补充：负责人指定的 STONE_DESIGN S04/S05/S10 缺口与 4593 步实跑暴露的“放置死循环”已按“先红测试 + 最小改法”补入（见 §3.6）；实跑记录与瓶颈分析见 [`review/STONE_RUN_2026-11-14.md`](STONE_RUN_2026-11-14.md)。
- 行尾：`agent/agent.py` 保持全 CRLF（1101 行，LF-only=0）；新增测试文件同为 CRLF；`git -c core.autocrlf=false diff --stat` 与 `git diff --ignore-space-at-eol --stat` 相同（仅内容改动，无整文件行尾 diff）。

## 1. 本轮范围与结论

| 目标 | 状态 | 证据 |
|---|---|---|
| P1-02 材料与便携台依赖恢复（缺棍补棍、缺板补板、无台重建） | 已实现 | 新用例 3 个（§4） |
| P1-03 放置确认（公开 `last_action`/背包/recipe）与有界重试 | 已实现 | 新用例 3 个 |
| P1-05（局部）已有高级镐不强制回木制 | 已实现 | 新用例 1 个 |
| P1-04 竖井遇基岩/液体/长期无进展有界恢复 | 已实现 | 新用例 3 个 |
| STONE_DESIGN S04 成品 recipe 优先于备用台采木 | 已补（§3.6） | 新用例 1 个 |
| STONE_DESIGN S05 真实携带台子才置 spare_table | 已补（§3.6） | 新用例 2 个 |
| STONE_DESIGN S10 选最高可用镐 | 已补（§3.6） | 新用例 2 个 |
| 4593 步实跑暴露的放置死循环 | 已补有界恢复（§3.6） | 新用例 1 个 |
| 保持原有回归 | 通过 | **全套 62 tests OK，exit 0**（原 43 + 新 19） |
| woodcraft 云端失败（PR #6，task-9） | **本分支不改** | 按 lead 指示由 `AI_no_boundary_woodfix` 的 wood-worker 处理；本报告仅附公共轨迹分析（§6），不重复实现木制 nav 修复 |

> 说明：这是单元级实现与公开观测序列回归。**尚未在官方 Docker stone-tools 场景实跑**（按约束不启动游戏）；真实 4/4 需负责人用本分支源码重新打包后运行，不得用本报告的单元测试代替实跑。

## 2. 使用的官方公开契约（未猜测字段）

来自官方开发包（只读核对）：

- `pdf_runner.py:51-69` `public_observation()`：`inventory`（逐槽 `{slot,item_id,quantity,equipped,...}`）、`craftable`、`crosshair_hit`、`nearby_tools`、`last_action`（首帧为 `None`）；
- `pdf_runner.py:72-81` `checked_action()`：`valid` 只表示 8 维动作向量合法，**不代表放置/制作真实成功**；
- `pdf_runner.py:178-180`：`last_action = {action, valid, inventory_delta, position_delta, health_delta}`；
- `minecraft_state.py:83-89` `inventory_change()`：`inventory_delta` 是“动作前后同名物品数量差”（放置成功时 `crafting_table` 为负）；
- `practice-scenes.json`：stone-tools = seed 43、`max_steps=6000`、tutorial、goals `wooden_pickaxe/cobblestone/stone_pickaxe/furnace`。

因此放置确认只看 `last_action.action[5] == 6` 且 `inventory_delta` 里台子/熔炉数量为负（或准星直接命中 `crafting_table`）；`valid=True` 不作为成功依据。

## 3. 实现（`agent/agent.py`，最终 +281/−56 行；含 §3.6 后续补充）

### 3.1 新状态（`reset()` 清理）

- 台子确认：`table_pending`、`table_pending_slot`、`table_confirm_wait`、`table_fail`、`dep_fail`（与既有 `table_placed/table_pos/tbl_wait/tbl_steps` 配合）；
- 竖井恢复：`dig_stall`、`dig_escape`、`dig_last_key`（既有 `dig_fail` 继续使用）。

### 3.2 工作台确认与依赖恢复（helpers，`agent.py:471-560` 附近）

- `_last_table_placement(obs)`：仅在 `inventory_delta` 显示 `crafting_table`/`furnace` 减少时返回 `"confirmed"`；上一步是 place 但未消耗 → `"failed"`；无动作信息 → `None`；
- `_update_table_state(obs)`：`table_pending` 用上述公开反馈收敛；确认成功→`table_placed=True`；失败/3 步内无反馈→`table_placed=False, table_fail+=1`（不再“发出 place 即永久成功”）；
- `_send_place(obs, slot, label)`：统一发起放置并进入 pending（下一帧必须得到公开确认）；
- `_material_step(obs, counts, craftable, want_sticks)`：缺棍→合法 `stick`；缺 2 板→合法 `planks`；缺 4 板→合法 `planks`；
- `_table_step(obs, counts, slots, craftable)`：无台→合法合成 `crafting_table`（先补板）→有台则放置/等待确认；不把历史 `table_placed=True` 当可用台。

### 3.3 木制阶段（`agent.py:923` 起；为石器依赖服务的最小改动）

- 阶段门槛：`if wpick == 0 and spick == 0 and iron_pickaxe == 0:` → 已有高级镐时不回退重走木制（P1-05 局部）；
- 放置改为 `_send_place` + 下一帧确认；连续 3 次放置失败→换位重放（有界），不再 60 步盲目等待；
- **补料顺序前移**：木板/木棍/台子的合法制作放到 `table_placed` 等待循环之前，避免“放台后 60 步只走不补料”（P1-03 的阻塞点）。

### 3.4 石器阶段（`agent.py:1021` 起）

圆石够时：

1. `want in craftable` → 立即制作（recipe 优先）；
2. `want == stone_pickaxe` 且缺棍 → `_material_step(want_sticks=True)`（缺板补板、缺棍补棍）；
3. `_table_step(...)`：无台→合法做台；有台未确认/不在旁→放置并等待确认；
4. 台在旁但 recipe 未刷新 → 有界等待（>20 步）后继续挖，不无限转；
5. 无台且无合法补料 → 有界（≤80 步）找木头重建，超预算交给 `walk_policy` 换路线。

圆石不够时：保持“先装备镐再竖直挖”，`dig_down` 改用 §3.5 的有界恢复。

### 3.5 竖井有界恢复（`agent.py:808-895`）

- 基岩 `bedrock/barrier/command_block/end_portal_frame` 与液体 `water/lava/flowing_*`：**不攻击**，`dig_fail+=1`，抬头转向离开（`dig_escape=10`），连续 3 次失败→`walk_policy` 水平换位；
- 普通方块：用公开 `last_action`（攻击且有 `inventory_delta` 或 `position_delta`）与目标指纹判断进展；同一目标连续 120 次无进展（`DIG_STALL_LIMIT`，原木约需 60~80 下）或有进展但 200 次仍未破 → 有界 relocate，3 次失败→放弃竖井换水平探索；
- 不再出现“pitch=90 时只改 yaw、目标不变、打到时限”。

### 3.6 后续补充：S04/S05/S10 与放置死循环有界恢复（4593 步实跑后）

1. **S04 成品 recipe 优先**：备用台阶段先看 `stone_pickaxe`/`furnace` 是否在当前 `craftable`，可用则立即制作，不再先进入 900 步备用台囤木。
2. **S05 真实携带判定**：`spare_table=True` 只由背包 `crafting_table ≥ 1` 触发；仅发出 craft 请求不置位（craft 是否成功由下一帧 inventory 决定）。备料超时只跳过备用台，不影响后续石器阶段用 `_table_step`。
3. **S10 最高可用镐**：新增 `_best_pick(counts)`（iron > stone > wooden），石器阶段装备/挖矿用最高级镐；铁器阶段同样装备最高可用镐（不再硬编码 stone_pickaxe）。
4. **放置失败有界恢复（本次实跑 1240 次 place 死循环的修复）**：`_update_table_state` 判定失败后设置 `table_recover`，下一帧执行“抬头 55° → 转向 90° → 换位置”的恢复动作再重试放置（`table_fail%3` 循环）；连续失败 ≥9 次放弃该台（`_table_step` 返回 None，转入有界依赖/探索路径）；重新合成台子时清零失败计数。修复点对应实跑中“pitch=90 正对脚下 stone、放置目标与玩家位置重叠导致 place 永不消耗”的场景。

### 3.7 后续补充（v2/v3 实跑后）：三维近台、5 步上限、deadline 一次性

1. **`_near_table` 三维距离**（v2 实跑瓶颈）：除 x/z 外加入 `dy`；要求 `abs(dy) <= 2.0` 且 3D 距离 ≤3.0。修复“下挖后台子留在高处、水平很近却不可用”的假近台。
2. **石器等待 recipe 缺失有界**：真实在台旁但 `craftable` 无目标配方时最多等 **5 步**；超时后若背包有备用 `crafting_table` → `table_placed=False` 并强制 `_send_place`（公开姿势/位置恢复），否则 `dig_down` 继续采矿；`craftable` 始终是配方权威。
3. **备用台 deadline 一次性**（v3 实跑瓶颈）：`spare table skipped (deadline)` 后置 `spare_table=True` 且不再重置 900 步；否则下一帧又重新囤木，v3 因此 2600+ 步卡在找树、未进入石器阶段（零圆石）。

## 4. 回归测试（先红后绿）

新增 `tests/test_stone_progression.py`（23 例，全部只用公开观测/动作契约；含 `last_action` fixture）：

| 覆盖要求 | 用例 |
|---|---|
| 缺棍有木：先补板→补棍→石镐 | `test_missing_sticks_with_logs_crafts_planks_then_sticks` |
| 远旧台无备用台：从原木/板重建台 | `test_far_stale_table_is_rebuilt_from_planks` |
| recipe 可用即合成 | `test_legal_recipe_is_preferred_over_navigation` |
| place 未确认：有界重试后换位 | `test_unconfirmed_place_retries_are_bounded_then_relocates` |
| place 确认：inventory_delta 消耗台子 | `test_confirmed_place_marks_table_available` |
| 放台等待不阻断补料 | `test_table_refresh_wait_does_not_block_material_crafting` |
| 木制路径（确认台后做镐）保持 | `test_woodcraft_path_still_crafts_pickaxe_after_confirmed_table` |
| 石镐无木镐：采铁不回木制 | `test_advanced_stone_pickaxe_does_not_force_wood_gathering` |
| 基岩不攻击 | `test_unbreakable_bedrock_is_not_attacked` |
| 水/熔岩不攻击 | `test_liquids_are_not_attacked`（4 种 block 名） |
| 竖井无进展有界恢复 | `test_vertical_dig_no_progress_recovers_within_bound` |
| 有公开进展时持续攻击 | `test_vertical_dig_keeps_attacking_with_public_progress` |
| reset 清理新状态 | `test_reset_clears_stone_stage_state` |
| S04 成品 recipe 优先 | `test_finished_recipe_precedes_spare_table_gathering` |
| S05 craft 请求不算携带 / 真实携带才置位 | `test_spare_table_flag_not_set_when_only_craft_is_requested`、`test_spare_table_flag_set_when_table_really_carried` |
| S10 铁器/石器阶段选最高镐 | `test_iron_phase_equips_best_available_pickaxe`、`test_stone_phase_equips_best_pickaxe_without_wooden` |
| 放置失败有界恢复（实跑死循环） | `test_failed_table_placement_has_bounded_recovery` |
| v2 假近台（垂直 9 格）必须触发真实放置 | `test_near_table_requires_vertical_proximity` |
| 3D 真近台路径不被误伤 | `test_near_table_accepts_true_3d_nearby_table` |
| 石器 recipe 等待最多 5 步 | `test_stone_recipe_wait_is_capped_to_five_steps` |
| v3 deadline 跳过后不得重启囤木 | `test_spare_table_deadline_skip_does_not_restart_gathering` |

证据：

| 阶段 | 命令 | 结果 |
|---|---|---|
| 修改前（红，第一批） | `python -m unittest tests.test_stone_progression -v` | **FAILED (failures=9)**（13 例中） |
| 修改前（红，第二批 S04/S05/S10/放置） | 同上 | **FAILED (failures=6, errors=1)**（19 例中） |
| 修改前（红，第三批 v2 假近台/5 步上限） | 同上 | **FAILED (failures=2)**（22 例中） |
| 修改前（红，v3 deadline 一次性） | 同上 | **FAILED (failures=1)**（23 例中） |
| 修改后（绿） | 同上 | **Ran 23 tests … OK** |
| 全套回归 | `python -m unittest discover -s tests` | **Ran 66 tests … OK，exit 0**（原 43 项全部保留通过 + 新 23） |
| 编译 | `python -m py_compile agent/agent.py tests/test_stone_progression.py` | exit 0 |
| 行尾/差异 | `git -c core.autocrlf=false diff --stat`；`git diff --ignore-space-at-eol --stat` | 两者一致：`agent/agent.py 298 insertions(+), 57 deletions(-)`（无整文件行尾 diff） |

## 5. 限制与未验证项

1. **未实跑官方 stone-tools**：本轮只做源码实现 + 公开观测序列单测；真实 seed43/6000 步/4 目标的 4/4 需负责人用本分支源码重新打包后在缓存镜像复验，不能以单元测试代替。
2. **未实跑 woodcraft**：本分支未改木制 nav 恢复逻辑；PR #6 的 woodcraft 云端失败由 task-9（wood-worker）处理。本分支对木制阶段的改动仅限放置确认/补料顺序/阶段门槛，可能与其 diff 冲突，由负责人集成时处理。
3. **铁器燃料链未动**：P1-01（熔炉放置/燃料）不在 task-8 范围；`_table_step` 的地基能力可复用于后续，但未实现煤/木炭链。
4. **台子“返回旧台”未实现**：只做“重建/放置可用台”；已知旧台坐标远时用合法材料重建，超预算换路线，不做坐标导航回旧台。
5. **单元 fixture 是公开契约构造**，不等于真实 MineDojo 行为；真实运行中 `inventory_delta` 的掉落语义（需靠近拾取）仍需实跑观察。
6. **兼容性风险**：`seek_and_break`/nav 未改，P2-01 长序列问题仍可能影响木制；不在本任务范围。

## 6. 附：PR #6 woodcraft 失败公共轨迹分析（只读，供 task-9 参考；本分支无对应改动）

- 产物：`C:\Users\31193\AppData\Local\Temp\ai-no-boundary-pr6-artifacts\world-nfiy9gyv`（result.json / agent.log / steps.jsonl，只读，未复制进仓库）。
- 结果：`termination=tutorial_step_limit`、`action_count=1500`、`task_success=false`、objectives 仅 `log/planks/stick`（缺 table/pickaxe）、0 death/0 invalid；包 sha256 `7dc22a7a…`。
- 轨迹事实（steps.jsonl）：第 227 步才首次拾取 log（在极近距离），随后第 320–385 步在 d≈2.66 连续攻击树干 66 次；目标切换后 `inventory_delta` 无 log（**方块破坏掉落未被拾取**，玩家距掉落点过远），类似长攻击段多次出现；大量 leaf 目标逐帧交替导致 `lock_hits` 反复清零、连击/破块进度被打断；直到 1080 步才再次合成木板，结束时仅 `planks=6, stick=4`，差 1 个木板无法做台/镐。
- 结论候选：**采集距离过远导致掉落未拾取 + leaf 目标交替打断连续攻击/恢复状态互搏**（与负责人判断一致）。这属于木制 nav/采集策略，建议在 task-9 处理；本分支不再重复实现，避免与 wood-worker 冲突。

## 7. 交付状态（freeze）

- 源码/测试**已冻结**，未 commit、未 push；等待负责人集成（本分支 `agent/agent.py` 与 wood-worker 的木制修复会有同文件差异，由负责人合并）。**当前回归：23 例石器测试 + 全套 66 tests OK**。
- 实跑记录（均未通过，完整证据在对应报告）：
  - run1（旧包）：外部中断，4593 步 2/4；瓶颈 1240 次 place 死循环 → 见 [`STONE_RUN_2026-11-14.md`](STONE_RUN_2026-11-14.md)；
  - v2（含 S04/S05/S10+放置恢复）：完整 6000 步 2/4，`tutorial_step_limit`；瓶颈 `_near_table` 假近台 → 见 [`STONE_RUN_V2_2026-11-14.md`](STONE_RUN_V2_2026-11-14.md)；
  - v3（含三维近台/5 步上限）：完整 6000 步 **1/4**（仅木镐），`tutorial_step_limit`；瓶颈备用台 deadline 重启囤木（不进石器阶段）→ 见 [`STONE_RUN_V3_2026-11-14.md`](STONE_RUN_V3_2026-11-14.md)。该 deadline 缺陷已在 v3 之后按 §3.7 修复并有红→绿测试。
- **不能**把任何一次 2/4 或 1/4 当作石器通过；也从未声称 4/4。
- 下一步（等负责人授权）：用当前冻结源码重新打包（应含 §3.6/§3.7 全部修复）在**唯一新目录**跑一次，判定 `termination=tutorial_goals`、`task_success=true`、objectives 4/4、`validate_practice` exit 0；若仍失败，按新证据继续最小修复（当前风险：木制前置耗时约 2000–3400 步，8 圆石预算偏紧；以及困难分析预测的“1×1 竖井内放台几何失败”）。
