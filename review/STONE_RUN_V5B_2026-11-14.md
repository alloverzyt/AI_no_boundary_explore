# 石器 v5b 复跑与验收（stone-tools seed43，2026-11-14）

- 日期：2026-11-14（Asia/Shanghai）
- 授权：负责人批准的**唯一一次** v5b 正式 stone-tools 运行（新目录 + 新 temp + 命名容器）；运行前冻结代码，**本轮不改源码/测试、不 commit/push、不并发跑第二个游戏**。
- 仓库/分支：`C:\Users\31193\Documents\Dsh\AI_no_boundary_explore` / `feature/stone-checkpoint`
- 运行起点 HEAD：`74f1796`（`docs: analyze stone v3 deadline regression`）；冻结内容为未提交工作树（`agent.py` 等），打包哈希见 §1。
- 运行目录：`review/runs/stone-v5b-2026-11-14`（唯一）；打包 temp `C:\Users\31193\AppData\Local\Temp\ainb-stone-v5b-pkg`；命名容器 `ainb-stone-v5b`。
- 结论：**运行本身完整有效（rc=0、产物齐全），但游戏目标真实失败 3/4**：木镐、圆石、石镐达成，**熔炉未达成**；`termination=tutorial_step_limit`、`task_success=false`、验证器 exit 1。**不计为石器验收通过。**

## 0. 验收结论（按要求 4/4 + validator exit 0）

| 判定项 | 要求 | 实测 | 结果 |
|---|---|---|---|
| objectives | 4/4 | **3/4**（`furnace=false`） | ✗ |
| termination | `tutorial_goals` | `tutorial_step_limit` | ✗ |
| task_success | `true` | `false` | ✗ |
| validator | exit 0 | **exit 1**（2 条错误） | ✗ |
| 运行完整性 | rc=0、产物齐全 | rc=0、result/outcome/checkpoint/steps/agent.log 等齐全 | ✓ |

> 结论明确：**未通过验收**。运行不是基础设施失败，失败点是策略/环境交互（下挖后无法回到工作台），详见 §4。

## 1. 冻结代码、包与运行配置

| 项 | 值 |
|---|---|
| 冻结源码 | `agent/agent.py` sha256 `702e0adea6d776c31bb300e4d8381f17df8663ea75bf67f96a4056ddd266bad9`（68,100 B，1359 行） |
| 冻结测试 | `tests/test_pickup_direction.py` `0f05e4aa…`、`tests/test_stone_progression.py` `e0be0fad…`、`tests/test_woodcraft_stability.py` `c9fc9244…` |
| 包 | 官方开发包 + 冻结 `agent.py`/`action_items.json`/`minecraft_actions.py`/`planner.py`/`vision.py`，`model=offline`；`agent.zip` **31,584 B**，sha256 `d0a6bb286acf0ae9638f7b3875be0c2bdc6f75d74e1f0c860da0548832cf7f1f` |
| 包内 agent.py | sha256 `702e0ade…` == 冻结源码；`manifest.package_sha256 == input.zip sha256 == d0a6bb28…` |
| 包校验 | 官方 `package_config` / `load_agent` 通过（`Agent.act` callable）；config `model={name:"offline",api_url:"",api_key:""}` |
| 测试 | `python -m unittest discover -s tests` → **Ran 80 tests, OK, exit 0** |
| 镜像 | `streetartist/uestc-minecraft-controller:latest`（本机缓存，**未 pull**；`4f0164fc2a36…`） |
| 容器 | `ainb-stone-v5b`，id `57287860a2c17c3743cfdc3a474c115b5111973b327c7d72cb295a224e8b3682`；started 12:46:23 / finished 12:53:49（elapsed 446.5s），`ExitCode=0`，当前 `exited`，保留供 inspect |
| 约束 | `--network none`、`--cpus 4 --memory 4g --memory-swap 4g --pids-limit 512 --shm-size 512m`、`--only stone-tools --no-video`；无模型调用（tokens=0 / calls=0） |

## 2. 官方结果（`world-h7tzowts/result.json`）

```json
{"episodes": [{"scenario": {"id": "stone-tools", "world_seed": 43, "max_steps": 6000,
                            "goals": ["wooden_pickaxe","cobblestone","stone_pickaxe","furnace"]},
               "status": "completed", "termination": "tutorial_step_limit",
               "metrics": {"task_success": false, "action_count": 6000, "deaths": 0,
                           "invalid_actions": 0, "execution_seconds": 386.9},
               "objectives": [{"id": "wooden_pickaxe", "completed": true},
                              {"id": "cobblestone",    "completed": true},
                              {"id": "stone_pickaxe",  "completed": true},
                              {"id": "furnace",        "completed": false}],
               "api": {"tokens": 0, "calls": 0, "fault": null}}],
 "summary": {"full_worlds": 0, "eligible": false, "mean_score": null}}
```

- 验证器：`python scripts/validate_practice.py --output review/runs/stone-v5b-2026-11-14` → **exit 1**；日志见 `review/runs/stone-v5b-2026-11-14/validator.log`：
  - `episodes[0].termination is 'tutorial_step_limit', expected 'tutorial_goals'`
  - `episodes[0].metrics.task_success is False, expected true`
- 动作总计：op0（移动/等待）2805、op3（攻击）3176、op4（合成）9、op5（装备）1、op6（放置）9；死亡 0、非法动作 0。
- 最终背包：18 圆石、3 木板、石镐×1、木镐×1、石头×25、泥土×11、树苗×4、红花×1；**无工作台**。

## 3. 里程碑与 v4 对比（同一 seed43）

| 事件 | v4 | **v5b** | 变化 |
|---|---|---|---|
| 首次原木入包 | 4615 | **669** | −3946 步 |
| 木板 / 木棍 | 4616 / 4617 | 670 / 671 | — |
| 工作台合成 | 5032 | 1979 | −3053 |
| 木镐 | 5034 | **1981** | −3053（占预算 33%，v4 为 84%） |
| 首次圆石 | 未达成 | **2469** | 新达成 |
| 石镐 | 未达成 | **2493**（余 3507 步） | 新达成 |
| 熔炉 | 未达成 | **未达成**（`craftable` 含 furnace 全程 0 步） | — |

- “打掉原木 → 捡取”触发：v4 **70 次**，v5b **8 次**（其中 3 次 `reached drop point`、9 次 `blocked -> jump`、2 次 `blocked -> sidestep`）；首次原木提前到 669 步，证明 `wood_hits >= 55` 阈值修复在真实轨迹中生效，假破坏空转基本消失。
- v4 的 851 步 `dig_down` walk 原地死锁**未再出现**；本轮实际挖到圆石并做出石镐，说明 walk 停滞恢复修复有效。
- 合成计数：`planks`×4、`stick`×1、`crafting_table`×2、`wooden_pickaxe`×1、`stone_pickaxe`×1；**无 furnace 合成尝试**。

## 4. 新的真实瓶颈：下挖后无法回到工作台，熔炉无机会

公开轨迹证据（`steps.jsonl` 6000 行、`agent.log` 473 行）：

1. 1979 合成工作台，1980 放下（1980–1982 近台）；2239/2240 再合成第二个工作台；2478–2492 连续 8 次放置尝试（`table placement failed` 7 次），2492 才成功放下第二个台（2492–2494 近台）。
2. 2493 在近台状态合成**石镐**（当时圆石仅 3，够镐不够熔炉）。
3. 2494 之后继续下挖：y 从 69 降到 **46**（约 23 格），两个工作台都留在 y≈69/72 地表。
4. 2494 之后 3507 步（58% 预算）被钉在井底：
   - **2569 步 y≤47**；x 范围仅 2.4 格、z 范围仅 2.4 格；
   - 水平路径累计仅 101.6 格，**首尾水平净位移仅 (0.26, 0.29)**——基本原地振荡；
   - `nav: stuck -> jumping` / `jump failed -> digging` 各 39 次，始终未能回到地表。
5. 熔炉**0 次进入 `craftable`**：结束时背包有 **18 圆石** + 3 木板，但附近无工作台（`nearby_tools.table=true` 仅 1980–1982、2492–2494 共 6 步）。
6. `agent.log` 中 **37 次** `stone dependencies unavailable -> explore for wood`：它想再要木头做新工作台（仅剩 3 木板，工作台需 4），但被困井下既回不去、也找不到树。

**根因排序**：

- **P0 竖直脱困/回程缺失**：下挖 20+ 格后没有 pillar/阶梯/回地表路径，近 60% 预算耗在井底。
- **P1 工作台只做“附近”判定、不做“回台”导航**：`table_pos` 有记录（`_track_table`），但只用于 `_near_table` 的三维距离判断；离开后（水平/垂直远超阈值）没有导航回台逻辑。因此 18 圆石永远无法合成熔炉。
- **P2 合成时机**：2492–2494 近台窗口内只有 3 圆石，确实不够 8；但采满 8 后应回台合成，而当前实现没有“采满即回台”的出口。

## 5. 最小下一修建议（本轮未改源码，等负责人决定）

1. **P0 竖直脱困**：`dig_down` 下挖超过阈值（如 6–8 格）后优先用阶梯/侧向台阶或 pillar 返回；为下挖增加“深度—回程”预算，禁止在无回程路径时持续直下。
2. **P1 回台导航**：放置 `crafting_table` 时记录公开坐标；目标需要合成且最近工作台 3D 距离超阈值时，先导航回台（含向上脱困），而不是 `explore for wood`。
3. **P2 采满即回**：目标含熔炉时，采满 8 圆石后立即回台合成，不在井底继续空转。
4. 保持已生效的 `wood_hits >= 55` 与 `dig_down` walk 停滞恢复；v5b 已证明两者有效，不宜回退。

## 6. 产物与合规

- `review/runs/stone-v5b-2026-11-14/`：`preflight.txt`、`docker-run.log`、`docker-run.log.bak`、`docker-exitcode.txt`(0)、`docker-inspect.json`、`docker-logs-raw.txt`、`validator.log`、`world-h7tzowts/{result.json,partial-results.json,manifest.json,review.html,input.zip}`、`world-h7tzowts/evidence/1/{outcome.json,checkpoint.json,steps.jsonl(6000 行),agent.log(473 行),budget.json,session.log,scene.json,trajectory.json,runtime-package.zip,agent/*,logs/*}`。
- 一致性：`manifest.package_sha256 = d0a6bb28…` == `input.zip` sha256；`input.zip`/`runtime-package.zip` 内 `agent.py` 均为冻结 `702e0ade…`；`runtime-package.zip` 的 config 由评测器改写为临时模型端点，但 **tokens=0 / calls=0**，未调用模型。
- **日志说明（如实）**：12:46:53 出现一次同名并发启动尝试，被 Docker 名称冲突拒绝，**未产生第二个容器、未影响正在运行的游戏**；该尝试截断了 `docker-run.log`。容器结束后已按 `docker logs -t`、`docker inspect` 与 runner footer 重建为干净 UTF-8 版本，**原始截断文件保留为 `docker-run.log.bak`**。
- **并发与提交（如实）**：`docker ps -a` 全程仅 `ainb-stone-v5b` 一个容器，已 `Exited (0)`；本轮未启动第二个游戏。运行结束后（12:55:34）分支上出现并发提交 `5f4a926 fix: improve mining recovery and log pickup`（非本轮执行），`origin/feature/stone-checkpoint` 仍为 `74f1796`（**未 push**）；工作树四个冻结文件哈希与运行前一致，本次运行包来源不受影响。
- 本轮的仓库写入范围仅为 `review/runs/stone-v5b-2026-11-14/` 与本文；**未修改源码/测试**，未执行 commit/push，镜像未 pull、`--network none`、无密钥进入仓库；容器保留可 `docker rm ainb-stone-v5b` 清理。
