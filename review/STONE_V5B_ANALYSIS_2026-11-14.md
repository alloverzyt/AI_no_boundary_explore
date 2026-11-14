# v5b 石镐后停滞证据、最小闭环与测试设计（只读，2026-11-14）

- 日期：2026-11-14（Asia/Shanghai）
- 输入：`review/runs/stone-v5b-2026-11-14/world-h7tzowts/`（lead 的 `STONE_RUN_V5B_2026-11-14.md` 已记录运行有效性）；本地 commit `5f4a926`（`fix: improve mining recovery and log pickup`）；包 sha256 `d0a6bb28…`（31,584 B），包内 `agent/agent.py` = `702e0ade…`（68,100 B）。
- 本轮**只读分析**：未改源码/测试、未 commit/push、未启动游戏；若需下一修，测试设计见 §5，等 lead 授权后实施。
- 结论：v5b 运行有效但游戏 3/4（`tutorial_step_limit`，熔炉未达成）。石镐后**tables=0、planks=3（<4）、log=0、cobble 已由 3 增到 18**，且离台 23.5 格、井下无树 → 37 次 `stone dependencies unavailable -> explore for wood` 全是无效循环。最小闭环应**在下井前（石镐刚完成、仍在近台/地表窗口）先确保携带便携台**；井下兜底再考虑回台/竖直脱困。

## 1. 工作台时间线（公开 steps 证据）

| 步 | 动作/事实 | 位置 | 背包要点 |
|---|---|---|---|
| 1979 | 合成工作台 #1（op4 item7） | `(-221.7,72,-40)` | planks4, sticks4, sapling4, table1 |
| 1980 | 放下 #1（op6 slot4）成功 | 同左 | table 1→0；准星命中台子 `(-223,73,-41) d=0.32` |
| 2240 | 合成工作台 #2（便携台） | `(-221.3,72,-39.2)` | planks 4→3，table 1 |
| 2478–2490 | #2 连续 7 次放置失败（op6 slot4） | `(-220.6,69,-40.3..-40.0)` | table 仍为 1 |
| 2492 | **#2 放置成功**（op6 slot4） | `(-220.6,69,-40.0)` | table 1→0；准星命中 `(-222,69,-40) d=1.76` |
| **2493** | **合成石镐**（op4 item207） | `(-220.6,69,-40.0)` | **cobblestone 3→0**；wooden_pick1, stone_pick1, planks3, sticks2, dirt6, sapling4 |
| 2494 | 装备石镐（op5 slot1） | 同左 | 近台（crosshair table d=1.76） |
| 2494 之后 | 准星再未命中任何 crafting_table（最后一次 table 命中=2494） | 下挖 | — |

> 说明：工作台 #2 的公开坐标 `(-222,69,-40)` 在 2492–2494 被准星命中，`_track_table()` 会写入 `table_pos`（代码 575–584 行），所以**坐标是被记录过的**；当前代码只把它用于 `_near_table` 判定，**没有用于“回台”导航**。

## 2. 石镐后关键快照（lead 要求的 tables/cobble/craftable/位置）

### 2.1 石镐完成瞬间（step 2493）

- 位置：`(-220.6, 69.0, -40.0)`；pitch 60；准星 `crafting_table (-222,69,-40) d=1.76`（**台子在旁边**）。
- 背包：`wooden_pickaxe 1, stone_pickaxe 1, planks 3, stick 2, dirt 6, sapling 4, red_flower 1`；**crafting_table = 0**；cobblestone = 0（3 个刚用于合成石镐）；**log/wood = 0**。
- `craftable`（2493）：`['stick','wooden_button','wooden_pressure_plate','bowl','wooden_slab']` —— 无 `stone_pickaxe`（圆石已耗尽），无 `furnace`（无台邻近判定/材料）。

### 2.2 圆石首次达 8（step 2936，已深挖 23 格）

- 位置：`(-220.7, 46.0, -39.3)`；背包：`stone_pickaxe1, wooden_pickaxe1, **cobblestone 8**, planks 3, stick 2, dirt 11, stone 2, sapling4, red_flower1`；**crafting_table = 0**；log/wood = 0。
- `craftable`（2936）：`['stick','stone_button','stone_pressure_plate','stonebrick','wooden_button','wooden_pressure_plate']` —— **没有 crafting_table、没有 furnace**。
- 台子距离：`(-222,69,-40)` 与当前位置 3D 距离 **≈23.5 格**（垂直 23）；#1 `(-223,73,-41)` 更远。
- 之后到 6000 步：**0 次 place、0 次 craft**；最终 cobble 18、planks 仍 3。
- 3000–6000 步：`agent.log` **37 次** `stone dependencies unavailable -> explore for wood`；step 2936→6000 共 **3065 步**，op3=1204（stone/gravel）、op0=1861，y 仅在 46–48 振荡。

### 2.3 为什么“37 次 seek wood”全都无效

- `_table_step` 无台分支：`crafting_table` 不在 `craftable`（planks 3 < 4）→ 返回 None；
- `_material_step`：`log_n = 0` → 返回 None；
- 于是 `dep_fail` 累计到 80 → `seek_and_break(LOG_BLOCKS, up_scan=True)`；但井底 y≈46 没有树，`up_scan` 也找不到 wood；`dep_fail` 清零后循环，共 37 次；
- 期间 nav 一直在 stone/gravel 里跳/挖（op3 1204 次），但既回不到台、也无法做出便携台。

## 3. 与 lead 两个修复选项的对照

| 选项 | v5b 证据 | 判断 |
|---|---|---|
| **A. 下井前保留第二台** | 2493 时台 #2 就在旁边，但**背包 tables=0**；planks=3、log=0，**当场做不出新台**（需要多 1 个原木→4 木板）。 | **可行且最小**：在 2493 这个“仍在 y69 地表/近台窗口”先补 1 个原木→4 木板→第二张台，再下井；预计多花百步内，v5b 石镐后还有 3507 步。 |
| **B. 石镐后有材料时重建台** | 2493 时 planks=3、log=0，**无材料**；下井后 y46 无树，永远补不到材料。 | 仅靠现有材料不成立；必须先“回地表/回台”或提前囤料，属于 A 的补充。 |
| **C. 回台/竖直脱困（兜底）** | 台坐标 `(-222,69,-40)` 已被 `_track_table` 记录，但当前无导航使用；v5b 在井底 3065 步与 y 46–48 振荡、nav jump/dig 反复失败。 | 需要竖直脱困/回头路径，改动较大；**不建议作为第一改**，可作为 A 失败时的有界兜底。 |

**建议的最小闭环（下一修）**：在石器/熔炉阶段（`spick>=1 and furnace==0`）加一个“下井前台子就绪闸门”：
1. 若 `tables >= 1` → 允许继续采矿（携带便携台，采满 8 用已有 `_table_step` 放置/合成）；
2. 若 `_near_table()` 且 `cobble>=8` → 直接 `craft furnace`（现有路径保护）；
3. 若 `tables==0` 且不在台旁：
   - `"crafting_table" in craftable and planks>=4` → 先做台（不急着下井）；
   - `log_n>=1 and "planks" in craftable` → 先补木板到 4 → 做台；
   - 在**浅层/地表窗口**（例如 `pos.y >= table_pos.y - 3`，或 `table_pos` 未知但 `y` 仍接近初始地表）→ 有界 `seek_and_break(LOG_BLOCKS)` 补 1 个原木 → 做台；
   - 只有 tables>=1（或确认台在配方距离内）才允许 `dig_down` 深挖；
4. 若已经深挖且无台无料：把现在的 37 次 `explore for wood` 改成**有界兜底**：用已记录的 `table_pos` + v5 `_yaw_to_point` 尝试回台/向上脱困（最多 1–2 轮），失败则明确日志并停止无效 loop；
5. 采满 8 圆石后：优先用携带台就地放置（沿用 v5 `table_recover` 失败恢复）→ `craft furnace`；若连续 9 次放置失败（竖井几何），转 4 的兜底回台。

## 4. 预期收益（基于 v5b 步数）

- v5b：石镐 2493 → 熔炉未做；剩余 3507 步中约 3065 步浪费在井底 dependency loop。
- 最小闭环预计在 2493–2700 步内补 1 原木/木板/台（若地表有树），再花 ~500–800 步采 8 圆石，剩余步数足够合成熔炉；**但需要实跑验证，不承诺**。

## 5. 测试设计（先写设计，未实现；下一修授权后落地）

建议新增 `tests/test_furnace_readiness.py`（只用公开 observation 契约，fixtures 直接取 v5b 公开轨迹值）：

### T1 石镐完成瞬间、缺台但有 1 原木（v5b 2493 + log 变体）
- 输入：`spick=1, furnace=0, cobble=0, tables=0, planks=3, log=1`，`craftable=["planks"]`，position `(-220.6,69,-40)`，hit 无/非 stone。
- 期望（新代码）：动作为 `craft planks`（之后补到 4→`craft crafting_table`），**不得** `dig_down`/aim 90/seek wood 地下；旧代码会在 stone 阶段直接下挖/循环 → **预期红**。
- 断言：`action[5]==4 and action[6]==CRAFT_ITEMS.index("planks")`；且后续 step 出现 `crafting_table` 合成。

### T2 石镐完成瞬间、无材料仍应优先地表补台
- 输入：`spick=1, furnace=0, cobble=0, tables=0, planks=3, log=0`，`craftable=[]`，position 地表 `(-220.6,69,-40)`。
- 期望：先 `seek_and_break(LOG_BLOCKS)`/近地表找树（有界），**不是** `dig_down`/pitch 90；旧代码直接下挖 → **预期红**。

### T3 已有 4 木板，直接做便携台
- 输入：`spick=1, furnace=0, cobble=0, tables=0, planks=4`，`craftable=["crafting_table"]`，position 地表。
- 期望：`op4 crafting_table`（携带台），不先下挖；旧代码下挖 → **预期红**。

### T4 深井、cobble=8、无台无料（v5b 2936 精确快照）
- 输入：`spick=1, furnace=0, cobble=8, tables=0, planks=3, log=0`，`craftable=['stick','stone_button','stone_pressure_plate','stonebrick','wooden_button','wooden_pressure_plate']`，position `(-220.7,46,-39.3)`，`table_placed=True`，`table_pos=(-222,69,-40)`。
- 期望：不再重复 `seek wood`；改为朝 `table_pos` 的有界回程/向上尝试（可用 `_yaw_to_point` 断言转向方向，或断言 40 步内动作含朝目标 yaw/向上移动，且 `stone dependencies unavailable` 日志 ≤1 次）；旧代码 37 次循环 → **预期红**。

### T5 携带台、cobble=8 时先放台再合熔炉
- 输入：`spick=1, furnace=0, cobble=8, tables=1`，`craftable=[]`，无 near table。
- 期望：`op6 place`（放置携带台，slot 正确）→ 下一帧 `craftable` 含 `furnace` 时 `op4 furnace`；旧代码也会放台（guard，防回归）。

### T6 近台保护：已在台旁则直接合熔炉
- 输入：`spick=1, furnace=0, cobble=8, tables=0`，`table_placed=True`，`table_pos` 与 position 3D ≤3，`craftable=["furnace"]`。
- 期望：`op4 furnace`；不得再去找木/做台（guard）。

### T7 reset/状态
- 输入：设置新的“台就绪/回程”状态字段后 `reset`，全部清零；保证另一条 v5 回归（80 tests）不退化。

> 以上 T1/T2/T3/T4 在当前 v5b 代码上预期为红；T5/T6 为防回归 guard。新增后目标为 **80 + 7 = 87 tests OK**（另含既有 80）。

## 6. 状态

- **未改源码/测试、未重跑**；`feature/stone-checkpoint` 本地 commit `5f4a926` 已保存（push 失败是网络问题，与代码无关）。
- 本报告只读；等 lead 授权后按 §3 最小闭环实施并先落地 §5 测试（先红后绿），再申请唯一一次 v5c/正式运行。
