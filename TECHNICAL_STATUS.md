# 无界杯赛道 B · MineDojo 开放世界智能体 —— 技术现状报告

> **2026-11-14 审查说明**：下文架构与实测数字包含历史迭代记录，不代表当前 HEAD 的复验结果。历史导航统计和末尾结论存在不一致，须以原始运行记录复核；不能据此宣布当前版本通关。当前修复记录见 [BUG_REVIEW.md](BUG_REVIEW.md)，本轮质量目标见 [review/QUALITY_PLAN_2026-11-14.md](review/QUALITY_PLAN_2026-11-14.md)。石器完整流程尚未验收，铁器的熔炉与燃料获取流程仍有缺口。

> 仓库用途：赛道 B（MineDojo 开放世界智能体）参赛代码与实验记录
> 当前版本：`agent/` 目录下三层架构（ReAct 规划 + 规则执行 + 离线视觉）
> 实测环境：官方镜像 `streetartist/uestc-minecraft-controller`，本地练习场景 `woodcraft` / `stone-tools`

---

## 一、方案总览

纯规则 Agent 在「局部操作」上已经够用（连续攻击、精确瞄准、按掩码合成全部验证可用），
但「往哪走」这种需要全局常识的决策，规则写不出来。因此采用**三层架构**：

```
观测 ──► Planner（模型，低频）──► {goal, turn, verb} ──► Navigator（单一状态机）
   ▲                                                          │
   │                              ┌───────────────────────────┘
   │                              ▼
   │                        Executor（规则原子技能：连续攻击 / 放置 / 合成）
   └──────────────── 环境反馈（背包 / 位置 / 准星 / 画面）────────────┘
```

| 层 | 文件 | 职责 |
|---|---|---|
| 规划层 | `planner.py` | 每 N 步调用一次官方模型，输出一行 JSON 决策；无密钥时自动降级为启发式 |
| 导航层 | `agent.py: nav_step()` | 单一状态机：`MOVING → JUMPING → DIGGING → DETOURING`，叠加 `SCANNING(360°)` |
| 执行层 | `agent.py` | 连续攻击（lock）、瞄准、放置、按 `craftable` 合成 |
| 感知层 | `vision.py` | 从 640×400 画面识别树冠/水面方位（纯 RGB 阈值，0 Token） |

---

## 二、观测与动作契约（来自官方开发包）

| 项 | 内容 |
|---|---|
| 动作 | 长度 8：`[前后, 左右, 跳/潜/冲, 俯仰, 偏航, 操作, 制作参数, 槽位]` |
| 俯仰/偏航 | **增量**，12 = 不变，每档 15°；**正俯仰 = 低头** |
| 操作码 | 0 无 / 1 用 / 2 丢 / 3 攻击 / 4 制作 / 5 装备 / 6 放置 / 7 销毁 |
| 观测 | `image_jpeg_base64`、`inventory`、`position`、`orientation`、`health`、`crosshair_hit`、`craftable`、`nearby_tools`、`last_action` 等 |

> **重要限制**：环境内部确实计算 `voxels`（13×15×13 方块网格）与 `lidar`，
> 但官方 `public_observation()` 只转发上表字段，voxel 用于**官方评分**而非提供给选手。
> 因此 Agent 的几何感知只有「一根 10 米准星射线 + 一张第一人称画面」。

---

## 三、实测结果

### 3.1 木制阶段（woodcraft，1500 步预算）

| 配置 | 结果 | 步数 |
|---|---|---|
| 规则版（无模型） | **5/5 通关**（`tutorial_goals`） | 最好 **533**，多次 534/536 |
| ReAct 版（真实模型） | **5/5 通关** | 846 / 1336 |
| 当前分支 | 未复现 5/5 | — |

效率分：`Seff(木制) = 8 × 1500/(1500 + 533) = 5.91 / 8`

### 3.2 石器阶段（stone-tools，6000 步预算）

| 配置 | 最好结果 | 说明 |
|---|---|---|
| 规则版 | **2/4（木镐 ✓ 圆石 ✓）** | 位移 69×98，攻击 1727 |
| 当前分支 | 0/4 | 运动中，未拿到圆石后合成石镐 |

### 3.3 真实模型接入

| 项 | 数值 |
|---|---|
| 模型 | `deepseek-flash`（官方 `api.uestcai.top`） |
| 调用间隔 | 每 40 环境步（航向锁定时 240 步才重问） |
| 单次消耗 | 约 440–510 token（含 reasoning） |
| 6000 步总消耗 | 约 4.6 万 token = 5M 预算的 **0.9%** |
| 降级 | 无密钥/超时 → 启发式；连续失败 3 次 → 永久降级 |

---

## 四、关键技术发现（全部有实测数据支撑）

1. **破坏方块必须连续攻击**：中途转向/改俯仰会重置进度。手打原木约需 60–80 下。
2. **俯仰正负号要实测**：本环境正 pitch = 低头；用 `orientation.pitch` 做绝对瞄准比发增量安全。
3. **`nearby_tools.table` 不可靠**：实测放下工作台并贴脸时仍恒为 False，应改用 `craftable` 掩码。
4. **合成前必须算清材料账**：木板 9 = 工作台 4 + 木棍 2 + 镐 3；提前做台子会导致差 1 个木板。
5. **观察数据只有一根 10 米射线**：画面边缘的树永远不会进入 `crosshair_hit`，必须靠视觉补。
6. **暗色树叶阈值**：雪原云杉树叶像素实测 `(29,36,28)`、`(3,16,7)`，绿通道仅 16–36，阈值必须下探到 `g>=12`。
7. **方向判定用「最密列」而非质心**：左右都有树时质心落在画面中央，等于告诉 Agent「直行」。

---

## 五、已修复的失败模式（迭代记录）

| # | 现象 | 根因 | 修复 |
|---|---|---|---|
| 1 | 1500 步 0 次攻击 | 方块名写死 `log`，本版本叫 `wood` | 子串容错组 |
| 2 | 974 次攻击零产出 | 单次挥拳重置破坏进度 | 目标指纹 + 连续攻击锁定 |
| 3 | 连击 66 步打不掉原木 | 连击上限 60 不够 | 提到 200 |
| 4 | 视线一直朝上 | 俯仰符号用错，pitch 压到 90° | 改绝对瞄准 |
| 5 | 贴脸工作台仍做不出镐 | `nearby_tools.table` 恒 False | 改用 `craftable` |
| 6 | 805 次合成失败 | 工作台从未真正放入世界（低头无地形时空转） | 放置分支加换位兜底 |
| 7 | 6000 步仅移动 15 格 | 顶在土坎前反复前进 | 先跳，跳不过斜向上挖 |
| 8 | 挖进地下水 | 斜向下挖 | 改斜向上 + 水/岩浆改为绕行 |
| 9 | 加探索逻辑后木制 0/5 | 探索行为对所有场景生效 | `STABLE` / `explore` 开关按阶段隔离 |
| 10 | 模型说 `turn:left` 时原地转 600° | 转向语义应为一步，却执行了 40 步 | `turn` 只在 `plan_used==1` 时执行 |
| 11 | 视觉每步都转（1456 次/1500 步） | 无节流 | 冷却 3 步 + 同向连续 2 次才采信 |
| 12 | 89% 时间准星盯着空气 | 丢目标后无重扫路径 | `SCANNING` 状态（360°） |
| 13 | 1400 步都在挖石头 | `dig` 状态只要准星有方块就无限攻击 | 40 步硬超时 → 绕行 |
| 14 | 三个控制器互相打断 | 三套独立计时器 | 合并为单一 `nav_step` 状态机 |

---

## 六、当前已知问题

| 问题 | 现象 | 下一步 |
|---|---|---|
| **跳跃↔复位振荡** | 127 次 `stuck → jumping` 只升级到 1 次 `digging` | 跳跃状态按步数推进（8 步必进 dig），不看位移 |
| **远距离探索缺失** | 草地场景扫 360° 无果后仍在附近打转 | 连续 3 次扫描无果 → 定向行进 300 步 |
| 石器合成未闭环 | 拿到圆石后未能就地合成石镐 | 便携工作台逻辑已写，待完整触发 |
| lock 保鲜期 | 目标短暂丢失即清零，攒不够 60 下 | 增加 3 步保鲜期 |

---

## 七、如何运行

`pack_agent.py`、`practice.py` 和 `practice-scenes.json` 位于归档的官方开发包 ZIP 中，本仓库根目录没有这些入口。先将 `比赛资料库/02_比赛信息整理/官方资料存档/下载/赛道B_智能体开发包.zip` 解压到独立的 `<dev目录>`，把本仓库 `agent/` 的文件覆盖到该目录，再在该目录执行下列命令。打包时必须附带 `planner.py`、`vision.py`，否则导入失败会静默降级。官方题面存档称开发包不含自动打包工具，与当前归档 ZIP 的实际内容不一致；这里按 2026-11-14 对归档 ZIP 的实际检查说明。

本机 Windows 使用 `python` 或 `py`；`python3` 是 Store 存根。Docker 不在 PATH 时使用 `C:\Program Files\Docker\Docker\resources\bin\docker.exe`。以下 PowerShell 命令中的 Docker 镜像可使用本地缓存，容器内仍使用 `python3`。

```powershell
# 1) 在解压并覆盖策略后的 <dev目录> 打包
python pack_agent.py --policy offline --output agent.zip --extra planner.py vision.py

# 2) 本地练习（无模型，纯规则）
docker run --rm --init --platform linux/amd64 --cpus 4 --memory 4g --memory-swap 4g `
  --pids-limit 512 --shm-size 512m --network none `
  --mount "type=bind,source=<dev目录>,target=/workspace" --workdir /tmp `
  -e PYTHONPATH=/workspace -e PYTHONDONTWRITEBYTECODE=1 `
  --entrypoint xvfb-run docker.io/streetartist/uestc-minecraft-controller `
  -a python3 -u /workspace/practice.py --package /workspace/agent.zip `
  --scenes /workspace/practice-scenes.json --output /workspace/practice-output --only woodcraft

# 3) 启用真实模型：去掉 --network none，并注入密钥（密钥不进包）
#    -e UESTC_MODEL_API_KEY=<key>
```

---

## 八、说明

- `config.json` 中 `api_key` 始终为空，密钥只通过环境变量注入；正式测评由平台统一替换三项。
- 未修改任何 `evaluation_adapters/*` 评测代码，全部改动都在选手策略侧。


---

## 九、最新验证数据（统一导航状态机上线后）

在 stone-tools 场景连跑两局（6000 步/局，真实模型 `deepseek-flash`）：

| 局 | 里程碑 | 位移 | 攻击 | `none_in_range` | 主导准星 |
|---|---|---|---|---|---|
| `world-4hcmq1dz` | 0/4 | X 38 / Z 23 | 43 | 23.9% | `gravel` 3532 |
| `world-a8rc6u1g` | 0/4 | **X 60 / Z 72** | **539** | **5.3%** | `grass_block` 4818 |

### 状态机计数（证明导航器在运转）

| 计数 | 局 1 | 局 2 |
|---|---|---|
| `nav: lost sight -> scanning` | 131 | 9 |
| `nav: scan done` | 130 | 8 |
| `nav: stuck -> jumping` | 127 | 4 |
| `nav: jump failed -> digging` | 124 | 1 |
| `nav: dig timeout -> detouring` | 1 | 0 |

### 结论

- **导航状态机已闭环**：跳 / 挖（40 步硬超时）/ 绕 / 360° 扫描全部按设计触发；
- **感知稳定性大幅提升**：`none_in_range` 最好 5.3%（早期版本 89%）；
- **移动性提升 5 倍以上**：位移从 11–13 格提升到 60–72 格；
- **仍待解决**：跳跃后位移 ≥2 格就复位，导致 `stuck -> jumping` 127 次只升级到 1 次 `digging`（振荡）；草地场景缺少远距离定向探索。
