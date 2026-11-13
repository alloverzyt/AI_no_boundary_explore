"""离线视觉 v2：HSV 色彩空间 + 垂直连通约束，估计树冠水平方位。

相对 v1 的两处升级：
  1. **RGB → HSV**：把"亮度"与"色相"解耦，雪原（高亮低饱和）、
     沙漠（偏黄）、洞穴（低光照）下都不容易失效；
  2. **垂直连通约束**：树冠是竖直成片的，草地是水平铺开的。
     要求某一列上存在连续 ≥ RUN_MIN 个"树叶色"采样点，
     该列才算"有树"，从而把草地、水面、蘑菇等误检压下去。

仍然满足赛规：纯本地计算、不联网、不读写环境内部数据、无 GPU。
单帧开销约 2–5 ms（640×400，stride=4）。
"""
import base64
import io

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

# HSV 阈值（PIL 的 H/S/V 均为 0..255）
HUE_MIN, HUE_MAX = 55, 115      # 绿色区（约 78°~162°）
SAT_MIN = 70                    # 饱和度下限，排除灰白(雪)与天空
VAL_MIN, VAL_MAX = 35, 175      # 亮度区间，排除全黑洞穴与过曝亮草

RUN_MIN = 5                     # 一列上至少连续的树叶采样点数（stride=4 → 约 20 px）


def _is_leaf(h, s, v):
    return (HUE_MIN <= h <= HUE_MAX) and (s >= SAT_MIN) and (VAL_MIN <= v <= VAL_MAX)


def tree_offset(obs, min_columns=3):
    """返回树冠水平偏移 [-1, +1]；看不到合格树冠返回 None。"""
    if Image is None:
        return None
    b64 = (obs or {}).get("image_jpeg_base64") or ""
    if not b64:
        return None
    try:
        im = Image.open(io.BytesIO(base64.b64decode(b64))).convert("HSV")
    except Exception:
        return None

    W, H = im.size
    hh, ss, vv = im.split()
    Hp, Sp, Vp = hh.load(), ss.load(), vv.load()

    y0, y1 = int(H * 0.08), int(H * 0.58)    # 只看地平线以上
    stride = 4

    columns = []
    for x in range(0, W, stride):
        run = 0
        best_run = 0
        count = 0
        for y in range(y0, y1, stride):
            if _is_leaf(Hp[x, y], Sp[x, y], Vp[x, y]):
                run += 1
                count += 1
                if run > best_run:
                    best_run = run
            else:
                run = 0
        # 垂直连通约束：没有足够长的连续段就不算树
        if best_run >= RUN_MIN:
            columns.append((x, count))

    if len(columns) < min_columns:
        return None
    total = sum(c for _, c in columns)
    if total <= 0:
        return None
    centroid = sum(x * c for x, c in columns) / total
    return (centroid - W / 2.0) / (W / 2.0)


# ---------------------------------------------------------------------------
# 模式 B：RGB 阈值版（v1，实测更稳，作为默认）
# 说明：HSV 版在高饱和草地/雪原上会出现"整行都命中"的误检（实测 stone 场景
#       1500 次触发、offset 恒为 0），因此默认回到 RGB + 列质心。
# ---------------------------------------------------------------------------
def _is_canopy_rgb(r, g, b):
    # 实测（world-uw7yq8tz 首帧）：雪原云杉树叶像素是 (29,36,28)/(3,16,7)，
    # 绿通道只有 16~36，原来要求 g>=40 会把整片森林过滤掉。
    return (12 <= g <= 150) and (g - r >= 4) and (g - b >= 4)


def tree_offset_rgb(obs, min_pixels=40):
    if Image is None:
        return None
    b64 = (obs or {}).get("image_jpeg_base64") or ""
    if not b64:
        return None
    try:
        im = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    except Exception:
        return None
    W, H = im.size
    px = im.load()
    y0, y1 = int(H * 0.08), int(H * 0.55)
    stride = 4
    scores = []
    for x in range(0, W, stride):
        cnt = 0
        for y in range(y0, y1, stride):
            r, g, b = px[x, y]
            if _is_canopy_rgb(r, g, b):
                cnt += 1
        scores.append((x, cnt))
    total = sum(c for _, c in scores)
    if total < min_pixels:
        return None
    # 取"树冠最密"的那一列作为目标方向（而不是质心）：
    # 左右两侧都有树时，质心会落在画面正中央，等于告诉 Agent"直走"。
    peak_x, peak_c = max(scores, key=lambda t: t[1])
    if peak_c <= 0:
        return None
    return (peak_x - W / 2.0) / (W / 2.0)


# 默认模式：'rgb'（已验证）或 'hsv'（新版，雪原/地下理论更好但当前误检偏多）
MODE = "rgb"


def detect_offset(obs):
    """统一入口，供 agent 调用。"""
    return tree_offset_rgb(obs) if MODE == "rgb" else tree_offset(obs)


# ---------------------------------------------------------------------------
# 水面 / 冰面识别（只扫画面下半部，避免与天空混淆）
# ---------------------------------------------------------------------------
def water_offset(obs, min_pixels=30):
    """返回前方水面/冰面的水平偏移 [-1,+1]，看不到返回 None。

    为什么需要：石器场景实测 6000 步里有 700+ 步准星盯着水面，
    而水无法破坏，Agent 只能反复撞进水里。用画面提前发现"正前方是水"。
    """
    if Image is None:
        return None
    b64 = (obs or {}).get("image_jpeg_base64") or ""
    if not b64:
        return None
    try:
        im = Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    except Exception:
        return None
    W, H = im.size
    px = im.load()
    y0, y1 = int(H * 0.55), int(H * 0.95)      # 只看下半部（地面/水面区域）
    stride = 4
    scores = []
    for x in range(0, W, stride):
        cnt = 0
        for y in range(y0, y1, stride):
            r, g, b = px[x, y]
            # 水/冰：蓝明显高于红；冰偏亮、水偏深，都满足 b - r 足够大
            if b > 90 and b - r >= 18 and b - g >= 6:
                cnt += 1
        scores.append((x, cnt))
    total = sum(c for _, c in scores)
    if total < min_pixels:
        return None
    # Use the occupancy centroid rather than the first maximum. A broad,
    # uniform water surface gives every column the same score; max(scores)
    # would incorrectly report x=0 (far left) and bypass centered avoidance.
    centroid = sum(x * count for x, count in scores) / total
    return (centroid - W / 2.0) / (W / 2.0)
