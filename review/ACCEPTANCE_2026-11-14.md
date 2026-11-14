# 首轮审查与修复验收 · 2026-11-14

## 结论

用户选择的目标为“全面质量审查与修复”。本轮已完成项目审查、环境/测试基线、首批有证据的修复与验证。负责人只组织、复核、修改说明文档和验收；策略/CI代码由执行成员修改，独立静态审查成员只交付审查报告。

基线审查：**P0 0项、P1 5项、P2 5项**。本轮关闭3项P2，**仍有5项P1、2项P2待修复**。本轮完成不代表项目所有缺陷已关闭，更不代表正式铁镐任务已达成。

## 首批交付

| 项目 | 实现与证据 | 验收 |
| --- | --- | --- |
| P2-02 CI空结果误报 | 新增 [验证器](../scripts/validate_practice.py)，拒绝无结果/空episodes/失败或不完整结果；[17项结果验证测试](../tests/test_practice_validation.py)覆盖失败与成功 | 通过；真实运行产物也通过校验 |
| P2-03 回归未接CI | [工作流](../.github/workflows/minedojo-practice.yml)新增Python 3.11/Pillow离线测试job，woodcraft依赖它 | 本地测试/静态检查通过；未触发远程Actions |
| P2-05 重复工具覆盖装备状态 | [Agent.inv](../agent/agent.py#L133)同名装备状态按任一已装备汇总，优先使用已装备槽，数量保持相加；[回归测试](../tests/test_agent.py#L169) | 旧实现新增用例3/5失败，修复后全绿；最终diff仅修改inv聚合逻辑 |
| 文档纠正 | [README](../README.md)反映实际代码目录；[技术现状](../TECHNICAL_STATUS.md)区分历史实验与当前证据，补充解压官方包和额外模块的打包步骤 | 通过文档差异复核 |

执行记录：[CI修复](CI_FIX_2026-11-14.md)、[装备聚合修复](INVENTORY_FIX_2026-11-14.md)。

## 负责人独立验证

在执行成员停止修改源码/测试后运行：

```text
python -m unittest discover -s tests -v
# 43 tests，0失败、0跳过；0.791s；exit 0
python -m py_compile agent/agent.py agent/planner.py agent/model_api.py agent/vision.py agent/minecraft_actions.py scripts/validate_practice.py
# exit 0
python scripts/validate_practice.py --output review/runs/woodcraft-2026-11-14
# PRACTICE_VALIDATION_OK results=1 episodes=1；exit 0
git diff --check
# exit 0
```

已审阅最终Agent/test差异、新增验证器及测试、工作流及文档差异。初始工作树干净，HEAD为 `eb683ac`；所有更改目前仍是本地未提交状态，未推送。

## 当前木制实跑证据

- 官方缓存Linux/amd64镜像；从包含本次inv修复的源码重新打包；离线模式、容器network none、0模型调用。
- woodcraft tutorial，seed 42，1500步预算；**1198步完成5/5目标，0死亡、0非法动作**；执行耗时87.4秒。
- 负责人直接读取了 [result.json](runs/woodcraft-2026-11-14/world-zhybgjcf/result.json) 和 [manifest.json](runs/woodcraft-2026-11-14/world-zhybgjcf/manifest.json)，并独立运行新验证器通过。
- 包SHA256：`957880b18baf85705244ebc2c9dec89a4467d574554eb2dcb4e87e0bc453e916`。包内策略哈希与当前源码匹配的证据见 [实跑报告](GAMEPLAY_2026-11-14.md)。
- 限制：宿主日志转发器发生GBK解码错误，后台作业exit 1，未捕获docker CLI退出码；容器仍完成并留下完整官方结果/轨迹。成功结论依据官方结果、轨迹及包哈希，不能声称docker命令退出0。未重跑。
- 本结果仅证明一次木制教学局成功；石器、铁器、隐藏种子和实际模型API端到端尚未验证。
- 原始运行产物被已有runs/忽略规则排除，仅本地保留；报告可跟踪。没有推送或提交比赛。

## 下一阶段具体目标（按建议执行顺序）

| 顺序 | 未关闭项 | 目标与验收 |
| --- | --- | --- |
| 1 | P1-02 后期依赖不恢复 | 缺棍补棍、缺板补板、远离旧台无备用台能重建；材料足且recipe可用即制作；覆盖木棍4→2→0及3铁锭无木棍输入 |
| 2 | P1-03 放置未确认 | 区分放置pending/confirmed；依据公开动作反馈/背包/合法recipe确认；失败与缺料有限步恢复，不漫步60步跳过可制作动作 |
| 3 | P1-05 强制回退木制 | 有石镐无木镐仍能采铁；按最高可用工具选阶段，旧工具损坏不强制重走木制 |
| 4 | P1-04 竖井无退出 | 基岩、水、熔岩和持续无进展输入有界退出，改变路线与目标；保留采矿连续动作 |
| 5 | P1-01 熔炉燃料冶炼链 | 合法获取燃料、放炉、确认条件、炼3铁锭并制作铁镐；缺条件不永久noop；需官方环境完整链实跑 |
| 6 | P2-01 木制导航绕过禁挖地 | 对moving→jumping→digging长序列加入阶段权限与有界绕行回归 |
| 7 | P2-04 无效模型文本不降级 | 有效决策才清失败计数，连续3次不可解析回复转启发式，坏后有效回复正确清零 |

先闭合依赖与放置恢复，再进行石镐+熔炉检查点实跑；此后推进铁镐全链。P1完整触发证据和建议见 [独立静态审查](STATIC_REVIEW_2026-11-14.md)。该报告针对初始基线，三项P2在并行交付后关闭的状态以本验收报告为准。

## 小队协作与证据边界

静态审查固定模型在子代理入口被拒绝，随后通过保留原模型/权限的小队成员启动接口成功运行；未替换其配置。该独立会话无法读取根会话task-1，因此审查者在报告注明此事并交付REVIEW_COMPLETE，负责人读取后回填任务验收。执行成员由固定模型子代理承担，任务2/3/6/5按依赖顺序完成，写入范围分开。

参考：[质量目标](QUALITY_PLAN_2026-11-14.md)、[环境和21项测试基线](BASELINE_2026-11-14.md)、[独立静态审查](STATIC_REVIEW_2026-11-14.md)、[实跑报告](GAMEPLAY_2026-11-14.md)。
