# v5c 实现：石镐后熔炉前台子就绪闸门（2026-11-14，freeze）

- 日期：2026-11-14（Asia/Shanghai）
- 授权：lead 按 `review/STONE_V5B_ANALYSIS_2026-11-14.md` 的 T1-T7 实现；**先红后绿、全套 87 tests/py_compile、freeze 报告；未启动游戏**，等 lead 批准 v5c。
- 仓库/分支：`C:\Users\31193\Documents\Dsh\AI_no_boundary_explore` / `feature/stone-checkpoint`，基线 HEAD `5f4a926`（v5 已提交；本报告对应**未提交**工作树改动）。
- 本轮写入：`agent/agent.py`、新增 `tests/test_furnace_readiness.py`、本报告。未改官方包/评测器/模型；未动 woodfix worktree；未 commit/push（push 网络问题由 lead 处理）。

## 0. 结论

| 项 | 结果 |
|---|---|
| 熔炉前台子就绪闸门 | 已实现（v5c） |
| 新增回归 | `tests/test_furnace_readiness.py` T1-T7 |
| 红→绿 | 修复前 **FAILED (failures=5)**（T1/T2/T3/T4/T7 红；T5/T6 guard 绿）→ 修复后 **7/7 OK** |
| 全套 | **Ran 87 tests，OK，exit 0**（80 既有 + 7 新增） |
| 编译 | `py_compile` exit 0 |
| 行尾/差异 | 编辑的代码/测试文件全 CRLF；`git -c core.autocrlf=false diff --stat` 与 `git diff --ignore-space-at-eol` 一致：`agent/agent.py +99/−0`（无整文件行尾 diff） |
| 游戏 | **未启动 v5c**（按要求等 lead 批准）；无新容器 |

- **lead 复核补丁（freeze 后）**：复核发现“近台即放行下挖”会漏掉 v5b 2493 的真实快照
  （石镐完成时台子就在旁边，但背包 `tables=0`、`cobble=0`），仍会重演离台后无台无料的
  死循环。已把 T2 强化为该精确快照（仍是 T1-T7 七个用例），补丁前强化 T2 **红**、
  补丁后 **绿**，全套仍 **87 tests OK**。

## 1. 实现（`agent/agent.py`）

### 1.1 新常量/新状态（reset 清理）

- `FURNACE_PREP_LIMIT = 120`：浅层为便携台找木/补料的有界步数；
- `FURNACE_RETURN_LIMIT = 120`：深井无台无料时回台/向上兜底的有界步数；
- `furnace_prep_steps`、`furnace_return_steps`、`furnace_return_last` 均由 `reset()` 清零/置 None。

### 1.2 `_furnace_table_step()`：石镐后、熔炉前的就绪闸门

在石器阶段 `spick>=1 and furnace==0` 时，于“继续挖圆石”判断之前调用；只用公开字段
`inventory / craftable / position / orientation.yaw / table_pos（由准星命中 crafting_table 记录的公开坐标）`：

1. `tables >= 1` → 返回 None，保持原有挖矿/合成路径；
   **`_near_table(obs)` 只有在 `cobblestone >= 8`（可当场合熔炉）时才放行**；
   否则（v5b 2493：台在旁边但 `tables=0`、`cobble=0`）仍先备好便携台再下井，
   避免离台 23.5 格后重演无台无料的死循环；
2. `"crafting_table" in craftable and planks >= 4` → 先合成便携台（不急着下井）；
3. `log_n >= 1 and planks < 4 and "planks" in craftable` → 先补木板（再回到 2）；
4. **浅层**（`pos.y >= table_pos.y - 3`，`table_pos` 未知时用 `y >= 60`）→ 有界
   `seek_and_break(LOG_BLOCKS, up_scan=True)` 找 1 个原木补台；最多
   `FURNACE_PREP_LIMIT=120` 步，超时记录日志后停止找木（不再无限 seek）；
5. **深井无台无料** → `_furnace_return_step()`：用记录到的 `table_pos` 与公开
   yaw 约定（forward=(-sin yaw, cos yaw)）转向回台；转向对齐后前进/跳跃；
   若位置连续不动则抬头（aim -60°）攻击上方尝试向上脱困；最多
   `FURNACE_RETURN_LIMIT=120` 步，超限只记录一次日志并转 `walk_policy`，
   **替代 v5b 的 37 次 `explore for wood` 无效循环**。

### 1.3 未改的部分（保留 v5 有效修复）

- `wood_hits >= 55` 的破块阈值、pickup 定向/停滞恢复、`dig_down` walk 停滞恢复均未回退；
- 仍遵守公开观测约束：不读内部 voxels/评测器状态，不改变官方场景/动作接口；
- 无台/近台/携带台三条既有合成路径保持原样（T5/T6 guard）。

## 2. 测试（`tests/test_furnace_readiness.py`，T1-T7）

| 用例 | fixture（公开字段） | 期望 | 修复前 |
|---|---|---|---|
| T1 | 石镐瞬间 `planks=3, log=1, craftable=["planks"]` | 先 `craft planks`（再补台），不 dig_down | **FAILED** |
| T2 | **v5b 2493/2494 精确快照**：石镐瞬间台在旁边（准星 `crafting_table` d=1.76、`traced=(-222,69,-40)`），但 `tables=0, planks=3, log=0` | 有界找木（`furnace_prep_steps>=1`），不得 pitch=90 下挖 | **FAILED**（强化前/后均红） |
| T3 | `planks=4, craftable=["crafting_table"]` | 先 `craft crafting_table` 携带 | **FAILED** |
| T4 | **v5b step 2936 精确深井快照**：tables=0、cobble=8、planks=3、log=0、craftable 无 table/furnace、pos y46、table_pos=(-222,69,-40) | `furnace_return_steps>0`，动作含转向/跳跃/抬头；200 帧内 `stone dependencies unavailable` ≤1 次 | **FAILED** |
| T5 | 携带台 + cobble=8 | 先 `place` 台（既有路径） | 通过（guard） |
| T6 | 近台 + cobble=8 + `craftable=["furnace"]` | 直接 `craft furnace` | 通过（guard） |
| T7 | reset 前设置新状态 | reset 后全部清零 | **FAILED** |

证据：

| 阶段 | 命令 | 结果 |
|---|---|---|
| 实现前（红） | `python -m unittest tests.test_furnace_readiness -v` | **FAILED (failures=5)** |
| 实现后（绿） | 同上 | **Ran 7 tests … OK** |
| 全套 | `python -m unittest discover -s tests` | **Ran 87 tests，OK，exit 0** |
| 编译 | `python -m py_compile agent/agent.py tests/test_furnace_readiness.py tests/test_pickup_direction.py tests/test_stone_progression.py tests/test_woodcraft_stability.py` | exit 0 |
| 行尾/差异 | CRLF；raw diff == ignore-eol diff | `agent/agent.py +99/−0`（未入库测试文件为新增 untracked） |
| lead 复核补丁（红） | 强化 T2 后、补丁前运行单测 | **FAILED (failures=1)**：`furnace_prep_steps=0`，近台仍下挖 |
| lead 复核补丁（绿） | 补丁后同上 | **OK** |
| 全套（补丁后） | `python -m unittest discover -s tests` | **Ran 87 tests，OK，exit 0** |
| 端到端序列（临时探针，未入库） | 2493 近台无料快照连走 6 帧 | seek wood(`prep=1`) → `craft planks` → `craft crafting_table` → 允许下挖(`prep=0`) → `place table` → `craft furnace` |

当前 frozen 工作树哈希（含 lead 复核补丁）：`agent/agent.py` sha256 `e293d893bbc9517791d36065c546b48e5396eb3ce0d0631e32e6e214bdbe0fc6`；
`tests/test_furnace_readiness.py` sha256 `bb7ef7e24236afd84e220a5adc65fc22cf617ad7e524729918b7ea259347048d`。

## 3. 限制与风险

1. **仅单元级**：v5c 未实跑；真实收益（石镐后先补台/回台，能否在 6000 步内做出熔炉）需唯一一次官方运行验证，不能以测试代替。
2. T4 fixture 的 yaw 每帧固定为 0，因此会反复出现“turn toward table”日志（真实环境中 yaw 会按动作变化，应逐步对齐）；测试已限制 200 帧并只统计 `stone dependencies unavailable`。
3. 若真实地表附近无树（浅层找木 120 步失败），闸门会停止找木并回到原有下挖路径；
   下挖越过“台高 -3”后进入深井有界回台兜底。若之后又回到浅层，找木计数会重新开始，
   真实环境里可能产生往返消耗；最终是否够步数需实跑确认。
4. 保留既有 v5 修复；与 wood-worker 的最终合并由 lead 处理。
5. 工作树另有他人未跟踪报告/改动（STONE_V3_ANALYSIS 等），未处理。

## 4. 状态

- 源码/测试已改完并 **freeze**，未 commit/push；无游戏启动/无新容器。
- 待 lead 批准后用 **新目录** `review/runs/stone-v5c-2026-11-14` + 命名容器 `ainb-stone-v5c`，UTF-8 逐行 + `docker wait`/inspect 退出码，跑唯一一次正式 v5c，并用 result/validator 写 `review/STONE_RUN_V5C_2026-11-14.md`。

## 5. v5c 正式运行结果（2/4）与 T8 修复（v5d 准备）

### 5.1 v5c 运行事实（见 `review/STONE_RUN_V5C_2026-11-14.md`）

- 运行有效（rc=0、6000 步、产物齐全），但目标 **2/4**：`wooden_pickaxe`、`cobblestone` 达成；**`stone_pickaxe`、`furnace` 未达成**；`termination=tutorial_step_limit`、`task_success=false`、validator exit 1。
- 关键轨迹：3047 合成台#1、3052 放置确认；3055 合成便携台#2 带在身上；3092 起直下竖井，3142/3177/3206 取得 3 圆石；**3207–3223 在 y=67 井底连续 9 次 place（slot4）全部失败**；3224 起每帧输出 `table placement abandoned after 9 failures`，共 **2776 次（agent.log 79.7%）**；3224–6000 位置钉在 y67–68、水平 0.4 格，圆石恒 3，**石镐/熔炉 0 次合成尝试**。
- 根因（公开轨迹）：
  - **D1 状态机终态**：`_table_step()` 在 `tables>=1 && table_fail>=9` 时打印 abandoned 后 `return None`，且该分支无条件刷日志；除“重新合成新台（需 4 木板，本轮只有 3 且无木）”外**没有复位条件** → 永远不再尝试台子配方。
  - **D2 竖井无脱困/回台**：台在 `(-216,72,-54)`，玩家 y67–68（dy 4–5），`_near_table` 的 `|dy|<=2`+3D≤3 判“不在旁”；没有 pillar/阶梯向上，也未使用已记录的 `table_pos` 回台。
  - **D3 闸门未覆盖**：v5c 的 `_furnace_table_step` 入口要求 `stone_pickaxe>=1`，本轮石镐从未做出，因此新增回台/补台逻辑一次都未执行。

### 5.2 T8 修复（本轮已实现，先红后绿）

- 新增 T8（`tests/test_furnace_readiness.py`，v5c 精确快照）：`stone_pickaxe` 未做、`crafting_table` slot4 携带、`table_fail=9`、cobble3、stick2、planks3、pos `(-215.5,67.0,-52.4)`、table_pos `(-216,72,-54)`；期望动作**不是 seek wood**、进入有界 return 状态，且 200 帧内 `table placement abandoned` 与 `stone dependencies unavailable` 均不超过阈值。
- 实现（仅 `agent/agent.py`，+120/−1）：
  1. `_table_step()` 的 abandoned 日志改为 **一次性**（`table_abandon_logged`），杜绝 2776 行刷屏；在放置确认成功、重新合成新台、木制失败 relocate 时复位该标志。
  2. 石器阶段 `cobble>=need` 且 `_table_step()` 返回 None 后，若 `tables>=1 && table_fail>=9`：
     - 若已回到台旁（`_near_table`）→ 复位 `table_fail/abandon_logged/furnace_return_steps/dep_fail`，重试正常合成；
     - 否则**显式接入 `_furnace_return_step()`**（用已记录的 `table_pos` + 公开 yaw 转向回台、前进/跳跃、位置不动时抬头 aim −60° 向上脱困；120 步有界），不再落入 dependencies explore / 永久 `return None`。
- 证据：
  - T8 修复前：`furnace_return_steps=0`、abandoned 每帧刷屏 → **FAILED**；
  - 修复后：T8 **OK**；`tests/test_furnace_readiness.py` **8/8 OK**；**全套 `python -m unittest discover -s tests` → Ran 88 tests，OK，exit 0**；`py_compile` exit 0；
  - 编辑文件全 CRLF；raw diff == ignore-eol：`agent/agent.py +120/−1`（新测试文件为 untracked）。
- 当前 frozen 哈希：`agent/agent.py` sha256 `a0ce4f43…`（1478 行）；`tests/test_furnace_readiness.py` sha256 `7aa2f2e7…`（178 行）。
- 遗留风险（未解决，不声称已修）：D2 的“1×1 竖井向上脱困”目前是转向+跳跃+抬头攻击（无 pillar/台阶摆放），可能仍爬不出；D1 的 `table_fail` 复位在回台/重做台时生效，但若 120 步兜底后仍无法回台，会转 `walk_policy`（有界但不保证成功）。D4 竖井深度预算未改。**需要 v5d 实跑验证**。
- 状态：未启动游戏、未 commit/push；等 lead 批准后用新目录（建议 `review/runs/stone-v5d-2026-11-14`）+ 命名容器 `ainb-stone-v5d` 跑唯一一次。
