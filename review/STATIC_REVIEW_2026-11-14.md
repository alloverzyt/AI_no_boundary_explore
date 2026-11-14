# 静态审查报告 · 2026-11-14

项目：AI_no_boundary_explore。基线 HEAD：`eb683aca616c21847f1e04dce96cfbb52e98f61d`。

共享 task-1 查询返回 not found，无法 claim/complete，按要求独立执行。审查者仅写本报告，未修改源代码、测试、工作流、模型配置或官方资料，未展示密钥。

## 结论与验证边界

确认 **P0：0；P1：5；P2：5**。P1 为正常科技树或常见恢复路径受阻，P2 为特定条件正确性、效率或验收可信度问题。未发现可确认的全局启动、安全或作弊规则 P0。

已审查 agent/ 全部 Python 模块、动作目录、配置结构、技术路线模板，tests/ 全部测试和当前工作流。已先读 [README](../README.md)、[BUG_REVIEW](../BUG_REVIEW.md)、[TECHNICAL_STATUS](../TECHNICAL_STATUS.md)、[比赛信息](../比赛资料库/02_比赛信息整理/AI无界杯_比赛信息.md)、[官方题面](../比赛资料库/02_比赛信息整理/官方资料存档/赛道B_无界探索_官方题面.md)、[计分规则](../比赛资料库/02_比赛信息整理/官方资料存档/下载/无界探索_智能体测评计分规则.txt)。只依据仓库官方存档，未联网替换规则。

执行 `python -B -m unittest discover -s tests -v`：Python 3.11.9，21 tests 全通过，视觉测试实际执行、无 skip，退出码 0。另以公开 observation 在内存调用策略验证下列路径，未运行真实游戏、访问环境内部数据或调用模型。离线测试通过、历史木制成功、石器成功、正式铁镐成功不能相互替代。

规则依据：题面 20、28、62–78 规定空包单世界推进铁镐、3600 秒/5M token；计分规则 40–42 规定历史里程碑不因材料消耗撤销，199–246 规定石器检查点同时需要石镐与熔炉，266–270 规定死亡掉物品，287–315 限制公开观测、规定动作和官方模型端口。

只读检查 [官方 ZIP](../比赛资料库/02_比赛信息整理/官方资料存档/下载/赛道B_智能体开发包.zip)：实际含 pack_agent.py、practice.py、practice-scenes.json；pack_agent.py 8–26 支持 --policy offline/--extra 并以脚本目录为根，当前 CI 解压后打包调用成立。其 pdf_runner.py 64–69 将环境 craft_smelt 掩码转为公开 craftable，另转发 nearby_tools/last_action 等。未修改或执行评测器。题面存档 174“不含打包工具”与当前 ZIP 有版本差异，不能据此误判 CI 打包失败。

## 历史修复复核

| 事项 | 当前证据 | 判定 |
| --- | --- | --- |
| 导航抢占制作 | [agent.py:740](../agent/agent.py#L740)、[arbitrate:666](../agent/agent.py#L666) | 已修，制作在先、仲裁默认 None，回归通过 |
| recovery 被 moving 阈值挡住 | [agent.py:513](../agent/agent.py#L513) | 已分别计时，静止输入测试通过；位移达阈值提前退出为显式设计，不重列旧 bug |
| 扫描立即重触发 | [agent.py:483](../agent/agent.py#L483) | 已清计数并设置移动窗口；不等于实现文档建议的 300 步远行 |
| walk 重复推进/递归 | [agent.py:156](../agent/agent.py#L156) | 已修，仅构造动作 |
| reset 跨局残留 | [agent.py:72](../agent/agent.py#L72) | 导航/台子/视觉等已清理并重建 planner |
| 有旧台不放便携台 | [agent.py:851](../agent/agent.py#L851) | 有备用台且离开旧台路径已修，缺台恢复见 P1-02 |
| evaluation 凭据/异常降级 | [planner.py:181](../agent/planner.py#L181)、[planner.py:136](../agent/planner.py#L136) | 客户端异常路径已修，语义失败见 P2-04 |
| 均匀水面报最左 | [vision.py:165](../agent/vision.py#L165) | 已改质心，回归通过 |
| 一矿就等/无效做铁镐 | [agent.py:885](../agent/agent.py#L885) | 数量和合法 recipe 判断已修，完整链未闭环 |
| 木制旧 explore 分支挖地 | [agent.py:302](../agent/agent.py#L302) | 此分支已加条件，导航仍可绕过，见 P2-01 |

## P0 清单

0 项。审查范围未发现直接读存档/隐藏 voxels、作弊改环境或额外网络服务；模型调用走现有 ModelClient。结论不覆盖外部镜像和全部历史资料安全性。

## P1 清单

### P1-01 缺熔炉放置/燃料链，矿石满额后永久空等

- **位置**：[agent.py:884](../agent/agent.py#L884)，887–904；846–849 仅制作熔炉，全文件无放炉或主动采煤/烧木炭流程。
- **触发**：熔炉在包、raw_iron+ingots≥3，iron_ingot 不在 craftable，例如无就近熔炉/合法冶炼条件。
- **影响**：904 无限 noop 至时限，铁锭/铁镐及铁器效率分不可达，历史承认的缺口仍真实存在。
- **复核**：木镐/石镐/熔炉各1、铁矿石3、craftable=[]，连续10次 act 完整 noop，未放炉/找燃料/调整位置。
- **建议**：补熔炉准备、合法燃料、放置确认、冶炼及失败恢复状态，依据公开 recipe/动作反馈/背包确认。
- **验收**：该状态有限步内合法准备，条件满足后炼3锭做铁镐；无燃料/放置失败不永久空等；最终官方 Docker 全链验证。

### P1-02 后期不补木棍，缺失工作台依赖恢复不完整

- **位置**：[agent.py:825](../agent/agent.py#L825)、[agent.py:846](../agent/agent.py#L846)、[agent.py:866](../agent/agent.py#L866)、[agent.py:906](../agent/agent.py#L906)。木板/木棍仅809–812制作，受 wpick==0 限制。
- **触发**：stick 一次产4，木镐用2、石镐用2，铁镐还需2；或远离旧台且备用台耗尽。即使原木与合法 planks/stick 在包也不补料。
- **影响**：铁锭够缺棍则909永久noop；圆石够缺棍/台则868–872只走转。table_placed=True 令866禁止再做台，不代表台可用。
- **复核**：木镐/石镐/熔炉、铁锭3、原木2、台在包、craftable=['planks','stick']，10次空等。木镐、圆石3、原木2、table_placed=True、无备用台、craftable=['planks']，20次操作码仅0。
- **建议**：统一恢复各配方依赖，缺棍补棍、缺板补板、无可用台则做/放/返回旧台，不以历史布尔值代替可用性。
- **验收**：stick 4→2→0 后可补料；3铁锭无棍能恢复；台耗尽且远离旧台能从原木重建；配方可用即优先制作。

### P1-03 放置未确认，木制等待阻断补料

- **位置**：[agent.py:762](../agent/agent.py#L762)、[agent.py:775](../agent/agent.py#L775)、[agent.py:783](../agent/agent.py#L783)，补料在809之后。
- **触发**：place失败仍设 table_placed=True；或放台时缺料；或死亡掉包但实例未reset。
- **影响**：缺料误当台未识别，至少60调用才清标志再换位，可能重复丢台/采集，损害木制恢复。
- **复核**：table_placed=True、log=1、planks=1、craftable=['planks']，60次act无制作。现有测试仅检查发送place，不确认成功。
- **建议**：区分pending/confirmed，以last_action、背包和recipe确认；缺料先补，仅缺工具条件时靠近/重放，重试有界。
- **验收**：place被拒、成功但缺料、放台后死亡三个序列，有限步内恢复，不跳过可执行制作而漫步60步。

### P1-04 竖井遇基岩/液体无退出，超时仅原地转向

- **位置**：[agent.py:697](../agent/agent.py#L697)，710–721攻击任何非空块，超200次只改yaw。
- **触发**：持续dig_down遇基岩/水/熔岩或长期无进展。
- **影响**：pitch=90时改yaw不变脚下目标，重置后继续打到时限；液体不可挖且有伤害风险，walk_policy水保护不经此路。
- **复核**：木镐已装备、pitch=90、脚下bedrock、无圆石，405次act为403攻击、2转向、0移动。
- **建议**：不可破坏/液体即退出；按坐标、背包、位置判无进展，有界重试后换路线/逃生并调pitch。
- **验收**：基岩、水、熔岩、固定坐标分别回归，上限后改变位置/目标，官方环境验逃生安全。

### P1-05 丢木镐后阶段回退，忽略高级工具

- **位置**：[agent.py:752](../agent/agent.py#L752)，与843、874–899组合。
- **触发**：已有石镐/熔炉，木镐损坏、丢弃或死亡后仅拾回高级工具。
- **影响**：强制重做木制，不能用石镐采铁；官方历史里程碑不会因旧工具丢失撤销。
- **复核**：石镐/熔炉在包、无木镐、铁矿石可达，act返回找木移动而非装备石镐/采铁。
- **建议**：按最高可用工具、当前配方和进度选阶段，仅补当前最小依赖。
- **验收**：有石镐无木镐可采铁，有铁镐满足结束/待命；损坏/死亡部分拾回不无条件重走木制。

## P2 清单

### P2-01 木制禁挖地仍有导航绕过

- **位置**：[agent.py:402](../agent/agent.py#L402)→[walk_policy:679](../agent/agent.py#L679)→[nav_step:513](../agent/agent.py#L513)，535–536攻击；[test_agent.py:114](../tests/test_agent.py#L114)仅查首步。
- **触发/影响**：木制顶土坎8次jump无位移进入digging，导航不知阶段，302的explore条件未覆盖，仍持续挖无关地面。
- **复核**：空包、近处dirt、固定位置，按输出更新pitch，35次act有11次攻击，最终digging。
- **建议**：导航显式接收阶段/清障权限，统一木制行为并保留有界绕行。
- **验收**：moving→jumping→digging长序列，覆盖STABLE两种配置，按预期不持续挖无关地面且能脱困。

### P2-02 CI 无结果/episode 仍成功

- **位置**：[minedojo-practice.yml:71](../.github/workflows/minedojo-practice.yml#L71)、74–83；92缺artifact仅warn。
- **触发/影响**：实践命令退出0但无匹配result或episodes缺失/空，循环体不运行，无完成证明也绿灯。此为校验器缺陷，不声称正常runner一定产空结果。
- **建议**：断言结果存在、episodes非空列表、场景/局数正确，再逐局验终止与task_success。
- **验收**：零结果、空列表、缺字段、失败局、成功局、混合局，仅完整成功通过。

### P2-03 单元回归未接 CI

- **位置**：[minedojo-practice.yml:6](../.github/workflows/minedojo-practice.yml#L6)、19–84；[test_vision.py:17](../tests/test_vision.py#L17)。
- **触发/影响**：tests改动或reset/fallback/视觉回归，CI监听tests却只跑seed42离线木制，不执行unittest；21回归不能阻止合并，无Pillow还可跳视觉。
- **建议**：加轻量unit job，声明Python/Pillow并discover，与游戏结果分别呈现，不改生产模型配置。
- **验收**：破坏一个断言CI必须失败；恢复后21项及新用例实际执行并明确skip。

### P2-04 坏模型文本不计失败，永不三次降级

- **位置**：[planner.py:133](../agent/planner.py#L133)，135解析前清errors，144–145失败直接None。
- **触发/影响**：调用成功但持续非JSON/非法枚举/缺字段，不抛异常，一直耗用量无决策，三次降级只覆盖调用异常。
- **复核**：五次返回'not a decision'，calls=5、errors=0、dead=False、decision=None。
- **建议**：有效决策才清零，parse/repair失败累加并降级；保留模型/端点/凭据来源/预算。
- **验收**：三次坏文本/枚举降级；坏后有效清零；可修复文本与ModelResponseError分别验证。

### P2-05 同名工具装备状态被后续行覆盖

- **位置**：[agent.py:133](../agent/agent.py#L133)，138首槽，139无条件覆盖equipped。
- **触发/影响**：同名多槽先equipped=True后False，重做/拾回可能出现；已装备却重复equip，首槽与状态也可不符，浪费步骤打断连挖。
- **复核**：两行stone_pickaxe先True后False，inv()返回False。
- **建议**：逻辑或汇总，优先实际装备槽，不依赖行顺序。
- **验收**：两种顺序、仅一把装备、全未装备；已装备不重复equip，待装备选正确槽。

## 文档及待实测项（不重复计数）

- [README:19](../README.md#L19)、109仍说预留源码；[TECHNICAL_STATUS:126](../TECHNICAL_STATUS.md#L126)根目录命令不能直接执行，但解压后脚本存在，应补准备步骤和版本说明。
- [TECHNICAL_STATUS:115](../TECHNICAL_STATUS.md#L115)、[TECHNICAL_STATUS:175](../TECHNICAL_STATUS.md#L175)的127跳只进1dig与166–167的127/124矛盾，不能当当前复现。
- [BUG_REVIEW:29](../BUG_REVIEW.md#L29)历史1170步木制成功需关联artifact/hash/种子/镜像/配置；本轮未复跑，未声称石器或铁器通关。
- [technical-route.md:1](../agent/technical-route.md#L1)仍为模板；资料分发隐私/版权是既有事项，本轮未复制个人记录。
- _near_table 445–449只算水平距离、不验台存在，需上下层/失败放置实测；树冠阈值与群系准确率需合法截图集，不把猜测列确认缺陷。
- goal/idle执行语义有限需明确，本轮只计已复现的解析降级问题。

## 建议交接

先修CI空结果与unit门禁，再修依赖/台子反馈及熔炉链，随后修工具阶段、竖井逃生和木制长序列回归。最终官方Linux/Docker从空包多种子验证木制、石器、铁器，保留成功/失败artifact；单元通过不代替通关。

持久写入仅本报告，内存复核用python -B，未新增脚本/pycache。task-1不可见，未伪造完成状态。模型配置未改。

交付核对时发现其他并行工作已修改工作流、README、TECHNICAL_STATUS、agent.py、test_agent.py，并新增 scripts/ 与 test_practice_validation.py。本报告的精确行号、21项测试结果及缺陷复核对应上述 HEAD 基线和本次首次读取的版本；不构成对并行修复后版本的验收。主负责人应将对应修复 diff 和新增测试与本清单逐项对照，再标记关闭，尤其关注 CI 校验、工具阶段及竖井恢复。本审查者没有回滚或覆盖这些并行变更。

REVIEW_COMPLETE
