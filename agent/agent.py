"""规则版基线 Agent v7 —— 不调用模型、不耗 Token 的确定性状态机。

v7 相对 v6 的两处结构性修正（来自 stone-tools 的失败轨迹 world-hjh6fiw1）：

  1. **边采集边制作（优先级阶梯）**
     v6 是串行状态机：先攒够 3 个原木才进入制作阶段。但 1500 步预算里
     只够砍到 1 个原木，于是制作阶段永远进不去（制作次数 = 0）。
     v7 改成：只要背包里有 1 个原木就先做木板，有任何可做的立刻做，
     做不了才回去采集。

  2. **打木头时抬头够上层**
     v6 日志里出现 8 次 `attack burst on wood (d=1.9)`——最下面那格原木被
     打掉后，树干变成悬空的上层原木，平视的准星够不到。v7 每 4 次攻击
     抬眼一次（+30 度），沿树干向上吃。

动作编码（8 维）：
    [0] 前后 0/1/2   [1] 左右 0/1/2   [2] 跳/潜/冲 0..3
    [3] 俯仰 0..24（12=不变，每档 15 度）
    [4] 偏航 0..24（12=不变）
    [5] 操作 0无/1用/2丢/3攻击/4制作/5装备/6放置/7销毁
    [6] 制作/冶炼物品编号（action_items.json）
    [7] 背包槽位 0..35
"""
from minecraft_actions import craft_action, slot_action

try:                      # 离线视觉模块（可缺失，缺失则退化为纯规则）
    import vision
except Exception:
    vision = None

try:                      # ReAct 规划层（无密钥时自动降级为启发式）
    import planner
except Exception:
    planner = None

PLAN_INTERVAL = 40        # 每 40 个环境步问一次规划器
HEADING_TTL = 240         # 航向上锁后至少直行这么多步才允许重新问方向
NAV_STILL_LIMIT = 12      # 连续「每步零位移」多少帧算被挡住
LOG_PICKUP_STEPS = 16     # 原木打掉后走向掉落物捡起的步数（PR6 掉落实测 2~4 格）

# ---------------------------------------------------------------- 模式开关
# STABLE=True 时关闭所有"实验性"行为，回到已验证 533 步 5/5 的配置：
#   * 不调用模型规划层
#   * 不做贴脸障碍挖穿 / 水绕行
#   * 视觉不做"看得远才采信"的闸门
# 这样保证提交版稳定；实验特性由 STABLE=False 打开。
STABLE = False


# ---------------------------------------------------------------- 常量区
LOG_BLOCKS = ("wood", "log", "oak_log", "birch_log", "spruce_log", "jungle_log", "acacia_log")
STONE_BLOCKS = ("stone", "cobblestone", "andesite", "granite", "diorite")
IRON_BLOCKS = ("iron_ore",)
OBSTACLES = ("leaves", "plant", "vine", "grass_fern")
UNBREAKABLE_BLOCKS = ("bedrock", "barrier", "command_block", "end_portal_frame")
LIQUID_BLOCKS = ("water", "flowing_water", "lava", "flowing_lava")
DIG_STALL_LIMIT = 120     # 连续有效攻击但无公开进展 -> 有界退出竖井（原木约需 60~80 下）

REACH = 4.0
STUCK_WINDOW = 8
STUCK_EPS = 0.6


def _is_any(name, group):
    name = (name or "").lower()
    return any(g in name for g in group)


class Agent:
    # ------------------------------------------------------------ 生命周期
    def configure(self, config):
        self.config = config
        self.settings = config.get("agent", {})
        # ReAct 规划层：有可用模型配置就用模型，否则降级为启发式（绝不抛异常）
        self.planner = None if STABLE else (planner.make_planner(config) if planner else None)

    def reset(self, goal):
        self.goals = list(goal or [])
        self.ticks = 0
        self.scan = 0
        self.history = []
        self.leaf_streak = 0
        self.hit_count = 0
        self.table_placed = False
        self.table_pos = None
        self.plan = None
        self.plan_ttl = 0
        self.plan_used = 0
        self.heading_lock = False
        self.heading_steps = 0
        self.nav_state = "moving"
        self.nav_anchor = None
        self.nav_count = 0
        self.nav_turns = 0
        self.nav_move_after_scan = 0
        self.acq_state = "track"
        self.acq_turns = 0
        self.acq_moves = 0
        self.no_sight = 0
        self.lock_key = None
        self.lock_hits = 0
        self.lock_grace = 0
        self.stuck_steps = 0
        self.obstacle_tries = 0
        self.blocked = 0
        self.blocked_attack = 0
        self.escape = 0
        self.look_around = 0
        self.vision_spin = 0
        self.arb_cd = 0
        self.arb_sign = 0
        self.arb_agree = 0
        self.walk_anchor = None
        self.walk_anchor_steps = 0
        self.walk_state = "normal"
        self.walk_count = 0
        self.dig_fail = 0
        self.dig_stall = 0
        self.dig_escape = 0
        self.dig_last_key = None
        self.place_walk = 0
        self.tbl_wait = 0
        self.tbl_steps = 0
        self.relocate = 0
        self.tries = 0
        self.table_pending = False
        self.table_pending_slot = None
        self.table_confirm_wait = 0
        self.table_fail = 0
        self.table_recover = None
        self.dep_fail = 0
        self.spare_table = False
        self.spare_deadline = None
        self._walk_hist = []
        self._wp_busy = False
        # 短窗位移进度：anchor 净位移小可能是在走曲线，不能据此判卡住。
        self.nav_last = None
        self.nav_still = 0
        self.nav_sidestep = 0
        # PR6 根因：木块打掉后掉落在 2~4 格外，旧逻辑直接走开不捡，
        # 1500 步里打掉多根原木却只拿到 2 个。这里记录正在打的原木块，
        # 打掉后朝掉落点前进一段把物品真正收进背包。
        self.wood_key = None
        self.wood_hits = 0
        self.pickup_steps = 0
        self._pickup_base_log = 0
        if not STABLE and planner:
            self.planner = planner.make_planner(getattr(self, "config", {}))
        pl = getattr(self, "planner", None)
        self.log("reset goals=%s planner=%s" % (self.goals, type(pl).__name__ if pl else "none"))

    @staticmethod
    def log(msg):
        print("[agent] " + msg, flush=True)

    # ------------------------------------------------------------ 观测解析
    @staticmethod
    def inv(obs):
        counts, slots, equipped = {}, {}, {}
        for row in obs.get("inventory", []):
            name = row["item_id"]
            slot = int(row["slot"])
            counts[name] = counts.get(name, 0) + int(row["quantity"])
            # 同一个 item_id 可能占多个槽位（例如捡到/合成出第二把镐）。
            # 不能盲信最后一行：若已装备行在前，未装备行在后，旧写法会把
            # equipped 覆盖回 False，导致每步都重复 equip、永远不攻击；
            # 也不能固定首槽，否则 equipped 行不是首槽时会反复切到未装备槽。
            # 聚合规则：同名任一槽位已装备即视为已装备，slots 指向已装备槽；
            # 全都没装备时 slots 保持首个可用槽。
            if bool(row.get("equipped")):
                equipped[name] = True
                slots[name] = slot
            else:
                equipped.setdefault(name, False)
                slots.setdefault(name, slot)
        return counts, slots, equipped

    @staticmethod
    def hit(obs):
        return obs.get("crosshair_hit") or {}

    # ------------------------------------------------------------ 动作构造
    @staticmethod
    def noop(obs):
        return list(obs["noop_action"])

    def turn(self, obs, amount=1):
        a = self.noop(obs)
        a[4] = max(0, min(24, 12 + amount))
        return a

    def walk(self, obs, forward=1, jump=False):
        a = self.noop(obs)
        a[0] = forward
        if jump:
            a[2] = 1

        # Navigation recovery is owned by ``walk_policy`` and ``nav_step``.
        # Do not run a second watchdog here: calling nav_step from walk would
        # advance its phase timer twice and could recurse through walk_policy.
        return a

    def attack(self, obs):
        a = self.noop(obs)
        a[5] = 3
        return a

    def pitch(self, obs, amount):
        a = self.noop(obs)
        a[3] = max(0, min(24, 12 + amount))
        return a

    def aim_pitch(self, obs, target_deg):
        """把俯仰**绝对**瞄准到 target_deg（度）。

        实测结论（来自 world-_qtp1qi0 轨迹）：
            action[3] = 12 + k 时，pitch 变成 +15k 度；
            **正 pitch = 低头**（准星会命中 grass_block），负 pitch = 抬头。
        之前的 bug：想抬头却一直发正数，结果把视线压到 90 度盯着地面，
        所以 1500 步里一次都没看到树。
        """
        cur = float((obs.get("orientation") or {}).get("pitch", 0.0))
        steps = int(round((target_deg - cur) / 15.0))
        a = self.noop(obs)
        a[3] = max(0, min(24, 12 + steps))
        return a

    # ------------------------------------------------------------ 卡住检测
    def is_stuck(self, obs):
        pos = obs.get("position") or [0, 0, 0]
        self.history.append(tuple(round(float(v), 2) for v in pos))
        if len(self.history) > STUCK_WINDOW:
            self.history.pop(0)
        if len(self.history) < STUCK_WINDOW:
            return False
        xs = [p[0] for p in self.history]
        zs = [p[2] for p in self.history]
        return (max(xs) - min(xs)) < STUCK_EPS and (max(zs) - min(zs)) < STUCK_EPS

    # ------------------------------------------------------------ 通用子策略
    def _block_key(self, hit):
        """用命中方块的坐标当"目标指纹"，用于判断是否还在打同一格。"""
        if hit.get("block_distance") is None:
            return None
        return (hit.get("traced_block_x"), hit.get("traced_block_y"), hit.get("traced_block_z"))

    def seek_and_break(self, obs, group, tag, up_scan=False, explore=False):
        """找方块 -> 靠近 -> **持续攻击**打掉。

        v11 的核心修正（来自人工看回放的结论）：
            Minecraft 的方块破坏进度是**连续**的，中途转向/改俯仰会**重置进度**。
            v10 的写法是「攻击2次 → 抬头1次」交替，等于每次都从头开始挖，
            所以 974 次攻击一个树叶都没破。
            现在改成：一旦锁定目标，就**连续攻击**（默认 40 次），
            期间绝不插入任何转向或俯仰动作。
        """
        hit = self.hit(obs)
        target = (hit.get("block_name") or "")
        dist = hit.get("block_distance")
        key = self._block_key(hit)

        # 原木被打掉（准星已换格）-> 朝原方向走几步把掉落物捡起来。
        if (tag == "wood" and self.wood_key is not None
                and key != self.wood_key and self.wood_hits >= 8):
            self._start_log_pickup(obs)
            return self.walk(obs, forward=1), True

        # ① 目标在攻击距离内 -> 持续连击（不转向、不抬头）
        if (_is_any(target, group) or _is_any(target, OBSTACLES)) and dist is not None and dist <= REACH:
            # PR6 根因：原木破坏耗时约 65 帧。先记下正在打的木块；一旦准星
            # 换到别的方块（说明这一格被打掉），就走向掉落点捡物品 —— 否则
            # 掉落物留在 2~4 格外，背包永远拿不到（云端 3/5、本地 run2 3/5）。
            if tag == "wood" and _is_any(target, group):
                if key == self.wood_key:
                    self.wood_hits += 1
                else:
                    self.wood_key = key
                    self.wood_hits = 1
            # 目标换了（上一格已打掉）就重置连击计数
            if key != getattr(self, "lock_key", None):
                self.lock_key = key
                self.lock_hits = 0
                self.log("LOCK on %s at %s (d=%.1f)" % (target, key, float(dist)))
            self.lock_hits = getattr(self, "lock_hits", 0) + 1
            if self.lock_hits > 200:         # 极端保护：手打原木约需 60~80 下，留足余量
                self.lock_key = None
                self.lock_hits = 0
                # 咬穿树冠：整整咬穿 200 下还只是树叶，说明树干在更高处，
                # 抬头 25 度继续咬，才可能露出 wood（否则永远停在树冠层）。
                if _is_any(target, ("leaves", "spruce_leaves", "oak_leaves",
                                     "birch_leaves", "jungle_leaves", "acacia_leaves",
                                     "dark_oak_leaves", "leaves2")):
                    self.log("chew leaves -> look up for trunk")
                    return self.aim_pitch(obs, -25), True
                return self.turn(obs, amount=3), True
            return self.attack(obs), True

        # 连击中断（目标丢失）-> 清状态
        self.lock_key = None
        self.lock_hits = 0

        # ② 目标可见但太远 -> 靠近（卡住时以跳跃为主，每 6 步强制大转向）
        if _is_any(target, group) and dist is not None:
            return self.walk_policy(obs), True

        # ②.5 贴脸障碍 -> 先跳，跳不过再斜向上挖（仅在"长时间没找到目标"后启用）
        #     实测教训：这套逻辑若对所有场景生效，会破坏木制阶段
        #     （woodcraft 复验从 5/5 掉成 0/5，因为它把"站在树旁"也当成障碍去挖）。
        #     所以用 self.scan > 400 做闸门：木制在 274 步就找到树，不会触发；
        #     只有像石器场景那样找了很久还没目标，才启用探索性行为。
        late = explore            # 仅找矿阶段启用探索性行为
        if late and dist is not None and dist <= 2.0 and target not in ("", "none_in_range"):
            self.obstacle_tries = getattr(self, "obstacle_tries", 0) + 1

            # 阶段 1：先尝试「跳过障碍」（最多 8 次）
            if self.obstacle_tries <= 8:
                return self.walk(obs, forward=1, jump=True), False

            # 阶段 2：跳不过去 -> 挖一条**斜向上**的通道翻过去
            #   s6 的教训：斜向下挖会掉进地下/水里（实测命中 water 5613 次、
            #   Y 掉 7 格却什么也没得到）。往上挖才能翻过土坎继续前进。
            cur = float((obs.get("orientation") or {}).get("pitch", 0.0))
            if cur > -20:
                return self.aim_pitch(obs, -25), False      # 抬头 25 度

            key = self._block_key(hit)
            if key != getattr(self, "lock_key", None):
                self.lock_key = key
                self.lock_hits = 0
                self.log("dig up-slope through %s at %s" % (target, key))
            self.lock_hits = getattr(self, "lock_hits", 0) + 1
            if self.lock_hits > 120:
                # 这段挖不动就换个方向，避免死磕
                self.lock_key = None
                self.lock_hits = 0
                self.obstacle_tries = 0
                return self.turn(obs, amount=6), False
            return self.attack(obs), False
        self.obstacle_tries = 0

        # ③ 没有目标 -> 边走边扫
        #    【木制阶段】恢复已验证可通关的局部游走参数（world-tg7tyhw4, 629 步 5/5）：
        #    每 16 步微调俯仰、每 40 步转 45 度、其余全速前进。
        #    注意：不要在这里加脱困逻辑——脱困的转向会让它离开出生点附近的林地。
        self.scan += 1

        # ===== 贴脸障碍兜底：连续顶住就开挖 =====
        # 实测（world-5a2yhrqc）1492 步全在前进、准星 1383 次是 2 格内的草方块、
        # 0 次攻击 —— 就是撞在坡上，视觉又误判"树在正前方"。这里直接挖穿。
        # 距离阈值放到 3.0、且只有真正看不到近处方块时才清零：
        # 实测 world-g3n7c7_v 里距离在 2.0 附近抖动，计数器被反复清零，
        # 6000 步只攻击 19 次，位移仅 3×8 格。
        if explore and (not STABLE) and dist is not None and dist <= 3.0 and target not in ("", "none_in_range"):
            if target in ("water", "lava", "flowing_water", "flowing_lava"):
                self.blocked = 0
                return self.turn(obs, amount=6), False
            self.blocked = getattr(self, "blocked", 0) + 1
            if self.blocked > 8:
                # 同样要超时：连续打 40 下还没打通 -> 放弃这条通路，转 90 度换方向
                self.blocked_attack = getattr(self, "blocked_attack", 0) + 1
                if self.blocked_attack > 40:
                    self.blocked_attack = 0
                    self.blocked = 0
                    self.log("blocked attack timeout(40) -> turn away")
                    return self.turn(obs, amount=6), False
                return self.attack(obs), False
        elif dist is None or target in ("", "none_in_range") or dist > 4.5:
            self.blocked = 0
            self.blocked_attack = 0

        # ===== ReAct 规划层：周期性问一次"该往哪走/该干什么" =====
        # 规则层负责执行，模型只负责高层决策；模型不可用时 planner 为 None，
        # 自动退回后面的启发式搜索。
        # 只在「眼前没有可挖目标」时才问模型：
        # 实测准星盯着近处方块时，模型容易耗尽输出预算返回空（finish=length），
        # 而这种情形规则层本来就能直接处理（挖 / 清障），不必浪费 token。
        if self.planner is not None and (dist is None or dist > REACH):
            try:
                # ---- 航向锁定：模型只在"航向失效"时改方向 ----
                # 实测同一观测模型常连续回 walk，每 40 步重问一次等于每 40 步推翻方向，
                # 这是此前成绩方差大的主因。
                self.heading_steps = getattr(self, "heading_steps", 0) + 1
                if getattr(self, "heading_lock", False) and self.heading_steps <= HEADING_TTL:
                    # 锁定期内仍要接受视觉校正：否则模型一旦锁错方向，
                    # 240 步内视觉再也插不上话（实测 world-zici2bez 首帧 offset=0.71 被忽略）。
                    return self.walk_policy(obs), False
                self.plan_ttl = getattr(self, "plan_ttl", 0) - 1
                if self.plan_ttl <= 0:
                    self.plan = self.planner.decide(obs, {
                        "goal_desc": "木镐和石器",
                        "recent": "step=%d" % obs.get("step", 0),
                    })
                    self.plan_ttl = PLAN_INTERVAL
                    self.plan_used = 0
                p = self.plan
                if p:
                    # 关键：turn 只执行一次。模型说"向左转再前进"是**一步**的语义，
                    # 若在整个 PLAN_INTERVAL 内都执行 turn，就会原地转 40 步（实测 0 里程碑）。
                    self.plan_used = getattr(self, "plan_used", 0) + 1
                    turn = p["turn"] if self.plan_used <= 1 else "none"
                    self.log("plan goal=%s turn=%s verb=%s used=%d" % (p["goal"], turn, p["verb"], self.plan_used))
                    if turn == "left":
                        self.heading_lock = True
                        self.heading_steps = 0
                        return self.turn(obs, amount=-1), False
                    if turn == "right":
                        self.heading_lock = True
                        self.heading_steps = 0
                        return self.turn(obs, amount=1), False
                    if p["verb"] == "mine" and dist is not None and dist <= REACH:
                        return self.attack(obs), False
                    # 模型只说"走过去"，但方向可能是错的：它看不到画面边缘的树。
                    # 这里补一次视觉：树不在画面中央就让视觉接管方向。
                    if vision is not None and (dist is None or dist > 6.0):
                        off = vision.detect_offset(obs)
                        if off is not None and abs(off) > 0.15:
                            self.log("plan walk + vision offset=%.2f -> steer" % off)
                            self.heading_lock = True
                            self.heading_steps = 0
                            return self.turn(obs, amount=(1 if off > 0 else -1)), False
                    # 模型说"走过去"，具体怎么走交给分级执行器
                    return self.walk_policy(obs), False
            except Exception:
                # 规划层任何异常都不允许拖垮 Agent
                self.plan = None

        if not explore:
            # ---- 离线视觉找树：每 4 步看一次画面，把树冠转到画面中央 ----
            if vision is not None and self.scan % 4 == 0 and (STABLE or dist is None or dist > 6.0):
                # 防抖 1：连续转向太多次说明视觉在抖（实测 savanna 场景
                # offset 在 -0.26~+0.23 反复跳，Agent 原地左右转、0 位移），
                # 这时强制走一段再说。
                if getattr(self, "vision_spin", 0) > 12:
                    self.vision_spin = 0
                    self.log("vision spin guard -> force walk")
                    return self.walk(obs, forward=1), False
                off = vision.detect_offset(obs)
                if off is not None:
                    self.log("vision offset=%.2f" % off)
                    # 防抖 2：死区放到 0.30，只有明显偏才转
                    if off > 0.15:
                        self.vision_spin = getattr(self, "vision_spin", 0) + 1
                        return self.turn(obs, amount=1), False
                    if off < -0.15:
                        self.vision_spin = getattr(self, "vision_spin", 0) + 1
                        return self.turn(obs, amount=-1), False
                    self.vision_spin = 0
                    return self.walk_policy(obs), False
            if self.scan % 16 == 0:
                return self.aim_pitch(obs, -10), False
            if self.scan % 40 == 0:
                return self.turn(obs, amount=3), False
            return self.walk_policy(obs), False

        #    【找矿阶段】长距离探索 + 脱困
        if getattr(self, "escape", 0) > 0:
            self.escape -= 1
            return self.walk(obs, forward=1, jump=True), False
        if self.is_stuck(obs):
            self.escape = 4
            self.log("stuck -> escape(turn90+forward x4)")
            return self.turn(obs, amount=6), False
        if self.scan % 24 == 0:
            return self.aim_pitch(obs, 0), False
        if self.scan % 600 == 0:
            return self.turn(obs, amount=6), False
        # 定点 360 度环视：长时间没看到目标时，先原地转一圈找树/找矿，
        # 避免像 s5 那样朝反方向一路挖进地底（回放里树其实就在背后）。
        # s8 实测：环视太稀疏（每 600 步一次）时，6000 步只看到 wood 2 次。
        if explore and self.scan % 150 == 0:
            self.look_around = 24
        if getattr(self, "look_around", 0) > 0:
            self.look_around -= 1
            return self.turn(obs, amount=1), False
        return self.walk(obs, forward=1), False

    # ------------------------------------------------------------ 掉落物捡取
    def _start_log_pickup(self, obs):
        """原木被打掉：朝前方（掉落点方向）走一段把物品捡进背包。"""
        self.pickup_steps = LOG_PICKUP_STEPS
        counts, _, _ = self.inv(obs)
        self._pickup_base_log = (counts.get("log", 0) + counts.get("log2", 0)
                                 + counts.get("wood", 0))
        self.wood_key = None
        self.wood_hits = 0
        self.log("log broken -> walk to drop")

    # ------------------------------------------------------------ 工作台自测距
    def _track_table(self, obs):
        """记录工作台坐标：准星命中 crafting_table 时抓取方块坐标。

        为什么不用 observation["nearby_tools"]["table"]：
        实测 world-tfagx6ru 全程 1500 步该字段恒为 False，
        即使准星贴着脸（0.6 格）正对刚放好的工作台也还是 False。
        """
        hit = self.hit(obs)
        if hit.get("block_name") == "crafting_table" and hit.get("traced_block_x") is not None:
            self.table_pos = (hit["traced_block_x"], hit["traced_block_y"], hit["traced_block_z"])

    def _near_table(self, obs):
        """自己算「是否站在工作台旁」：优先用准星，其次用坐标距离。"""
        hit = self.hit(obs)
        if hit.get("block_name") == "crafting_table" and hit.get("block_distance") is not None:
            if float(hit["block_distance"]) <= 4.0:
                return True
        tp = getattr(self, "table_pos", None)
        if tp is not None:
            p = obs.get("position") or [0, 0, 0]
            dx = float(p[0]) - float(tp[0])
            dy = float(p[1]) - float(tp[1])
            dz = float(p[2]) - float(tp[2])
            # 仅 x/z 水平距离会在“下挖后台子留在高处”时误判为旁边
            # （v2 实跑：水平 1.35、垂直 9，导致 48% 预算空转）。
            vertical_ok = abs(dy) <= 2.0
            distance3 = (dx * dx + dy * dy + dz * dz) ** 0.5
            return vertical_ok and distance3 <= 3.0
        return False

    # ------------------------------------------------------ 工作台确认与依赖恢复
    @staticmethod
    def _last_table_placement(obs):
        """只用公开 last_action 判断上一步放置是否真的消耗了台子/熔炉。

        ``valid`` 只代表 8 维动作向量合法，不代表放置成功；这里只在
        ``inventory_delta`` 显示台子（或熔炉）数量减少时才视为成功。
        """
        last = obs.get("last_action")
        if not isinstance(last, dict):
            return None
        action = last.get("action")
        if not isinstance(action, list) or len(action) < 6 or action[5] != 6:
            return None
        delta = last.get("inventory_delta")
        if not isinstance(delta, dict):
            return "failed"
        if delta.get("crafting_table", 0) < 0 or delta.get("furnace", 0) < 0:
            return "confirmed"
        return "failed"

    def _update_table_state(self, obs):
        """用公开反馈收敛 table_pending；不把历史布尔值当作台子可用。"""
        if not getattr(self, "table_pending", False):
            return
        self.table_confirm_wait = getattr(self, "table_confirm_wait", 0) + 1
        hit = self.hit(obs)
        near_table = (hit.get("block_name") == "crafting_table" and
                      hit.get("block_distance") is not None and
                      float(hit["block_distance"]) <= REACH)
        result = self._last_table_placement(obs)
        if result == "confirmed" or near_table:
            self.table_pending = False
            self.table_pending_slot = None
            self.table_placed = True
            self.table_fail = 0
            self.tbl_wait = 0
            self.log("table placement confirmed")
            return
        if result == "failed" or self.table_confirm_wait > 3:
            self.table_pending = False
            self.table_pending_slot = None
            self.table_placed = False
            self.table_fail = getattr(self, "table_fail", 0) + 1
            self.tbl_wait = 0
            # 失败后换姿势：1) 抬头到 55 度找可放置面 2) 转向 3) 换位置。
            # 直接俯视脚下方块时，放置目标可能与玩家自身位置重叠而必失败
            # （4593 步实跑里连续 1240 次 place 全部失败即此原因）。
            move = self.table_fail % 3
            self.table_recover = "aim" if move == 1 else ("turn" if move == 2 else "walk")
            self.log("table placement failed/unconfirmed (attempt %d)" % self.table_fail)

    def _send_place(self, obs, slot, label="crafting_table"):
        self.table_pending = True
        self.table_pending_slot = slot
        self.table_confirm_wait = 0
        self.log("place %s slot=%d (awaiting confirmation)" % (label, slot))
        action = slot_action(obs, "place", slot)
        action[3] = 12
        return action

    def _material_step(self, obs, counts, craftable, want_sticks=False):
        """缺板/缺棍时只做一个合法制作步；无合法配方返回 None。"""
        craftable = set(craftable)
        log_n = counts.get("log", 0) + counts.get("log2", 0) + counts.get("wood", 0)
        planks = counts.get("planks", 0)
        sticks = counts.get("stick", 0)
        if want_sticks:
            if sticks < 2 and planks >= 2 and "stick" in craftable:
                return craft_action(obs, "stick")
            if sticks < 2 and planks < 2 and log_n >= 1 and "planks" in craftable:
                return craft_action(obs, "planks")
            return None
        if planks < 4 and log_n >= 1 and "planks" in craftable:
            return craft_action(obs, "planks")
        return None

    @staticmethod
    def _best_pick(counts):
        """按 iron > stone > wooden 选当前最高可用镐（S10）。"""
        for name in ("iron_pickaxe", "stone_pickaxe", "wooden_pickaxe"):
            if counts.get(name, 0) > 0:
                return name
        return None

    def _table_step(self, obs, counts, slots, craftable):
        """缺台时做一个合法步骤：合成台子 -> 放置并等待公开确认。"""
        craftable = set(craftable)
        tables = counts.get("crafting_table", 0)
        planks = counts.get("planks", 0)
        log_n = counts.get("log", 0) + counts.get("log2", 0) + counts.get("wood", 0)
        if tables >= 1:
            slot = slots.get("crafting_table")
            if slot is None or self.table_pending:
                return None
            if self.table_fail >= 9:
                self.log("table placement abandoned after %d failures" % self.table_fail)
                return None
            if not self.table_placed or not self._near_table(obs):
                return self._send_place(obs, slot, "crafting_table")
            return None
        if "crafting_table" in craftable and planks >= 4:
            # 重新做一张新台子：上一张的失败计数与姿势恢复清零。
            self.table_fail = 0
            self.table_recover = None
            return craft_action(obs, "crafting_table")
        if log_n >= 1 and planks < 4 and "planks" in craftable:
            return craft_action(obs, "planks")
        return None

    # ------------------------------------------------------------ 统一导航状态机
    def nav_step(self, obs):
        """Single-owner navigation state machine with bounded recovery phases."""
        pos = self._p(obs)
        # 每帧真实位移（而不是相对 anchor 的净位移）才是「被挡住」的直接信号：
        # 曲线行走时 anchor 净位移可以很小，但每帧仍有位移。
        delta = 99.0 if self.nav_last is None else self._dist2(pos, self.nav_last)
        self.nav_last = pos
        if delta < 0.05:
            self.nav_still += 1
        else:
            self.nav_still = 0
            self.nav_sidestep = 0
        hit = self.hit(obs)
        target = (hit.get("block_name") or "").lower()
        dist = hit.get("block_distance")
        visible = dist is not None and target not in ("", "none_in_range")

        if self.nav_anchor is None:
            self.nav_anchor = pos
            self.nav_count = 0
        self.nav_count += 1
        moved = self._dist2(pos, self.nav_anchor)

        # Progress ends jump/dig recovery; detours deliberately run their full
        # course so they do not collapse back into the blocked heading.
        if moved >= 2.0 and self.nav_state not in ("detouring", "scanning"):
            self.nav_state = "moving"
            self.nav_count = 0
            self.nav_anchor = pos
            self.nav_turns = 0
            self.no_sight = 0
            self.nav_move_after_scan = 0
            moved = 0.0

        if visible:
            self.no_sight = 0
        elif self.nav_state == "moving" and self.nav_move_after_scan <= 0:
            self.no_sight += 1

        # A failed scan must be followed by a meaningful travel interval. Reset
        # the sight counter for its duration so the same scan cannot restart on
        # the next frame.
        if self.nav_state == "moving" and self.nav_move_after_scan > 0:
            self.nav_move_after_scan -= 1
            self.no_sight = 0
            return self.walk(obs, forward=1)

        if self.nav_state == "moving" and self.no_sight >= 10:
            self.nav_state = "scanning"
            self.nav_count = 0
            self.nav_turns = 0
            self.log("nav: lost sight -> scanning 360")

        if self.nav_state == "scanning":
            cur = float((obs.get("orientation") or {}).get("pitch", 0.0))
            if abs(cur) > 10:
                return self.aim_pitch(obs, 0)
            self.nav_turns += 1
            if self.nav_turns <= 12:
                return self.turn(obs, amount=2)
            self.nav_state = "moving"
            self.nav_count = 0
            self.nav_turns = 0
            self.nav_anchor = pos
            self.no_sight = 0
            self.nav_move_after_scan = 12
            self.log("nav: scan done -> move")
            return self.walk(obs, forward=1)

        if self.nav_state == "jumping":
            if self.nav_count <= 8:
                return self.walk(obs, forward=1, jump=True)
            self.nav_state = "digging"
            self.nav_count = 0
            self.log("nav: jump failed -> digging")
            return self.aim_pitch(obs, -25)

        if self.nav_state == "digging":
            if self.nav_count > 40:
                self.nav_state = "detouring"
                self.nav_count = 0
                self.log("nav: dig timeout(40) -> detouring")
                return self.turn(obs, amount=6)
            if target in ("water", "lava", "flowing_water", "flowing_lava"):
                self.nav_state = "detouring"
                self.nav_count = 0
                self.log("nav: fluid ahead -> detouring")
                return self.turn(obs, amount=6)
            cur = float((obs.get("orientation") or {}).get("pitch", 0.0))
            if cur > -20:
                return self.aim_pitch(obs, -25)
            if dist is not None and float(dist) <= REACH:
                return self.attack(obs)
            return self.walk(obs, forward=1, jump=True)

        if self.nav_state == "detouring":
            if self.nav_count <= 10:
                return self.walk(obs, forward=1)
            if self.nav_count <= 13:
                return self.turn(obs, amount=-4)
            self.nav_state = "moving"
            self.nav_count = 0
            self.nav_anchor = pos
            self.no_sight = 0
            self.log("nav: detour done -> moving")
            return self.walk(obs, forward=1)

        # Enter recovery only from the moving phase. Active phases above use
        # their own timers and cannot be stranded behind the stuck threshold.
        # Known limitation: re-anchoring claims progress at moved >= 2.0 while
        # this stall test needs moved < 1.0, so net movement in [1.0, 2.0) can
        # keep nav_count growing (PR6 failure trace step 1358-1500). Widening
        # this bound to <2.0 was measured to regress the verified woodcraft
        # path (local run 0/5, diverging at step 430), so the anchor rule stays
        # untouched; the PR6 hard case is instead handled by the per-step
        # short-window sidestep below (and, in practice, by log-drop pickup).
        if self.nav_state == "moving" and self.nav_count >= 12 and moved < 1.0:
            self.nav_state = "jumping"
            self.nav_count = 0
            self.log("nav: stuck -> jumping")
            return self.walk(obs, forward=1, jump=True)

        # 短窗零位移：前进帧连续没有真实位移说明前方被挡。此时只做轻量
        # 90 度侧移（不 jump/dig，避免把已经站立的 agent 挖进地下），
        # 最多换 3 个方向后放行给原逻辑（PR6 失败轨迹 step 1358-1500 的
        # 143 帧原地前进由此兜底）。
        if self.nav_state == "moving" and self.nav_still >= NAV_STILL_LIMIT:
            self.nav_still = 0
            self.nav_count = 0
            # 保留原 anchor：死区净位移仍在 [1.0,2.0) 时不应退回 jump/dig，
            # 只有真正 moved<1.0 的原有卡住逻辑才允许 jump/dig。
            self.nav_sidestep += 1
            if self.nav_sidestep <= 3:
                self.log("nav: blocked walk -> sidestep %d" % self.nav_sidestep)
                return self.turn(obs, amount=6)
            self.nav_sidestep = 0
            return self.walk(obs, forward=1)

        return self.walk(obs, forward=1)

    # ------------------------------------------------------------ 丢目标重扫闭环
    def acquire(self, obs):
        """目标丢失后的完整闭环：短暂等待 -> 视线回正 -> 系统扫 360° -> 移动再扫。

        为什么需要（world-zo6pfjk2 实测）：
            1500 步里 1334 步准星 none_in_range（盯着空气），净位移仅 14×12 格。
            攻击逻辑本身没问题（127 次攻击、8 步连续咬合），
            缺的是"丢了目标之后怎么找回来"这条路径。
        """
        hit = self.hit(obs)
        target = hit.get("block_name") or ""
        dist = hit.get("block_distance")
        visible = dist is not None and target not in ("", "none_in_range")

        if visible:
            self.acq_state = "track"
            self.acq_turns = 0
            self.acq_moves = 0
            self.no_sight = 0
            # 看到了但够不着 -> 走近（走 walk_policy，保证会跳/挖/绕）
            if target in self.ARB_CORE and float(dist) > REACH:
                return self.walk_policy(obs)
            return None

        # ---- 看不到目标 ----
        self.no_sight = getattr(self, "no_sight", 0) + 1
        if self.no_sight < 10:
            return None                     # 短暂丢失，先不打断

        cur_pitch = float((obs.get("orientation") or {}).get("pitch", 0.0))

        if self.acq_state != "rescan":
            self.acq_state = "rescan"
            self.acq_turns = 0
            self.log("acquire: target lost -> rescan")

        # 第一步：视线回正（chew 把 pitch 抬到 -25 后没人管，射线一路打空）
        if abs(cur_pitch) > 10:
            return self.aim_pitch(obs, 0)

        # 第二步：每步转 30 度，12 步扫满 360 度
        if self.acq_turns < 12:
            self.acq_turns += 1
            return self.turn(obs, amount=2)

        # 第三步：扫完一圈还是没有 -> 移动一段距离再扫
        self.acq_turns = 0
        self.acq_state = "move"
        self.acq_moves = 0
        self.log("acquire: full scan failed -> move & rescan")
        return self.walk_policy(obs)

    # ------------------------------------------------------------ 动作仲裁器
    ARB_CORE = ("wood", "log", "oak_log", "birch_log", "spruce_log", "jungle_log",
                "acacia_log", "dark_oak_log", "leaves", "leaves2", "spruce_leaves",
                "oak_leaves", "birch_leaves", "jungle_leaves", "acacia_leaves",
                "dark_oak_leaves")

    def arbitrate(self, obs):
        """动作仲裁器：一帧只允许一个控制器出手。

        优先级（高 -> 低）：
            P0 攻击   准星 4 米内有可挖方块
            P1 脱困   walk 阶梯正处于 jump/dig/detour
            P2 视觉转向 带 3 步冷却 + 同向连续 2 次才采信
            P3 其余   交给规划/探索流程
        返回 None 表示不接管。
        """
        hit = self.hit(obs)
        target = hit.get("block_name") or ""
        dist = hit.get("block_distance")

        # ---- P0：看得见就砍（离开树冠遮挡的树干也算）----
        if dist is not None and float(dist) <= REACH and target in self.ARB_CORE:
            self.no_sight = 0
            self.lock_grace = 3          # 命中即刷新保鲜期
            action, _ = self.seek_and_break(obs, LOG_BLOCKS, "wood", up_scan=True)
            return action

        # ---- P1：脱困/重扫统一交给导航状态机（单一计时器，不会互相打断）----
        if getattr(self, "nav_state", "moving") != "moving":
            return self.nav_step(obs)

        # ---- P2：视觉转向（冷却 + 一致性）----
        cd = getattr(self, "arb_cd", 0)
        if cd > 0:
            self.arb_cd = cd - 1
            return None
        if vision is not None and (dist is None or float(dist) > 6.0):
            off = vision.detect_offset(obs)
            if off is not None and abs(off) > 0.25:
                sign = 1 if off > 0 else -1
                if getattr(self, "arb_sign", 0) == sign:
                    self.arb_agree = getattr(self, "arb_agree", 0) + 1
                else:
                    self.arb_sign = sign
                    self.arb_agree = 1
                if self.arb_agree >= 2:
                    self.arb_cd = 3          # 转一次后必须走 3 步
                    self.arb_agree = 0
                    self.log("arbiter: vision turn %+d (off=%.2f)" % (sign, off))
                    return self.turn(obs, amount=sign)
            else:
                self.arb_agree = 0

        # ---- P3：没有需要强制接管的情况 ----
        # Inventory progression and ordinary exploration must retain control.
        return None

    # ------------------------------------------------------------ 移动执行器
    def _p(self, obs):
        p = obs.get("position") or [0, 0, 0]
        return (float(p[0]), float(p[1]), float(p[2]))

    @staticmethod
    def _dist2(a, b):
        return ((a[0] - b[0]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5

    def walk_policy(self, obs):
        """Apply safety overrides, then let the single navigator own movement."""
        override = self.arbitrate(obs)
        if override is not None:
            return override

        # Water cannot be mined. Detect it from the legal image observation and
        # enter the same timed detour state used by other navigation failures.
        if vision is not None and self.nav_count % 4 == 1:
            woff = vision.water_offset(obs)
            if woff is not None and abs(woff) < 0.30:
                self.nav_state = "detouring"
                self.nav_count = 0
                self.nav_anchor = self._p(obs)
                self.log("water ahead (off=%.2f) -> detour" % woff)
                return self.turn(obs, amount=6)
        return self.nav_step(obs)

    # ------------------------------------------------------------ 向下挖竖井
    def _dig_give_up(self, obs):
        """连续恢复失败 -> 放弃当前竖井，交给水平导航换位置。"""
        self.dig_fail = 0
        self.dig_escape = 0
        self.dig_stall = 0
        self.dig_last_key = None
        self.log("dig_down: repeated failures -> horizontal explore")
        return self.walk_policy(obs)

    def _dig_relocate(self, obs):
        """不可破坏/液体/无进展：抬头转向离开，有界后再试。"""
        self.dig_escape = 10
        self.dig_stall = 0
        self.dig_last_key = None
        self.lock_key = None
        self.lock_hits = 0
        return self.turn(obs, amount=6)

    @staticmethod
    def _public_dig_progress(obs):
        """公开 last_action 是否显示上一步攻击产生了进展（掉落/位移）。"""
        last = obs.get("last_action")
        if not isinstance(last, dict):
            return False
        action = last.get("action")
        if not isinstance(action, list) or len(action) < 6 or action[5] != 3:
            return False
        delta = last.get("inventory_delta")
        if isinstance(delta, dict) and delta:
            return True
        moved = last.get("position_delta")
        if isinstance(moved, list):
            return any(abs(float(v)) > 0.05 for v in moved[:3])
        return False

    def dig_down(self, obs):
        """低头对准脚下方块连续挖，形成 1×1 竖井，直到挖到石头层。

        为什么需要它：石头在地下，surface 的 grass/dirt 不在 STONE_BLOCKS 里，
        原来的 seek_and_break 在草原上会一直找不到 stone。

        P1-04：基岩/液体不可挖；同一目标长期无公开进展时必须有界脱困并
        换路线，而不是原地 yaw 空转到时限。
        """
        hit = self.hit(obs)
        cur = float((obs.get("orientation") or {}).get("pitch", 0.0))
        if cur < 70:
            return self.aim_pitch(obs, 90)          # 先低头到 -90 度（正 pitch=低头）
        name = (hit.get("block_name") or "")
        # 已进入脱困：先抬头离开竖井，再交给导航继续走。
        if getattr(self, "dig_escape", 0) > 0:
            self.dig_escape -= 1
            if abs(cur) > 15:
                return self.aim_pitch(obs, 0)
            return self.walk(obs, forward=1)
        # 基岩/液体：不攻击，有界恢复后换路线。
        if _is_any(name, UNBREAKABLE_BLOCKS) or _is_any(name, LIQUID_BLOCKS):
            self.dig_fail = getattr(self, "dig_fail", 0) + 1
            self.log("dig_down: %s is not mineable" % name)
            if self.dig_fail >= 3:
                return self._dig_give_up(obs)
            return self._dig_relocate(obs)
        dist = hit.get("block_distance")
        if dist is not None and dist <= REACH and name not in ("", "none_in_range"):
            key = self._block_key(hit)
            if key != getattr(self, "dig_last_key", None) or self._public_dig_progress(obs):
                self.dig_stall = 0
            else:
                self.dig_stall = getattr(self, "dig_stall", 0) + 1
            self.dig_last_key = key
            if key != getattr(self, "lock_key", None):
                self.lock_key = key
                self.lock_hits = 0
                self.log("dig_down on %s at %s" % (name, key))
            self.lock_hits = getattr(self, "lock_hits", 0) + 1
            if self.lock_hits > 200 or self.dig_stall >= DIG_STALL_LIMIT:
                self.dig_fail = getattr(self, "dig_fail", 0) + 1
                self.log("dig_down: no progress (%d hits) -> relocate" % self.lock_hits)
                if self.dig_fail >= 3:
                    return self._dig_give_up(obs)
                return self._dig_relocate(obs)
            return self.attack(obs)
        self.dig_stall = 0
        self.dig_last_key = None
        return self.walk(obs, forward=1)            # 脚下没方块就挪一步

    # ------------------------------------------------------------ 主循环
    def act(self, observation):
        self.ticks += 1
        counts, slots, equipped = self.inv(observation)
        hit = self.hit(observation)
        self._track_table(observation)
        self._update_table_state(observation)
        if getattr(self, "table_pending", False):
            return self.noop(observation)
        # 放置失败后先做一个有界的换姿势动作，再重试，避免原地死循环。
        recovery = getattr(self, "table_recover", None)
        if recovery is not None:
            self.table_recover = None
            self.log("table recovery: %s" % recovery)
            if recovery == "aim":
                return self.aim_pitch(observation, 55)
            if recovery == "turn":
                return self.turn(observation, amount=6)
            return self.walk(observation, forward=1)

        log_n = counts.get("log", 0) + counts.get("log2", 0) + counts.get("wood", 0)
        planks = counts.get("planks", 0)
        sticks = counts.get("stick", 0)
        tables = counts.get("crafting_table", 0)
        wpick = counts.get("wooden_pickaxe", 0)
        cobble = counts.get("cobblestone", 0)
        spick = counts.get("stone_pickaxe", 0)
        furnace = counts.get("furnace", 0)

        # ===== 目标全部达成 -> 待命 =====
        if self.goals and all(
            counts.get(g, 0) > 0 or (g == "log" and counts.get("log2", 0) > 0)
            for g in self.goals
        ):
            return self.noop(observation)

        # ===== 木制阶段：严格按材料预算推进 =====
        # 材料账：木板 9 = 工作台4 + 木棍2(→木棍4) + 木镐3
        # 重要：只用 observation["craftable"]（环境给出的合法可合成列表）作为
        # 权威信号——因为 nearby_tools.table 实测恒为 False，不能作为判据。
        craftable = set(observation.get("craftable") or [])
        # 已有更高一级的镐（石镐/铁镐）时不再回退重走木制；官方里程碑是
        # “曾经合法获得”，旧木镐丢失不撤销已有进度（P1-05）。
        if wpick == 0 and spick == 0 and counts.get("iron_pickaxe", 0) == 0:
            # 原木掉落物捡取优先于继续采集（但别打断可立即完成的木镐合成）。
            if self.pickup_steps > 0 and "wooden_pickaxe" not in craftable:
                if log_n > self._pickup_base_log:
                    self.pickup_steps = 0        # 已捡到，立刻恢复正常进度
                else:
                    self.pickup_steps -= 1
                    return self.walk(observation, forward=1)
            # 换位重放：工作台放下后环境没识别到 -> 先走开一段再放一个新的
            if getattr(self, "relocate", 0) > 0:
                self.relocate -= 1
                if self.relocate % 4 == 0:
                    return self.turn(observation, amount=3)
                return self.walk(observation, forward=1)
            # 顺序很重要：先把已有的工作台放出去，再做别的。
            # （v20 的教训：把「木板<9 就砍树」放最前，会在做完台子后
            #   因为木板降到 3 又回去砍树，台子永远躺在背包里 -> 放置 0 次）
            if tables >= 1 and not self.table_placed and not self.table_pending:
                if self.table_fail >= 3:
                    self.table_fail = 0
                    self.relocate = 12
                    self.log("table placement failed 3x -> relocate and retry")
                    return self.walk(observation, forward=1)
                slot = slots.get("crafting_table")
                if slot is None:
                    return self.noop(observation)
                if not hit.get("block_name") or hit.get("block_name") == "none_in_range":
                    cur_pitch = float((observation.get("orientation") or {}).get("pitch", 0.0))
                    if cur_pitch < 40:
                        return self.aim_pitch(observation, 55)
                    self.place_walk = getattr(self, "place_walk", 0) + 1
                    if self.place_walk % 3 == 0:
                        return self.turn(observation, amount=3)
                    return self.walk(observation, forward=1)
                return self._send_place(observation, slot, "crafting_table")

            if "wooden_pickaxe" in craftable:
                return craft_action(observation, "wooden_pickaxe")

            # 等待工作台被识别期间仍要补料：木板/木棍不依赖台子，必须放在
            # tbl_wait 之前，否则“放台后 60 步只走不补料”（P1-03）。
            if log_n >= 1 and planks < 9 and "planks" in craftable:
                return craft_action(observation, "planks")
            if sticks < 2 and planks >= 2 and "stick" in craftable:
                return craft_action(observation, "stick")
            # 做工作台必须留够木镐的材料：
            # 实测 world-ym20nayz 里工作台放下了、nearby_tools 也真了 104 步，
            # 但因为只剩 2 个木板，craftable 里始终没有木镐。
            if tables == 0 and planks >= 7 and sticks >= 2 and "crafting_table" in craftable:
                return craft_action(observation, "crafting_table")

            if self.table_placed:
                # 刚放下工作台时，环境的 craftable 掩码要等观测刷新才更新，
                # 此时若立刻走开就永远等不到（实测放置 1 次却始终无木镐）。
                # 所以先原地站 4 步等刷新，再考虑换位置。
                self.tbl_wait = getattr(self, "tbl_wait", 0) + 1
                if self.tbl_wait <= 4:
                    return self.noop(observation)
                # 60 步还没解锁 -> 判定环境没识别到这张台子，换位置重放
                if self.tbl_wait > 60:
                    self.table_placed = False
                    self.tbl_wait = 0
                    self.relocate = 12
                    self.tries = getattr(self, "tries", 0) + 1
                    self.log("table not detected -> retry #%d at new spot" % self.tries)
                    return self.walk(observation, forward=1)
                self.tbl_steps = getattr(self, "tbl_steps", 0) + 1
                phase = self.tbl_steps % 16
                if phase < 6:
                    return self.walk(observation, forward=1)
                if phase < 9:
                    return self.walk(observation, forward=2)
                if phase < 12:
                    return self.turn(observation, amount=3)
                return self.walk(observation, forward=1)

            # 材料不够 -> 砍树（顺便把木板攒到 9）
            action, _ = self.seek_and_break(observation, LOG_BLOCKS, "wood", up_scan=True)
            return action

        # ===== 备用工作台（便携式）=====
        # 思路（用户建议）：与其挖完矿跑回原工作台，不如多囤 4 个木板
        # 做一个「随身工作台」，到矿区就地放下就地合成，省掉回程。
        if wpick >= 1 and spick == 0 and not getattr(self, "spare_table", False):
            craftable = set(observation.get("craftable") or [])
            # S04：成品 recipe 已可用时优先制作，不让备用台囤料挡路。
            if "stone_pickaxe" in craftable:
                return craft_action(observation, "stone_pickaxe")
            if "furnace" in craftable:
                return craft_action(observation, "furnace")
            # S05：只有背包真实携带 crafting_table 才认为有便携台；
            # 发出 craft 请求本身不代表成功（下一帧由 inventory 确认）。
            deadline = getattr(self, "spare_deadline", None)
            if tables >= 1:
                self.spare_table = True
                self.spare_deadline = None
                self.log("portable table carried (%d) -> continue" % tables)
            elif deadline is not None and self.ticks >= deadline:
                # 跳过是一次性决定：不能清空 deadline（否则下一帧又重置 900 步
                # 重启囤木；stone-v3 实跑因此卡在找树 2600+ 步）。
                self.log("spare table skipped (deadline)")
                self.spare_table = True
                self.spare_deadline = None
            else:
                if deadline is None:
                    self.spare_deadline = self.ticks + 900      # 最多再花 900 步囤料
                if "crafting_table" in craftable and planks >= 4:
                    self.log("craft portable crafting_table")
                    return craft_action(observation, "crafting_table")
                if log_n >= 1 and "planks" in craftable:
                    return craft_action(observation, "planks")
                action, _ = self.seek_and_break(observation, LOG_BLOCKS, "wood",
                                                up_scan=True)
                return action

        # ===== 石器阶段 =====
        # 目标：cobblestone×3 → stone_pickaxe；再 cobblestone×8 → furnace
        # 关键：石头在地下，必须「向下挖」；且挖石头前要手持镐子。
        if spick == 0 or furnace == 0:
            need = 3 if spick == 0 else 8
            pick_name = self._best_pick(counts) or (
                "wooden_pickaxe" if spick == 0 else "stone_pickaxe")
            want = "stone_pickaxe" if spick == 0 else "furnace"
            if cobble >= need:
                if want in craftable:
                    return craft_action(observation, want)
                # P1-02：缺木棍时先用合法配方补木板/棍（只做一个合法步）。
                if want == "stone_pickaxe" and sticks < 2:
                    action = self._material_step(observation, counts, craftable,
                                                 want_sticks=True)
                    if action is not None:
                        return action
                # P1-02/P1-03：需要台子时合法合成/放置并等待公开确认；
                # 历史 table_placed=True 不再被当作“台子可用”。
                action = self._table_step(observation, counts, slots, craftable)
                if action is not None:
                    return action
                if self.table_placed and self._near_table(observation):
                    # 台子真实在旁但 recipe 未刷新：最多等 5 步；之后必须行动。
                    # 有备用台 -> 强制在公开姿势/位置放置（不再无限 noop/dig）；
                    # 没备用台 -> 继续采矿（craftable 仍是唯一配方权威）。
                    self.tbl_steps = getattr(self, "tbl_steps", 0) + 1
                    if self.tbl_steps > 5:
                        self.tbl_steps = 0
                        slot = slots.get("crafting_table")
                        if slot is not None and not self.table_pending:
                            self.table_placed = False
                            self.log("stone recipe missing near table -> force place carried table")
                            return self._send_place(observation, slot,
                                                    "crafting_table (force)")
                        self.log("stone recipe still missing; no carried table -> continue mining")
                        self.dep_fail = 0
                        return self.dig_down(observation)
                    if self.tbl_steps % 2 == 0:
                        return self.noop(observation)
                    return self.turn(observation, amount=1)
                # 没有可用台子也没有合法补料步骤 -> 有界找木头重建；超预算换路线。
                self.dep_fail = getattr(self, "dep_fail", 0) + 1
                if self.dep_fail <= 80:
                    action, _ = self.seek_and_break(observation, LOG_BLOCKS, "wood",
                                                    up_scan=True)
                    return action
                self.log("stone dependencies unavailable -> explore for wood")
                self.dep_fail = 0
                return self.walk_policy(observation)

            # 还没攒够圆石：先装备镐，然后向下挖
            if not equipped.get(pick_name) and slots.get(pick_name) is not None:
                return slot_action(observation, "equip", slots[pick_name])
            # 准星里已经有石头就正常挖，否则开竖井
            if _is_any((hit.get("block_name") or ""), STONE_BLOCKS) and \
               hit.get("block_distance") is not None and hit["block_distance"] <= REACH:
                action, _ = self.seek_and_break(observation, STONE_BLOCKS, "stone", explore=True)
                return action
            return self.dig_down(observation)

        # ===== 铁器阶段 =====
        raw_iron = counts.get("iron_ore", 0)
        ingots = counts.get("iron_ingot", 0)
        if raw_iron + ingots < 3:
            # Smelt any ore that is currently legal before mining more. If the
            # furnace/fuel is not ready, continue mining rather than issuing an
            # invalid repeated smelt request forever.
            if raw_iron and "iron_ingot" in craftable:
                return craft_action(observation, "iron_ingot")
            best_pick = self._best_pick(counts)
            if (best_pick and not equipped.get(best_pick)
                    and slots.get(best_pick) is not None):
                return slot_action(observation, "equip", slots[best_pick])
            if _is_any((hit.get("block_name") or ""), IRON_BLOCKS) and \
               hit.get("block_distance") is not None and hit["block_distance"] <= REACH:
                action, _ = self.seek_and_break(observation, IRON_BLOCKS, "iron_ore", explore=True)
                return action
            return self.dig_down(observation)

        if ingots < 3:
            if "iron_ingot" in craftable:
                return craft_action(observation, "iron_ingot")
            return self.noop(observation)

        if counts.get("iron_pickaxe", 0) < 1:
            if "iron_pickaxe" in craftable:
                return craft_action(observation, "iron_pickaxe")
            return self.noop(observation)

        self.log("IRON PICKAXE!")
        return self.noop(observation)
