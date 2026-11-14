# Woodcraft 稳定性隔离修复报告（task-9）

- 日期：2026-11-14（Asia/Shanghai）
- worktree：`C:\Users\31193\Documents\Dsh\AI_no_boundary_woodfix`
- 分支：`fix/woodcraft-stability`，基线 commit `c0619a075b484d258bb1073d61ac87e222d57710`
- 授权：负责人（lead）授权在独立 worktree 内按证据修复并实跑，不 commit/push，不写主 branch，不改主目录 `AI_no_boundary_explore`。
- 目标：PR6 云端 woodcraft seed42 FAIL（3/5）的隔离修复；至少两次独立 seed42 实跑 5/5 才声称稳定；保留所有失败。

## 0. 结论（如实）

| 项 | 结果 |
|---|---|
| 修复范围 | 仅 `agent/agent.py`（+78 行，无删除、无整文件 diff，CRLF 保持）；新增 `tests/test_woodcraft_stability.py`（4 用例，CRLF） |
| 单元测试 | `python -B -m unittest discover -s tests` → **47/47 OK**（原 43 + 新 4）；`python -m py_compile agent/agent.py` OK |
| 实跑（最终源码） | **2 次独立 seed42 woodcraft 均 5/5**：`woodcraft-fix3-run1` 958 步、`woodcraft-fix3-run2` 958 步；两次 `docker exit=0`、0 death、0 invalid、0 模型调用 |
| 失败保留 | `woodcraft-fix-run1`（尝试1，0/5，导航门槛硬放宽，已废弃）、`woodcraft-fix2-run2`（尝试2，3/5，**复现云端同型失败**，用于定位主因）；两者产物均保留 |
| 镜像/网络 | 使用本机缓存官方镜像 `streetartist/uestc-minecraft-controller:latest`（`sha256:4f0164fc2a36…`），运行前后 ID 不变；`--network none`，未 pull、未联网调用模型 |
| 遗留容器 | 我的运行全部 `--rm`，未遗留容器；`docker ps -a` 仅见其他 worker 的容器 `c21fa88199a1`（未触碰） |
| git | 未 `git add`、未 commit、未 push。实跑产物写在 `review/runs/`（`.gitignore` 的 `runs/`，本地保留） |

> 诚实边界：这是 **woodcraft 教学局 seed42** 的本地官方镜像验证。本地渲染/时序与云端 runner 存在细微差异（见 §6），修复前本地也有 5/5，因此**不能**证明"云端一定过"；能证明的是：从云端公共失败轨迹统计出的真实机制（打掉原木不捡掉落物）在本地被**独立复现成同样的 3/5**，修复该机制后本地该失败路径转为 5/5，且两次独立实跑 5/5。不对其它 seed、stone-tools/iron-age 或正式隐藏种子作结论。

## 1. 约束与合规

- 未修改：官方场景/practice 数据、官方评测器（`evaluation_adapters/`、`practice.py`）、`vision.py`、`planner.py`、`config.json`、模型端点/凭据、1500 步上限、结果验收标准。
- 只使用公开观测/动作契约（`noop_action`、`inventory`、`crosshair_hit`、`position`、`orientation`、`craftable`、`last_action`），未读环境内部 voxels，未改官方包。
- 打包：独占 temp 目录复制官方开发包 `ai_no_boundary_task5_pkg`，用修复后源码覆盖 7 个 agent 文件，离线配置 `model={"name":"offline","api_url":"","api_key":""}`，执行官方 `pack_agent.py --policy offline --output agent.zip --extra planner.py vision.py`。
- 包内 `agent.py` sha256 与仓库当前 `agent/agent.py` 完全一致（§5），每局 `manifest.json.package_sha256` 与本局包一致。

## 2. 根因分析（基于 PR6 公共失败轨迹 `world-nfiy9gyv` 的 steps.jsonl 统计）

失败轨迹：seed42、1500 步、`tutorial_step_limit`、3/5（log/planks/stick 有，crafting_table/wooden_pickaxe 无）、0 death/0 invalid、0 模型调用。

### 2.1 主因：原木打掉后不去捡掉落物（背包永远只拿到 1~2 个原木）

证据 1（破坏确实发生）：各运行对同一原木块的连续攻击段都约 **65 帧**（统计整个 1500 步：`attack_run` 长度 65~72；手打木头约 60 tick，与破坏耗时一致），随后准星换格 —— 说明**木块被打掉了**。

证据 2（掉落在 2~4 格外，旧逻辑直接走开）：

| 轨迹 | 长原木攻击段（step） | 攻击时玩家到木块水平距离 | 之后 25 步内拿到 log？ |
|---|---|---|---|
| 云端失败 | 134-200 / 320-384 / 475-541 / 542-608 / 1157-1223 / 1230-1294 | 2.1 / 4.42 / 2.84 / 2.84 / 3.83 / 2.89 | 仅 step227（第一根）有；后 5 根**全部没有** |
| 本地 task5 成功 | 134-200 | 2.1 | 有（step215） |
| 本地 run2（复现失败） | 1009-1073（key `(-237,70,-135)`） | 2.7 | **没有**：65 帧后准星换格，背包始终无 log |

- 掉落物位于被破坏方块中心；玩家只有在其附近（约 1~1.5 格）才会拾取。旧 `seek_and_break` 在 `dist<=REACH(4.0)` 就持续攻击，打掉后立即转去下一格/走开，**从不返回掉落点**。
- 云端失败轨迹打了至少 6 根原木却只有 2 根进入背包；只要每根都捡起，材料（planks≥7、stick≥2）早已足够做工作台+木镐。
- 本地复现：`woodcraft-fix2-run2`（仅含旧的"树冠上限+导航侧移"修复、无捡取修复）得到与云端**完全相同的 3/5**（log/planks/stick 有、crafting_table/wooden_pickaxe 无），进一步确认主因。

### 2.2 次因：原地前进卡死（导航恢复死区）

- 云端失败轨迹 step **1358-1500**：连续 143 步 `action[0]=1`（前进）但 `position` 完全冻结、准星 wood 距离恒 5.0（>REACH）。
- 原因：`nav_step` 用「相对 anchor 的净位移」判定 —— 重锚要求 `moved>=2.0`，卡住判定是 `moved<1.0`；当净位移落在 `[1.0,2.0)` 时既不重锚也永不触发恢复，`nav_count` 无限增长。
- 直接放宽 `moved<2.0` 被实测否决：`woodcraft-fix-run1` 在 step 430 起触发 jump→dig→detour 循环，把已站立的 agent 挖到 y≈66 并对着 stone 空打，**0/5**（失败产物保留）。该尝试已回滚。

## 3. 修复内容（最小、仅木制）

`agent/agent.py`（+78 行，0 删除；CRLF 1001 行全部 CRLF）：

1. **原木掉落物捡取（主修复）**
   - `LOG_PICKUP_STEPS = 16`（[agent.py:39](../agent/agent.py#L39)）。
   - `seek_and_break`：记录正在攻击的原木块 `wood_key/wood_hits`；当准星换格且已攻击 ≥8 帧（[agent.py:250](../agent/agent.py#L250)。`_start_log_pickup` 见 [agent.py:466](../agent/agent.py#L466)），判定该格已打掉，`act` 优先前进 16 帧走向掉落点（[agent.py:835](../agent/agent.py#L835)）。
   - 背包出现 `log/log2/wood` 立即取消捡取、恢复原有合成/采集进度；不打断可立即完成的木镐合成。
2. **导航短窗零位移侧移（次修复，按 lead 建议）**
   - 用「每帧真实位移」短窗（[agent.py:506](../agent/agent.py#L506)）代替净位移：连续 12 帧零位移才判定被挡（曲线行走每帧仍有位移，不会误判）。
   - 只做 90° 侧移换方向（[agent.py:629](../agent/agent.py#L629)），最多 3 个方向；**不做 jump/dig**，避免把已站立 agent 挖进地下；并保留原 `moved<1.0` 卡住逻辑不变（注释中记录死区已知限制与实测回归证据 [agent.py:612](../agent/agent.py#L612)）。

未改动 `vision.py` / `planner.py` / 场景 / 评测器 / 配置 / API / 步数 / 验收标准。

## 4. 测试（先失败后修复）

新增 `tests/test_woodcraft_stability.py`（4 用例，CRLF），全部只使用公开观测/动作契约：

| 用例 | 复现的失败序列 | 旧代码表现 |
|---|---|---|
| `test_broken_log_is_walked_into_for_pickup` | step 1009-1073：同一 wood 块连打 70 帧后准星换到 6.4 格外 leaves | 无 `pickup_steps` 状态、打掉后首帧是转向而非"前进捡取"，且捡到 log 后不会立刻恢复合成 → FAIL |
| `test_short_wood_look_does_not_fake_a_break` | 只打 3 帧就丢目标 | 不得误触发捡取（回归保护） |
| `test_blocked_walk_sidesteps_instead_of_walking_forever` | step 1358-1500：anchor 净位移 1.2、每帧零位移 | 30 步内只有前进、无侧移 → FAIL |
| `test_short_window_still_counts_curved_walking_as_progress` | 每帧 0.3 格曲线行走 | 不得误判卡住（回归保护） |

- 旧代码复核：对 `HEAD` 的 `agent.py` 运行同一"70 帧打木后换格"序列，`pickup_steps` 不存在、换格后首帧为转向（`[0,0,0,12,13,0,0,0]`）而非前进捡取，证明该用例在旧代码上失败。
- 全套：**Ran 47 tests … OK**；`py_compile` 通过；`agent/agent.py` 与测试文件均为 CRLF，`git diff` 仅 +78/-0，无整文件行尾 diff。

## 5. 实机验证（官方缓存镜像、离线、seed42、1500 步上限）

### 5.1 运行方式（CI 同等约束，未 pull）

```text
docker run --rm --init --platform linux/amd64 --cpus 4 --memory 4g --memory-swap 4g \
  --pids-limit 512 --shm-size 512m --network none \
  --mount type=bind,source=<独占temp>/woodfix_accept_pkg,target=/pkg \
  --mount type=bind,source=<worktree>/review/runs,target=/workspace/review/runs \
  --workdir /tmp -e PYTHONPATH=/pkg -e PYTHONDONTWRITEBYTECODE=1 \
  --entrypoint xvfb-run streetartist/uestc-minecraft-controller:latest \
  -a python3 -u /pkg/practice.py --package /pkg/agent.zip --scenes /pkg/practice-scenes.json \
  --output /workspace/review/runs/<RUN_ID> --only woodcraft --no-video
```

- 最终源码包：`agent/agent.py` sha256 `adeca3133f17ee52dde19936d20623978d130fe4c7560fe3e7612c9e1881672d`；
  `agent.zip` sha256 `33086c4a7ee71b1c09ea07f83dd432e311fda3f0a72fe6da1d97a2e3392df48a`（两局 `manifest.json.package_sha256` 均为该值）。
- 镜像 `sha256:4f0164fc2a366adf8290292f0f3fe438d40bcbb2ea104f2a74f0a3e8a088bfa7`，运行前后不变；无 pull。
- 宿主 stdout/stderr 直接重定向到每局 `docker-run.log`（UTF-8 原始字节），docker CLI 退出码写入 `review/runs/<RUN_ID>/docker-exit-code.txt`。

### 5.2 全部运行结果（失败均保留）

| 运行目录 | 代码版本 | docker exit | 结果 | 步骤 | 目标 | 说明 |
|---|---|---|---|---|---|---|
| `dbg-woodcraft-1` | 修复前源码 + 临时调试日志 | 0 | 5/5 | 1091 | 全达成 | 修复前本地基线（0 death/invalid，0 模型调用）；说明本地修复前就能 5/5 |
| `woodcraft-fix-run1` | 尝试1：直接放宽导航 moved<2.0 | 0 | **0/5** | 1500 | 全未达成 | 回归：step 430 起 jump/dig 循环挖到地下；已回滚 |
| `woodcraft-fix2-run1` | 尝试2：树冠上限+导航侧移 | 0 | 5/5 | 1308 | 全达成 | 未含捡取修复 |
| `woodcraft-fix2-run2` | 尝试2 | 0 | **3/5** | 1500 | log/planks/stick | **复现云端同型失败**（40+ 起 wanders，打掉原木未捡） |
| `woodcraft-fix3-run1` | **最终源码** | 0 | **5/5** | 958 | 全达成 | 第一次独立验收 |
| `woodcraft-fix3-run2` | **最终源码** | 0 | **5/5** | 958 | 全达成 | 第二次独立验收 |

最终两局明细：

| 项 | run1 | run2 |
|---|---|---|
| termination | tutorial_goals | tutorial_goals |
| task_success | true | true |
| action_count | 958 | 958 |
| deaths / invalid_actions | 0 / 0 | 0 / 0 |
| execution_seconds | 78.5 | 74.0 |
| 首次获得 log / planks / stick | 213 / 214 / 215 | 195 / 196 / 197 |
| crafting_table / wooden_pickaxe | 956 / 958 | 882 / 958 |
| `api.tokens / calls / fault` | 0 / 0 / null | 0 / 0 / null |
| `log broken -> walk to drop` 日志次数 | 4 | 3 |
| 包 sha256 与源码一致 | 是 | 是 |

对比：捡取修复前本地最好 1198/1308 步、且 `fix2-run2` 1500 步 3/5；修复后 958 步 5/5，首次原木从 777/779 步提前到 195/213 步 —— 与"打掉即去捡"的机制一致。

## 6. 诚实记录的限制与未验证项

1. **本地无法复现云端渲染差异**：本地两次运行的视觉 offset 略有不同（如 `off=0.61` vs `0.69`），轨迹会混沌分叉；修复前本地已有 5/5（`dbg-woodcraft-1`），因此本地通过**不等于**云端必然通过。本报告的可信链条是：云端公共轨迹统计 → 定位"打掉不捡"机制 → 本地独立复现同型 3/5（`fix2-run2`）→ 修复该机制后同一环境两次 5/5。
2. **导航侧移修复在最终两局未被触发**（最终两局 958 步即完成，`sidestep` 计数 0）；它在尝试2 的实跑中被触发过（`fix2-run1` 1 次、`fix2-run2` 2 次）且未造成该两局失败的新错误；单独效果仅由单元测试验证。
3. 只验证 woodcraft 教学局 seed42；未验证 stone-tools/iron-age、隐藏种子、真实 GitHub Actions CI；未开视频回放。
4. `dbg-woodcraft-1` 为诊断用临时插桩包（含临时 state.log 写入代码），**不是**最终提交源码；最终验收为 `fix3-run1/run2`。
5. 未推送、未 commit、未 `git add`；`review/runs/` 被 `.gitignore` 忽略，仅本地保留。

## 7. 产物索引

- 失败保留：`review/runs/woodcraft-fix-run1/`（0/5）、`review/runs/woodcraft-fix2-run2/`（3/5）
- 最终验收：`review/runs/woodcraft-fix3-run1/`、`review/runs/woodcraft-fix3-run2/`（各含 `result.json`、`steps.jsonl`、`agent.log`、`docker-run.log`、`docker-exit-code.txt`、`image-before/after.txt`、`run-meta.txt`）
- 中间成功运行：`review/runs/woodcraft-fix2-run1/`、`review/runs/dbg-woodcraft-1/`
- 每局 `world-*/evidence/1/` 下有官方 `outcome.json`、`checkpoint.json`、`session.log`、`logs/`、`runtime-package.zip`。

## 8. Freeze 通知（交 lead 集成）

- 源码 freeze：`agent/agent.py`（sha256 `adeca3133f17ee52dde19936d20623978d130fe4c7560fe3e7612c9e1881672d`）、新增 `tests/test_woodcraft_stability.py`；**未 commit、未 add、未 push**。
- 复验命令：`python -B -m unittest discover -s tests`（47/47）、`python -m py_compile agent/agent.py`。
- 合并建议：只取这两个文件；`review/runs/` 为本地产物（gitignored），报告为本文件 `review/WOODCRAFT_STABILITY_2026-11-14.md`。
