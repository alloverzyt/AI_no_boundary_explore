# 石器 v5c 正式复跑与验收（stone-tools seed43，2026-11-14）

- 日期：2026-11-14（Asia/Shanghai）
- 授权：负责人批准的**唯一一次** v5c 正式 stone-tools 运行（新目录 + 打包 temp + 命名容器 `ainb-stone-v5c`）；运行期间**未改源码/测试、未 commit/push、未并发跑第二个游戏**（13:04:47 有一次同名 `docker run` 尝试被名称冲突拒绝，见 §6；未产生第二个容器）。
- 仓库/分支：`C:\Users\31193\Documents\Dsh\AI_no_boundary_explore` / `feature/stone-checkpoint`，HEAD `5f4a92626bcf1aa5b2a88cac0c7d312bebda43c3`；运行内容是**未提交工作树**（冻结 `agent/agent.py`）。
- 运行目录：`review/runs/stone-v5c-2026-11-14`（唯一）；打包 temp `C:\Users\31193\AppData\Local\Temp\ainb-stone-v5c-pkg`；容器 `ainb-stone-v5c`。
- 结论：**运行本身完整有效（rc=0、6000 动作、产物齐全），但游戏目标 2/4 失败**：木镐、圆石达成；**石镐、熔炉未达成**；`termination=tutorial_step_limit`、`task_success=false`、验证器 exit 1。相对 v5b（3/4）**是回归**，且 v5c 新增的熔炉闸门**在真实运行中一次都没执行到**（石镐从未做出）。

## 0. 验收结论（按要求 4/4 + validator exit 0）

| 判定项 | 要求 | 实测 | 结果 |
|---|---|---|---|
| objectives | 4/4 | **2/4**（`stone_pickaxe=false`、`furnace=false`） | ✗ |
| termination | `tutorial_goals` | `tutorial_step_limit` | ✗ |
| task_success | `true` | `false` | ✗ |
| validator | exit 0 | **exit 1**（2 条错误） | ✗ |
| 运行完整性 | rc=0、6000 步、产物齐全 | rc=0、`action_count=6000`、result/outcome/checkpoint/steps/agent.log 齐全 | ✓ |

> 结论明确：**未通过验收**。不是基础设施失败，而是策略缺陷：工作台放置 9 次失败后被**永久放弃**，随后 2777 步困在 1×1 竖井里空转。

## 1. 冻结代码、包与运行配置

| 项 | 值 |
|---|---|
| 冻结源码 | `agent/agent.py` sha256 `e293d893bbc9517791d36065c546b48e5396eb3ce0d0631e32e6e214bdbe0fc6`（73,594 B，含 lead 复核补丁） |
| 冻结测试 | `tests/test_furnace_readiness.py` `bb7ef7e2…`（新增 T1-T7）、`test_pickup_direction.py` `0f05e4aa…`、`test_stone_progression.py` `e0be0fad…`、`test_woodcraft_stability.py` `c9fc9244…` |
| 测试 | `python -m unittest discover -s tests` → **Ran 87 tests, OK, exit 0**（80 既有 + 7 新增；运行前后各跑一次均 OK，见 `tests.log` / `tests-after-run.log`） |
| 编译 | `py_compile` exit 0（见 `preflight.txt`） |
| 包 | 官方开发包 + 冻结 agent 文件，`model=offline`；`agent.zip` **32,927 B**，sha256 `6c92ce8d6dbfe6b8ec3786d11159f58a72395f16d8b3f460eed890acd99b4c05`（8 entries） |
| 包一致性 | `manifest.package_sha256` == `input.zip` sha256 == `6c92ce8d…`；`input.zip`/`runtime-package.zip`/工作树的 `agent.py` **三者同哈希 `e293d893…`**（73,594 B） |
| 包校验 | 官方 `package_config` / `load_agent` 通过（`Agent.act` callable）；config `{"name":"offline","api_url":"","api_key":""}` |
| 镜像 | `streetartist/uestc-minecraft-controller:latest` sha256 `4f0164fc2a36…`（本机缓存，**未 pull**） |
| 容器 | `ainb-stone-v5c`，id `f1fa9a847ea6ba6055e69a4ee03e4148e304c8457e9728462b7df64784f5abec`；started `13:02:44.6` / finished `13:11:22.7`（elapsed **518.1s**），`ExitCode=0`，当前 `exited`，保留供 inspect |
| 约束 | `--network none`、`--cpus 4 --memory 4g --memory-swap 4g --pids-limit 512 --shm-size 512m`、`--only stone-tools --no-video`；无模型调用（`tokens=0 / calls=0`） |

> 冻结时间线（如实）：`STONE_V5C_FURNACE_READINESS` 在 12:59 冻结的是 `8331bcb8…`（73,060 B）；13:01:51/55 最终补丁（近台但 `cobblestone<8` 仍先补便携台，T2 同步强化）把工作树更新为 `e293d893…`（73,594 B）。本轮打包发生在 13:02:25，`preflight.txt` 与包内 `agent.py` 均为 e293，运行用的就是该最终冻结版。

## 2. 官方结果（`world-prxdo03b/result.json`）

> 以下为便于阅读的格式化展示，字段与 `result.json` 原文一致（原文为单行 JSON）。

```json
{"episodes": [{"scenario": {"id": "stone-tools", "world_seed": 43, "max_steps": 6000,
                            "goals": ["wooden_pickaxe","cobblestone","stone_pickaxe","furnace"]},
               "status": "completed", "termination": "tutorial_step_limit",
               "metrics": {"task_success": false, "action_count": 6000, "deaths": 0,
                           "invalid_actions": 0, "execution_seconds": 461.6},
               "objectives": [{"id": "wooden_pickaxe", "completed": true},
                              {"id": "cobblestone",    "completed": true},
                              {"id": "stone_pickaxe",  "completed": false},
                              {"id": "furnace",        "completed": false}],
               "api": {"tokens": 0, "calls": 0, "fault": null}}],
 "summary": {"full_worlds": 0, "eligible": false, "mean_score": null}}
```

- 验证器：`python scripts/validate_practice.py --output review/runs/stone-v5c-2026-11-14` → **exit 1**；日志见 `review/runs/stone-v5c-2026-11-14/validator.log`：
  - `episodes[0].termination is 'tutorial_step_limit', expected 'tutorial_goals'`
  - `episodes[0].metrics.task_success is False, expected true`
- 动作总计：op0（移动/等待）2580、op3（攻击）3399、op4（合成）8、op5（装备）1、op6（放置）12；死亡 0、非法动作 0。
- 最终背包：`wooden_pickaxe×1、stick×2、apple×1、sapling×2、crafting_table×1、planks×3、dirt×2、cobblestone×3`；**无石镐、无熔炉**；第一张台仍在 (-216,72,-54)，但距井底 dy=5、3D>3，`nearby_tools.table=false`，判为不可用。
- 最终 `craftable`：`["lever","stick","wooden_button","wooden_pressure_plate"]`——石镐/熔炉全程未进入可合成列表。

## 3. 里程碑与 v5b 对比（同一 seed43）

| 事件 | v5b | **v5c** | 变化 |
|---|---|---|---|
| 首次原木入包 | 669 | **567** | −102 |
| 木板 / 木棍 | 670 / 671 | 568 / 569 | — |
| 工作台合成 | 1979 | **3047** | +1068 |
| 工作台放置确认 | 1979→1980 | **3052** | — |
| 木镐 | 1981 | **3053** | +1072（占预算 51%） |
| 首次圆石 | 2469 | **3142** | +673 |
| 第 2 / 第 3 圆石 | — | **3177 / 3206** | — |
| 石镐 | **2493** | **未达成** | v5c 回归 |
| 熔炉 | 未达成 | **未达成**（`craftable` 含 furnace 全程 0 步） | — |
| 最后有效位移 | — | **step 3223 后钉在 0.4 格范围（净位移 0.26）** | — |

- 合成计数（8 次）：`planks`×4、`stick`×1、`crafting_table`×2、`wooden_pickaxe`×1；**无 stone_pickaxe、无 furnace 合成尝试**。
- 圆石只拿到 **3 个**（3142/3177/3206），凑够石镐的 3 个之后**再未增加**。
- 木镐晚到 3053 的原因：木制阶段要求 `planks >= 7` 才做台子（给台 4 + 棍 2 + 镐 3 留料），它在 618 步只有 6 板，直到 3045 才捡到第 2 个原木补到 10 板——**这段比 v5b 多耗约 1100 步**（v5b 木板 671 → 台 1979 约 1300 步；v5c 618 → 3045 约 2400 步）。该段代码 v5c 未改，属真实轨迹方差/找树效率问题，但确实吃掉了石镐的时间预算。

## 4. 根因（公开轨迹证据：`steps.jsonl` 6000 行、`agent.log` 3483 行）

### 4.1 时间线

1. **3047** 合成第 1 张台；**3048/3050 放置失败 2 次→3052 确认成功**（准星 `crafting_table` d=1.2）。
2. **3055** 立刻又合成第 2 张「便携台」并背在身上（`portable table carried (1) -> continue`）。
3. **3092** 开始直下竖井（dirt→stone），**3142/3177/3206** 在 y=69/68/67 各拿 1 个圆石（共 3 个，已够石镐）。
4. **3207–3223** 在 y=67、1×1 竖井底连续 9 次 `place crafting_table`，**全部失败**（准星 stone，d≈1.2–1.6m）。
5. **3224** 起 `table placement abandoned after 9 failures`：此后**几乎每一帧（2776/2777）**都打印同一行并返回 `None`，直到 6000 步——共 **2776 次**，占 `agent.log` 的 **79.7%**。
6. **3224–6000（2777 步，46.3% 预算）**：只有 `noop`×1505 与 `attack`×1272；位置钉在 x∈[-215.7,-215.3]、z∈[-52.7,-52.3]、y∈[67.0,68.3]（**水平跨度约 0.4 格，首尾水平净位移仅 0.26 格，累计路径约 122 格**）；圆石恒为 3。

### 4.2 缺陷排序

- **D1（致命，状态机终态死锁）** `_table_step()`：当 `tables>=1` 且 `table_fail>=9` 时，逻辑是
  「打印 abandoned → `return None`」——**除「重新合成新台」（需 4 木板；本轮只有 3 木板且无木）外没有复位条件**。背包里台子还在，`table_fail` 永远 ≥9，
  于是此后每一帧都走这条路，**再也不可能合成任何需要台子的配方**（石镐/熔炉）。
  同时该分支无条件打日志，造成 2776 行刷屏，掩盖了其它诊断信息。
  *（该 `table_fail>=9` 终态逻辑在 HEAD `5f4a926` 中已存在，v5c 未改；本轮只是首次在真实轨迹中把它触发。对照：木制阶段的同类分支 `table_fail>=3` 会 `reset + relocate + walk`，石镐阶段却不会。）*

- **D2（致命，1×1 竖井无法脱困且不回台）** 石镐阶段为了拿石头 `dig_down` 直下 5 格（y72→67），
  玩家自封在 1 宽井底。已确认的台子在正上方 3–5 格、水平约 1.5 格（记录坐标 (-216,72,-54)；y=69 时 dy=3、y=67 时 dy=5），但
  `_near_table()` 要求 `|dy|<=2` 且 3D 距离 ≤3（y=69 时 dy=3、y=67 时 dy=5 都判“不在台旁”）；
  于是它不向上走 1 格回台，而是在井底反复尝试放新台。项目**没有任何 pillar/阶梯向上**动作。

- **D3（v5c 闸门放晚了，未覆盖真实失败点）** `_furnace_table_step()` 的入口条件是
  `stone_pickaxe >= 1`。本轮**石镐从未做出**，所以 v5c 新增的“回台/补台/有限找木”逻辑
  **一次都没有执行**（`agent.log` 无 `furnace readiness:*`、无 `furnace return:*`）。
  v5b 的失败点在“石镐之后”，v5c 把闸门加在石镐之后，但本轮的失败点被提前到了“石镐之前”。

- **D4（次要）** 井底每约 82 步：`dep_fail` 累到 80 → `stone dependencies unavailable -> explore for wood`（共 34 次）
  → `walk_policy` 走不动 → `nav: stuck -> jumping`(42) → `jump failed -> digging`(41) → 再 80 步。
  这是 D1 的下游症状，不是独立根因。

> 一句话：**v5c 修的是「石镐后无台无料」，但真实轨迹在「凑够 3 圆石后想合成石镐」这一步就先崩了——台子放置失败被永久放弃 + 直下竖井回不去。**

## 5. 建议的 v5d 最小修（本轮未改任何源码，等负责人批准）

1. **D1 状态复位**：`table_fail>=9` 只允许**一次性**日志（`self.table_abandoned_logged`），
   并在以下任一事件复位 `table_fail=0 / table_recover=None`：位置变化超过 2 格、捡到新料、
   重新合成台子、进入新阶段、或经过 N（如 40）帧。**禁止**进入不可逆的 `return None` 终态。
2. **D2 回台优先于放新台**：`table_pos` 已记录时，若 `|dy|<=8` 且水平距离 ≤3，
   先“向上/阶梯回台”（需要 pillar：跳起后在脚下放圆石/泥土；当前 3 圆石 + 2 泥土刚好够），
   **不要**在 1×1 井底尝试放置台子；把 `_near_table` 的 `|dy|<=2` 放宽为
   “同一竖井内即可视为可回台”，并显式区分“回台”与“在旁”。
3. **D3 闸门前置**：把“回台”能力从 `_furnace_table_step`（spick 后）下沉到**通用台子就绪逻辑**，
   在 `cobble>=3 && spick==0` 时也生效；即 `stone_pickaxe in craftable` 前的失败同样走“回台/补台”。
4. **D4 竖井预算**：`dig_down` 连续直下超过 4–6 格即停止继续直下，转而阶梯上行/在井壁开侧向台阶，
   避免“自封井底”；给“深度—回程”配预算。
5. 保留 v5b 已生效的 `wood_hits>=55` 与 walk 停滞恢复，不动官方包/评测器。

## 6. 产物与合规

- `review/runs/stone-v5c-2026-11-14/`：`preflight.txt`、`tests.log`（87 OK）、`build.log`（打包/加载校验）、`docker-run.log`、`docker-run.log.bak`、`docker-exitcode.txt`(0)、`docker-inspect.json`、`docker-inspect-full.json`、`docker-logs-raw.txt`、`validator.log`、`tests-after-run.log`、`world-prxdo03b/{result.json,partial-results.json,review.html,manifest.json,input.zip}`、`world-prxdo03b/evidence/1/{outcome.json,checkpoint.json,steps.jsonl(6000 行),agent.log(3483 行),budget.json,session.log,scene.json,trajectory.json,runtime-package.zip,agent/*,logs/mc_375.log}`。
- 一致性：`manifest.package_sha256 = 6c92ce8d…` == `input.zip` sha256；`input.zip`/`runtime-package.zip` 内 `agent.py` 均为冻结 `e293d893…`；`runtime-package.zip` 的 config 由评测器改写为临时模型端点，但 **tokens=0 / calls=0**，未调用模型。
- **日志说明（如实）**：`13:04:47` 出现一次同名并发 `docker run` 尝试，被 Docker 名称冲突拒绝（**未产生第二个容器、未影响正在运行的游戏**），该尝试截断了 `docker-run.log`。容器结束后已按 `docker logs -t`、`docker inspect` 与 runner footer 重建干净 UTF-8 版本，**原始截断文件保留为 `docker-run.log.bak`**。
- **容器与并发（如实）**：`docker ps -a` 全程仅 `ainb-stone-v5c` 一个本轮容器（现已 `Exited (0)`）；`ainb-stone-v5b` 为上一轮旧容器。未启动第二个游戏。
- 本轮的仓库写入范围仅为 `review/runs/stone-v5c-2026-11-14/` 与本文；**未修改源码/测试**（`agent/agent.py` 哈希仍为 `e293d893…`），未执行 commit/push，镜像未 pull、`--network none`、无密钥进入仓库。
- 清理：`docker rm ainb-stone-v5c`（当前保留供 inspect）；`C:\Users\31193\AppData\Local\Temp\ainb-stone-v5c-pkg` 可删。
