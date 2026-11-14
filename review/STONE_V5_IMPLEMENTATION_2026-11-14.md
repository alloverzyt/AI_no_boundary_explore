# 石器 v5 最小修复：pickup 定向 + dig_down walk 停滞恢复（2026-11-14）

- 日期：2026-11-14（Asia/Shanghai）
- 授权：lead 批准 v5 最小修复（当前 `feature/stone-checkpoint`）；**先红后绿、全套测试、freeze 报告；未启动 v5 游戏**，等 lead 确认。
- 仓库/分支：`C:\Users\31193\Documents\Dsh\AI_no_boundary_explore` / `feature/stone-checkpoint`（HEAD `74f1796` + 本次未提交改动；分支跟踪 `origin/feature/stone-checkpoint`，我未 push）
- 本轮写入：`agent/agent.py`、`tests/test_pickup_direction.py`（新增）、`tests/test_stone_progression.py`、`tests/test_woodcraft_stability.py`（既有测试随行为变更同步）、本报告。未改官方包/评测器/模型；未动 woodfix worktree。

## 0. 结论

| 项 | 结果 |
|---|---|
| v5 代码 | pickup 从“盲目前进 16 步”改为**朝被打掉原木公开坐标转向/靠近**，带位置停滞恢复与预算上限 |
| v5 代码 | `dig_down` 的“目标不在攻击距离”walk 分支加入公开 position 短窗停滞检测（12 帧 jump、36 帧 turn、再失败 walk_policy） |
| 回归 | **全套 77 tests OK，exit 0**（70 集成基线 + 新增 7） |
| 编译 | `py_compile` exit 0 |
| 行尾/差异 | 编辑文件全 CRLF；`git -c core.autocrlf=false diff --stat` 与 `git diff --ignore-space-at-eol` 一致（无整文件行尾 diff） |
| 游戏 | **未启动 v5**（按要求等 lead 确认）；容器 `ainb-stone-v4` 仍为 exited(0) 保留 |

## 1. 公开轨迹证据（v4 seed43，只读分析）

### 1.1 木制 pickup 为什么不可靠

对 `review/runs/stone-v4-2026-11-14/world-rdzxn2a2/evidence/1/steps.jsonl`（6000 步）做公开坐标分析：

- 识别“破块候选”（准星 wood 连续 ≥8 帧后换格）：**56 次**；
- 之后 16 步内 log 真正进背包：**1/56**；
- 拾取期间移动方向与“→原木坐标”的点积：朝目标 **5**、背向 **0**、净位移≈0 **51**；
- 与 `agent.log` 的 **70 条** `log broken -> walk to drop`、首 log 第 4615 步一致：**旧“向前 16 步”在 51/56 情况下根本走不动**（被树叶/地形挡住，位置冻结），且没有方向校正。

### 1.2 yaw/前进方向约定（由公开 steps 拟合，写入实现）

- 纯前进动作样本 673 个，比较 `Δposition` 与各候选方向：`forward = (-sin(yaw), cos(yaw))` 平均点积 **0.725**（其余候选 ≤0.18）；
- 转向动作 171 个：`yaw_after - yaw_before = 15.0 * (action[4] - 12)`（中位数 15.0、标准差 0.0）。
- 因此“朝目标点”的期望 yaw = `atan2(-(tx-px), (tz-pz))`，每帧最多转 |12| 档（180°）。

### 1.3 dig_down walk 为什么 851 步空转

v4 第 ~5150–6000 步：位置冻结 `(-218.7,71,-41.7)`、准星 `stone` 但 `d=4.62 > REACH(4.0)`、动作连续 851 次 `[1,0,0,12,12,0,0,0]`。原 `dig_down` 在“目标不在攻击距离”时只 `walk(forward=1)`，无位置进度检测；攻击分支的 `dig_stall` 只在 REACH 内生效，所以不会触发恢复。

## 2. 实现（`agent/agent.py`）

### 2.1 pickup 定向与有界恢复

- 破块时 `_start_log_pickup` 记录**被打掉方块的公开 traced 坐标**（`wood_key`）到 `pickup_target`，清空旧状态；
- `_pickup_step(obs)`：
  - 若 `log/log2/wood` 数量增加 → 立即清除 pickup 恢复正常进度；
  - 计算水平距离与期望 yaw：距离 ≤1.2 → 站一帧（noop）让环境完成拾取后清除；否则按 `atan2` 计算转向档位（`round(delta/15)`，clamp ±12）先转向，方向对齐后前进；
  - **位置短窗停滞**：连续 3 帧零水平位移 → jump+forward；连续 6 帧仍零位移 → 侧移（turn 60°）；侧移后再次阻塞 → 放弃该掉落物（有界），避免又 16 步盲走；
  - 由 `LOG_PICKUP_STEPS`（16）封顶，清除时重置所有 pickup 状态；
- `act()` 的木制 pickup 分支改为调用 `_pickup_step`，不再直接 `walk(forward=1)`。

### 2.2 dig_down walk 分支停滞恢复

- “目标不在 REACH”的 walk 分支记录公开 `position`：若与上一帧水平位移 <0.05 → `dig_walk_stall += 1`，否则清零并重置 turn 计数；
- `>=12` 帧 → `walk(forward=1, jump=True)`；`>=36` 帧 → `turn(amount=6)`（90°）；再次累计 36 帧 → `walk_policy` 换路线并清零；
- 攻击分支（目标在 REACH 内）进入时清空 `dig_walk_*`，**不影响连续攻击与既有 `dig_stall`**（有测试防回归）。

### 2.3 reset 清理

新增字段（`pickup_target/pickup_last_pos/pickup_stall/pickup_blocked/dig_walk_last/dig_walk_stall/dig_walk_turns`）均在 `reset()` 清零/置 None；`_dig_give_up/_dig_relocate` 同步清理 walk 状态。

## 3. 测试（先红后绿）

新增 `tests/test_pickup_direction.py`（4 例，seed42/seed43 公开坐标）：

| 用例 | 断言 | 修复前 |
|---|---|---|
| `test_seed43_pickup_turns_toward_broken_log` | seed43 v4 坐标下，pickup 首帧转向期望 yaw 档位、非攻击 | ERROR（无 `pickup_target`） |
| `test_seed42_pickup_walks_forward_when_facing_target` | 方向对齐时前进、不改 yaw | ERROR |
| `test_pickup_stops_when_reaching_drop_point` | 已到掉落点附近时站一帧并清除 pickup | ERROR |
| `test_pickup_blocked_jumps_and_is_bounded` | 位置冻结时出现 jump、侧移、且 16 步内清除 pickup | ERROR |

`tests/test_stone_progression.py` 追加 3 例：

| 用例 | 断言 | 修复前 |
|---|---|---|
| `test_dig_down_walk_stall_jumps_then_turns` | d=4.62>REACH 且位置冻结：≤14 步内 jump，≤42 步内转向 | FAILED（只有 walk） |
| `test_dig_down_stall_recovery_does_not_break_continuous_attack` | REACH 内 6 帧全为攻击、`dig_walk_stall==0` | 通过（防回归） |
| `test_reset_clears_v5_pickup_and_walk_state` | reset 后新状态全清 | FAILED（AttributeError/未清） |

`tests/test_woodcraft_stability.py` 的 `test_broken_log_is_walked_into_for_pickup` 按 v5 语义同步：pickup 必须保持非攻击并向掉落点移动；fixture 位置恒定时允许有界 jump/sidestep（旧断言“连续 6 帧只能 forward”对应被替换的旧实现）。

证据：

| 阶段 | 命令 | 结果 |
|---|---|---|
| 修复前（红） | `python -m unittest tests.test_pickup_direction -v` | **ERROR ×4**（无 pickup_target 状态） |
| 修复前（红） | dig 新增 3 例 | **FAILED (failures=2, errors=1)** |
| 修复后（绿） | `python -m unittest tests.test_pickup_direction -v` | **Ran 4 tests … OK** |
| 修复后（全套） | `python -m unittest discover -s tests` | **Ran 77 tests … OK，exit 0**（70 + 7） |
| 编译 | `python -m py_compile agent/agent.py tests/test_pickup_direction.py tests/test_stone_progression.py tests/test_woodcraft_stability.py` | exit 0 |
| 行尾/差异 | 编辑文件 CRLF（agent.py 1355 行，LF-only=0）；raw diff == ignore-eol diff | `agent/agent.py +123/−?`、测试合计，见 `git diff --stat` |

## 4. 未验证项与风险（v5 未跑游戏）

1. **尚未实跑 v5**：以上是单元级修复与公开轨迹分析；能否把首 log 从 4615 步显著提前、以及 dig_down 脱困能否采到 3+8 圆石，必须等 lead 确认后用**唯一新目录/命名容器/UTF-8+退出码**流程跑一次才能判定。
2. pickup 恢复的 jump/侧移可能带来少量额外步数；`LOG_PICKUP_STEPS=16` 未延长（符合“不要只延长 forward 预算”）；若实跑仍捡不到，需再分析“掉落点垂直位置/拾取半径”与“等待拾取帧数”。
3. dig_down `walk_policy` 出口可能触发 nav 的另一次恢复；本次只验证了单元层不破坏连续攻击，真实收益待 v5 实跑。
4. wood-worker 仅做只读分析（lead 已说明）；本轮未改 woodfix worktree，但共享 `tests/test_woodcraft_stability.py` 有 1 处语义同步，集成时请复核。
5. 工作树另有他人对 `review/STONE_V3_ANALYSIS_2026-11-14.md` 的修改（非我），未处理。

## 5. 交付状态

- 代码/测试已改完，**未 commit、未 push**；镜像未 pull、无密钥。
- **v5 运行记录（无效）**：授权后曾启动 `ainb-stone-v5`（12:42:10），负责人发现阈值错误后 12:42:54 执行 `docker stop` 终止（`ExitCode=143`，elapsed≈43.7s，无 result.json）；容器已 `rm -f`。该运行**无效、不计正式 v5、输出目录不复用**，详见 `review/runs/stone-v5-2026-11-14/ABORTED_INVALID.md`。
- 阈值修复（见 §6）完成后再次 freeze；等待负责人授权后用**新目录** `review/runs/stone-v5b-2026-11-14` + 命名容器 `ainb-stone-v5b` 跑正式 v5。
- 现有容器 `ainb-stone-v4` 为 exited(0)，可清理：`docker rm ainb-stone-v4`。

## 6. wood-worker 复核后的阈值修复（2026-11-14，freeze）

### 6.1 证据（wood-worker 只读分析 + 我们复算）

- v4 公开轨迹按 v5 代码语义重建：pickup 触发 **70** 次（与 agent.log 70 条 `log broken` 一致）。
- **65 次假破坏**：`wood_hits` 只有 8 或 10（49 次=10、16 次=8），换格后同一 wood 方块坐标重新出现；机制=跳起空中连打约 10 帧→落地准星滑到树叶→触发假捡取→16 步原地 walk→再跳，约 29 步一循环。
- **5 次真破坏**：`wood_hits` = 67/62/60/67/65（≈60 tick 手打木头时长）。
- 方向：70 次触发时“前进方向 vs →掉落点”夹角 median **15.1°**、max **15.2°**（最多差 1 个 15° 档）；真破坏中 4 次位移 0/0.8/1.55/1.61、min_hd 卡 1.80~1.81 → 需要 jump/侧移而不只是转向。结论：**主因是破块判定阈值**，方向修复仍保留作为辅助。
- 修复：pickup 触发条件 `wood_hits >= 8` → **`>= 55`**（真破坏最小 60、假破坏最大 10 的干净分界）；未达阈值不清 `wood_key/wood_hits`，连击可继续累积到真破坏。pickup 预算本轮仍固定 16 步（wood-worker 建议的按距离动态预算留待下一步，未擅自扩大）。

### 6.2 新增/更新回归（先红后绿）

`tests/test_pickup_direction.py`：

| 类别 | 用例 | 修复前 |
|---|---|---|
| 真破坏 5 组（R1-R5，hits 67/62/60/67/65，公开坐标/位置/yaw） | 必须 arm pickup，且首帧转向档位符合公开 yaw 公式 | arm 通过（guard） |
| 假破坏 3 组（F1-F3，hits 10/10/8） | **不得** arm、保留 `wood_key/wood_hits` 让连击继续 | **FAILED**（旧阈值 8 会 arm） |
| 回放 step1800-1811（1 jump + 10 帧 wood 同 key 后换 leaves） | 不得 arm | **FAILED** |
| seed43/42 方向、到达停止、阻塞 jump/sidestep | 保持 v5 定向/停滞语义 | 通过（改为 60+ hits 触发） |

证据：阈值修改前 `pickup_direction` → **FAILED (failures=4)**；修改后 → **Ran 7 tests … OK**；**全套 `python -m unittest discover -s tests` → Ran 80 tests，OK，exit 0**；`py_compile` exit 0；编辑文件全 CRLF（agent.py 1359 行，LF-only=0）；`git -c core.autocrlf=false diff --stat` 与 `git diff --ignore-space-at-eol` 一致（agent.py +129、总 264+/10−）。

当前 frozen 源码哈希：`agent/agent.py` sha256 `702e0adea6d776c31bb300e4d8381f17df8663ea75bf67f96a4056ddd266bad9`；`tests/test_pickup_direction.py` sha256 `0f05e4aa687f03b58bf18f83593c987b740d0f90e696feda99dc81caed92be8a`。

### 6.3 待办

- 等待负责人再次授权后用 `review/runs/stone-v5b-2026-11-14` + `ainb-stone-v5b` 跑唯一一次正式 v5；本轮**不再启动游戏**、不改源码。
- 若 v5b 仍受 pickup 距离预算限制（真破坏 R1/R4 距离 3.4~4.2），下一步再评估 wood-worker 建议的按距离动态 `pickup_steps`（`max(8,min(24,ceil(dist/0.28)+6))`）。
