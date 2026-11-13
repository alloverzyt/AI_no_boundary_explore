"""ReAct 式规划层：把"往哪走 / 干什么"交给模型，规则层只负责执行。

架构定位（与 Voyager / ReAct 的对应关系）：

    观测 ──► Planner（模型，低频）──► 子目标/航向 ──► Executor（规则，高频）
       ▲                                                  │
       └──────────────── 环境反馈（背包/位置/准星）────────┘

  * Planner 每 PLAN_INTERVAL 个环境步调用一次，输出一个短 JSON 决策；
  * Executor 沿用已验证的原子技能（连击挖方块、放置、按 craftable 合成）；
  * 模型不可用（无密钥/超时/报错）时自动降级为启发式规划器，绝不让程序崩。

赛规约束：
  * 只通过官方 `model_api.ModelClient` 调用，不自行发请求；
  * 官方网关不自动重试，本模块捕获异常后交给规则层，绝不静默重试；
  * Token 消耗做下限控制：短提示（约 300 token）+ 短输出（≤120 token）。
"""
import json
import os
import re

# --------------------------------------------------------------------------
# 提示词：要求模型只做"高层决策"，不生成动作序列
# --------------------------------------------------------------------------
SYSTEM_HINT = "你是 Minecraft 生存智能体的规划器。只输出一行 JSON，不要解释。"

PROMPT_TMPL = """目标：从空背包做出{goal_desc}。
当前：步数={step} 生命={health} 位置=({x:.0f},{y:.0f},{z:.0f})
背包：{inv}
准星：{crosshair}
最近：{recent}

请判断下一步该做什么，从下列枚举中选择：
- goal: "find_tree"（找树砍原木） | "get_stone"（找石头/下挖） | "craft"（材料够了，合成） | "escape"（被卡住，脱困）
- turn:  "left" | "right" | "none"（是否先转向）
- verb:  "walk"（前进） | "mine"（对准的方块连击） | "idle"（原地等待）

只输出 JSON，形如 {{"goal":"find_tree","turn":"left","verb":"walk"}}"""


def _short_inv(obs, limit=6):
    inv = obs.get("inventory") or []
    if not inv:
        return "空"
    items = ["%s×%d" % (r["item_id"], r["quantity"]) for r in inv[:limit]]
    return "、".join(items)


def _crosshair(obs):
    hit = obs.get("crosshair_hit") or {}
    name = hit.get("block_name") or "none"
    dist = hit.get("block_distance")
    if dist is None:
        return "无目标"
    return "%s@%.1f格" % (name, float(dist))


def build_prompt(obs, ctx):
    pos = obs.get("position") or [0, 0, 0]
    return PROMPT_TMPL.format(
        goal_desc=ctx.get("goal_desc", "木镐"),
        step=obs.get("step", 0),
        health=obs.get("health", 20),
        x=float(pos[0]), y=float(pos[1]), z=float(pos[2]),
        inv=_short_inv(obs),
        crosshair=_crosshair(obs),
        recent=ctx.get("recent", "无"),
    )


_JSON_RE = re.compile(r"\{[^{}]*\}", re.S)


def parse_decision(text):
    """从模型回复里抠出第一个 JSON 对象；失败返回 None。"""
    if not text:
        return None
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except Exception:
        return None
    if d.get("goal") not in ("find_tree", "get_stone", "craft", "escape"):
        return None
    if d.get("turn") not in ("left", "right", "none"):
        return None
    if d.get("verb") not in ("walk", "mine", "idle"):
        return None
    return d


def repair_decision(text):
    """兜底：输出被截断（如 '{"goal":"craft' ）时，按已出现的字段尽力还原。"""
    if not text:
        return None
    d = {}
    for key, allowed in (("goal", ("find_tree", "get_stone", "craft", "escape")),
                         ("turn", ("left", "right", "none")),
                         ("verb", ("walk", "mine", "idle"))):
        m = re.search(r'"%s"\s*:\s*"([a-z_]+)"' % key, text)
        if m and m.group(1) in allowed:
            d[key] = m.group(1)
    if "goal" not in d:
        return None
    # 缺失字段给保守默认值
    d.setdefault("turn", "none")
    d.setdefault("verb", "walk" if d["goal"] in ("find_tree", "get_stone") else "idle")
    return d


# --------------------------------------------------------------------------
# 规划器 A：真模型（官方 model_api.ModelClient）
# --------------------------------------------------------------------------
class ModelPlanner:
    def __init__(self, config, max_output_tokens=512, timeout=45):
        from model_api import ModelClient   # 官方 SDK，遵守计量与鉴权
        self.client = ModelClient(
            config=config,
            max_output_tokens=max_output_tokens,
            timeout=timeout,
        )
        self.calls = 0
        self.errors = 0
        self.dead = False          # 连续失败过多 -> 永久降级为规则层
        self.fallback = HeuristicPlanner()

    def decide(self, obs, ctx):
        if self.dead:
            return self.fallback.decide(obs, ctx)
        try:
            reply = self.client.chat(SYSTEM_HINT + "\n\n" + build_prompt(obs, ctx))
            self.calls += 1
            self.errors = 0        # 成功一次就清零
        except Exception:
            # 官方网关不自动重试；三次失败后 use the local planner rather
            # than returning an empty decision on every subsequent interval.
            self.errors += 1
            if self.errors >= 3:
                self.dead = True
                return self.fallback.decide(obs, ctx)
            return None
        dec = parse_decision(reply)
        return dec if dec else repair_decision(reply)


# --------------------------------------------------------------------------
# 规划器 B：启发式（无密钥时的降级方案，也用于本地无网测试）
# --------------------------------------------------------------------------
class HeuristicPlanner:
    """不调用任何模型：用观测统计给出同样格式的决策，便于验证架构。"""

    name = "heuristic"

    def __init__(self):
        self.calls = 0
        self.errors = 0
        self._turn_dir = 1

    def decide(self, obs, ctx):
        self.calls += 1
        hit = obs.get("crosshair_hit") or {}
        name = (hit.get("block_name") or "")
        dist = hit.get("block_distance")

        # 准星里已经有木头/石头 -> 直接挖
        if dist is not None and float(dist) <= 4.0:
            if "wood" in name or "log" in name:
                return {"goal": "find_tree", "turn": "none", "verb": "mine"}
            if "stone" in name:
                return {"goal": "get_stone", "turn": "none", "verb": "mine"}

        # 否则按固定节奏扫描：交替左右，避免一直朝一个方向
        self._turn_dir = -self._turn_dir
        return {"goal": "find_tree", "turn": "left" if self._turn_dir > 0 else "right",
                "verb": "walk"}


# --------------------------------------------------------------------------
def make_planner(config):
    """Use the model only when a name and a usable credential source exist."""
    model = (config or {}).get("model") or {}
    if not isinstance(model, dict):
        return HeuristicPlanner()

    evaluation_url = os.environ.get("EVALUATION_API_URL")
    evaluation_token = os.environ.get("EVALUATION_API_TOKEN")
    if evaluation_url or evaluation_token:
        has_credentials = bool(evaluation_url and evaluation_token)
    else:
        has_credentials = bool(model.get("api_key") or os.environ.get("UESTC_MODEL_API_KEY"))

    has_target = bool(str(model.get("name") or "").strip()) and has_credentials
    if has_target:
        try:
            return ModelPlanner(config)
        except Exception:
            return HeuristicPlanner()
    return HeuristicPlanner()
