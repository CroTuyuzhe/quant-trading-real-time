#!/usr/bin/env python3
"""
实时买卖信号系统 v2 — 趋势驱动型盘中决策引擎
核心逻辑: 检测当天分钟级趋势方向，提前预判拐点
Data: Sina为主, Tencent/akshare兜底
Usage: python3 rt_signal.py --code 600900 --action buy [--interval 30] [--max-minutes 30]
"""
import argparse
import json
import sys
import time
import traceback
import urllib.request
import re
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict

# ── 常量 ──────────────────────────────────────────────────────
MARKET_OPEN  = (9, 30)
MARKET_CLOSE = (15, 0)
LUNCH_START  = (11, 30)
LUNCH_END    = (13, 0)
SINA_REFERER = "https://finance.sina.com.cn"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# ── 数据结构 ──────────────────────────────────────────────────
@dataclass
class TrendSignals:
    """趋势信号集"""
    price_trend: str = "flat"       # up / down / flat
    trend_strength: float = 0.0     # 趋势强度 0~1
    momentum_dir: str = "neutral"   # accelerating_up / decelerating_up / accelerating_down / decelerating_down / neutral
    ma_alignment: str = "neutral"   # bullish / bearish / neutral / converging
    volume_trend: str = "flat"      # rising / falling / flat
    reversal_hint: str = "none"     # bottoming / topping / none
    breakout_phase: str = "none"    # pre_breakout / confirmed / failed / none
    detail: dict = field(default_factory=dict)

@dataclass
class Decision:
    ts: str
    action: str
    composite: float
    signals: TrendSignals
    price: float
    reasoning: str

# ── 工具函数 ──────────────────────────────────────────────────
def is_trading_time() -> bool:
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    t = (now.hour, now.minute)
    return (MARKET_OPEN <= t < LUNCH_START) or (LUNCH_END <= t < MARKET_CLOSE)

def sina_prefix(code): return "sh" if code.startswith("6") else "sz"

def http_get(url, timeout=10):
    req = urllib.request.Request(url, headers={"Referer": SINA_REFERER, "User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", errors="replace")

def linear_slope(values):
    """最小二乘法线性斜率"""
    n = len(values)
    if n < 2:
        return 0.0
    x_mean = (n - 1) / 2.0
    y_mean = sum(values) / n
    num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
    den = sum((i - x_mean) ** 2 for i in range(n))
    return num / (den + 1e-10)

def ema(data, span):
    mult = 2 / (span + 1)
    result = [data[0]]
    for i in range(1, len(data)):
        result.append(data[i] * mult + result[-1] * (1 - mult))
    return result

# ── 数据获取 ──────────────────────────────────────────────────
def fetch_sina_quote(code):
    prefix = sina_prefix(code)
    raw = http_get(f"https://hq.sinajs.cn/list={prefix}{code}")
    m = re.search(r'"(.+)"', raw)
    if not m: return {}
    f = m.group(1).split(",")
    if len(f) < 32: return {}
    bid, ask = [], []
    for i in range(10, 20, 2):
        try: bid.append({"price": float(f[i+1]), "vol": int(f[i])})
        except: pass
    for i in range(20, 30, 2):
        try: ask.append({"price": float(f[i+1]), "vol": int(f[i])})
        except: pass
    return {"code": code, "name": f[0], "open": float(f[1] or 0), "pre_close": float(f[2] or 0),
            "price": float(f[3] or 0), "high": float(f[4] or 0), "low": float(f[5] or 0),
            "volume": int(f[8] or 0), "amount": float(f[9] or 0), "bid": bid, "ask": ask}

def fetch_tencent_quote(code):
    prefix = sina_prefix(code)
    raw = http_get(f"https://qt.gtimg.cn/q={prefix}{code}")
    m = re.search(r'"(.+)"', raw)
    if not m: return {}
    f = m.group(1).split("~")
    if len(f) < 30: return {}
    bid, ask = [], []
    for i in range(9, 19, 2):
        try: bid.append({"price": float(f[i]), "vol": int(f[i+1]) * 100})
        except: pass
    for i in range(19, 29, 2):
        try: ask.append({"price": float(f[i]), "vol": int(f[i+1]) * 100})
        except: pass
    return {"code": code, "name": f[1], "price": float(f[3] or 0), "pre_close": float(f[4] or 0),
            "open": float(f[5] or 0), "volume": int(f[6] or 0) * 100, "bid": bid, "ask": ask}

def fetch_minute_kline(code, count=120):
    prefix = sina_prefix(code)
    raw = http_get(f"https://quotes.sina.cn/cn/api/jsonp_v2.php/data/CN_MarketDataService.getKLineData?symbol={prefix}{code}&scale=1&ma=no&datalen={count}", timeout=15)
    m = re.search(r'data\((\[.+\])\)', raw)
    if not m: return []
    data = json.loads(m.group(1))
    return [{"time": d["day"], "open": float(d["open"]), "high": float(d["high"]),
             "low": float(d["low"]), "close": float(d["close"]),
             "volume": int(d["volume"]), "amount": float(d["amount"])} for d in data]

def fetch_realtime_quote(code):
    q = fetch_sina_quote(code)
    if not q or not q.get("price"):
        q = fetch_tencent_quote(code)
    if not q or not q.get("price"):
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            row = df[df["代码"] == code]
            if not row.empty:
                r = row.iloc[0]
                q = {"code": code, "name": r.get("名称",""), "price": float(r.get("最新价",0)),
                     "open": float(r.get("今开",0)), "pre_close": float(r.get("昨收",0)),
                     "high": float(r.get("最高",0)), "low": float(r.get("最低",0)),
                     "volume": int(r.get("成交量",0)), "amount": float(r.get("成交额",0)),
                     "bid": [], "ask": []}
        except: pass
    return q

# ══════════════════════════════════════════════════════════════
# 趋势分析核心 — 全部基于当天分钟数据
# ══════════════════════════════════════════════════════════════

def analyze_price_trend(closes, window_short=5, window_long=15):
    """
    分析价格趋势方向和强度
    返回: (direction, strength)
    direction: up / down / flat
    strength: 0~1
    """
    if len(closes) < window_long:
        return "flat", 0.0

    # 短期斜率 vs 长期斜率
    slope_short = linear_slope(closes[-window_short:])
    slope_long = linear_slope(closes[-window_long:])

    # 斜率标准化（相对于价格的百分比）
    avg_price = sum(closes[-window_long:]) / window_long
    rel_slope_short = slope_short / (avg_price + 0.001) * 100  # 每分钟变化%
    rel_slope_long = slope_long / (avg_price + 0.001) * 100

    # 方向
    if rel_slope_short > 0.01 and rel_slope_long > 0:
        direction = "up"
    elif rel_slope_short < -0.01 and rel_slope_long < 0:
        direction = "down"
    else:
        direction = "flat"

    # 强度 = 短期斜率的绝对值（归一化到0~1）
    # 每分钟0.1%算强，0.5%算非常强
    strength = min(abs(rel_slope_short) / 0.5, 1.0)

    return direction, round(strength, 3)


def analyze_momentum(closes):
    """
    分析动量状态 — 加速/减速是趋势拐点的前兆
    返回: momentum_dir
    accelerating_up: 上涨加速 → buy好时机
    decelerating_up: 上涨减速 → 可能见顶，sell机会
    accelerating_down: 下跌加速 → sell好时机/sell要快
    decelerating_down: 下跌减速 → 可能见底，buy机会
    """
    if len(closes) < 15:
        return "neutral"

    # 分三段看速度变化
    s1 = linear_slope(closes[-15:-10])  # 早期
    s2 = linear_slope(closes[-10:-5])   # 中期
    s3 = linear_slope(closes[-5:])      # 近期

    # 加速度 = s3 - s2, 以及 s2 - s1
    accel_recent = s3 - s2
    accel_early = s2 - s1

    avg = sum(closes[-15:]) / 15
    rel_s3 = s3 / (avg + 0.001) * 100
    rel_accel = accel_recent / (avg + 0.001) * 100

    if s3 > 0 and accel_recent > 0 and rel_accel > 0.005:
        return "accelerating_up"
    elif s3 > 0 and accel_recent <= 0:
        return "decelerating_up"
    elif s3 < 0 and accel_recent < 0 and rel_accel < -0.005:
        return "accelerating_down"
    elif s3 < 0 and accel_recent >= 0:
        return "decelerating_down"
    else:
        return "neutral"


def analyze_ma_alignment(closes):
    """
    均线排列趋势 — 当天MA5和MA20的关系变化
    多头排列形成中 → 上升趋势确认
    多头排列瓦解 → 趋势反转预警
    """
    if len(closes) < 20:
        return "neutral", {}

    ma5_now = sum(closes[-5:]) / 5
    ma20_now = sum(closes[-20:]) / 20
    diff_now = ma5_now - ma20_now

    # 5分钟前的状态
    if len(closes) >= 25:
        ma5_prev = sum(closes[-25:-20]) / 5
        ma20_prev = sum(closes[-20:]) / 20
        diff_prev = ma5_prev - ma20_prev
    else:
        diff_prev = diff_now

    spread_change = diff_now - diff_prev  # 差值在扩大还是缩小

    if diff_now > 0 and spread_change > 0:
        return "bullish", {"状态": "多头排列强化", "MA5-MA20": f"{diff_now:.3f}"}
    elif diff_now > 0 and spread_change < 0:
        return "converging", {"状态": "多头排列收窄⚠️", "MA5-MA20": f"{diff_now:.3f}"}
    elif diff_now < 0 and spread_change < 0:
        return "bearish", {"状态": "空头排列强化", "MA5-MA20": f"{diff_now:.3f}"}
    elif diff_now < 0 and spread_change > 0:
        return "converging", {"状态": "空头排列收窄🔄", "MA5-MA20": f"{diff_now:.3f}"}
    else:
        return "neutral", {}


def analyze_volume_trend(vols, window=10):
    """
    量能趋势 — 放量配合趋势方向才可靠
    """
    if len(vols) < window:
        return "flat", 0.0

    recent = vols[-window:]
    slope = linear_slope(recent)
    avg = sum(recent) / len(recent)
    rel_slope = slope / (avg + 1) * 100

    if rel_slope > 2:
        return "rising", round(rel_slope, 2)
    elif rel_slope < -2:
        return "falling", round(rel_slope, 2)
    else:
        return "flat", round(rel_slope, 2)


def detect_reversal(closes, vols):
    """
    检测趋势反转信号（底/顶的形成）
    底部信号: 连续下跌后出现下影线 + 缩量 → 放量
    顶部信号: 连续上涨后出现上影线 + 放量滞涨
    """
    if len(closes) < 10:
        return "none", {}

    recent_trend = linear_slope(closes[-10:])
    avg = sum(closes[-10:]) / 10

    detail = {}

    # 底部探测: 下跌趋势 + 最近2根有下影线 + 量开始回升
    if recent_trend < 0:
        if len(closes) >= 3:
            # 最近一根有长下影（低点偏离close较大）
            last_close = closes[-1]
            last_low = min(closes[-3:])  # 近似
            lower_shadow = (last_close - last_low) / (last_close + 0.001) * 100

            vol_recent = vols[-3:] if len(vols) >= 3 else vols
            vol_prev = vols[-10:-3] if len(vols) >= 10 else vols
            vol_avg_prev = sum(vol_prev) / (len(vol_prev) + 1)
            vol_increasing = vol_recent[-1] > vol_avg_prev * 1.2 if vol_recent else False

            # 下跌减速 + 量能回升 = 底部信号
            slope_recent = linear_slope(closes[-3:])
            slope_prev = linear_slope(closes[-10:-3])
            decelerating = slope_recent > slope_prev  # 下跌变缓

            if decelerating and vol_increasing:
                detail["信号"] = "下跌减速+量能回升，可能见底"
                return "bottoming", detail

    # 顶部探测: 上涨趋势 + 最近滞涨 + 放量
    if recent_trend > 0:
        if len(closes) >= 3:
            slope_recent = linear_slope(closes[-3:])
            slope_prev = linear_slope(closes[-10:-3])

            vol_recent = vols[-3:] if len(vols) >= 3 else vols
            vol_prev = vols[-10:-3] if len(vols) >= 10 else vols
            vol_avg_prev = sum(vol_prev) / (len(vol_prev) + 1)
            vol_spike = vol_recent[-1] > vol_avg_prev * 1.5 if vol_recent else False

            # 上涨减速 + 放量 = 顶部信号
            decelerating = slope_recent < slope_prev * 0.5
            if decelerating and vol_spike:
                detail["信号"] = "上涨减速+异常放量，可能见顶"
                return "topping", detail

    return "none", detail


def detect_breakout_phase(closes, highs, vols):
    """
    突破阶段识别
    pre_breakout: 价格逼近前高 + 蓄势(缩量整理) → buy好时机
    confirmed: 放量突破前高 → 趋势确认
    failed: 突破后回落 → 趋势失败
    """
    if len(closes) < 20:
        return "none", {}

    recent_high = max(highs[-20:-1])  # 不含当前
    current = closes[-1]
    avg_vol = sum(vols[-20:]) / 20
    current_vol = vols[-1] if vols else 0

    detail = {}
    threshold = recent_high * 0.995  # 距前高0.5%以内

    # 之前突破过但现在回落了 → failed
    if len(closes) >= 5:
        max_recent5 = max(closes[-5:])
        if max_recent5 > recent_high and current < recent_high * 0.99:
            detail["状态"] = f"突破{recent_high:.2f}后回落"
            return "failed", detail

    if current >= recent_high and current_vol > avg_vol * 1.3:
        detail["状态"] = f"放量突破{recent_high:.2f}"
        return "confirmed", detail
    elif current >= threshold and current_vol < avg_vol * 0.8:
        detail["状态"] = f"逼近前高{recent_high:.2f}，缩量蓄势"
        return "pre_breakout", detail
    elif current >= threshold:
        detail["状态"] = f"接近前高{recent_high:.2f}"
        return "pre_breakout", detail

    return "none", detail


def analyze_bid_ask_trend(quote):
    """
    盘口压力/支撑判断
    """
    bid = quote.get("bid", [])
    ask = quote.get("ask", [])
    if not bid or not ask:
        return "neutral", {}

    total_bid = sum(b["vol"] for b in bid)
    total_ask = sum(a["vol"] for a in ask)
    ratio = total_bid / (total_ask + 1)

    detail = {"买卖比": f"{ratio:.2f}"}

    if ratio > 1.5:
        return "supportive", detail  # 买盘支撑强
    elif ratio < 0.7:
        return "resistive", detail   # 卖盘压力大
    else:
        return "neutral", detail


# ══════════════════════════════════════════════════════════════
# 趋势→决策映射
# ══════════════════════════════════════════════════════════════

def decide_from_signals(signals: TrendSignals, action: str) -> tuple:
    """
    核心决策逻辑：
    
    BUY 策略 — 寻找上升趋势形成前的入场点:
      🟢买入条件（满足任一组合）:
        1. 价格趋势up + 动量加速 → 强买入
        2. 下跌减速(见底) + 量能回升 → 买入(抄底)
        3. 蓄势突破前高 + 均线多头 → 买入(追突破)
        4. 均线多头排列强化 + 量能配合 → 买入
      ⏳等待条件:
        - 价格趋势down且动量加速下跌 → 还在跌，等
        - 见顶信号 → 等回调
        - 突破失败 → 等重新蓄势

    SELL 策略 — 寻找下跌趋势形成前的出场点:
      🔴卖出条件（满足任一组合）:
        1. 价格趋势down + 动量加速下跌 → 强卖出
        2. 见顶信号(上涨减速+放量) → 卖出
        3. 多头排列瓦解 + 量能异常 → 卖出
        4. 突破失败 + 卖压大 → 卖出
      ⏳等待条件:
        - 价格趋势up且动量加速 → 还在涨，等更好的卖点
        - 蓄势突破 → 等突破结果
    """
    s = signals
    score = 0.5
    reasons = []

    if action == "buy":
        # ===== 上升趋势信号 → 买入 =====
        # 强买入: 价格趋势上升 + 动量加速
        if s.price_trend == "up" and s.momentum_dir == "accelerating_up":
            score += 0.30
            reasons.append("📈上升趋势加速形成")

        # 中等买入: 价格趋势上升 + 量能配合
        elif s.price_trend == "up" and s.volume_trend == "rising":
            score += 0.22
            reasons.append("📈上升趋势+量能配合")

        # 中等买入: 价格趋势上升（即使量未跟上）
        elif s.price_trend == "up":
            score += 0.15
            reasons.append("📈价格趋势向上")

        # 抄底信号: 下跌减速 + 见底迹象（弱信号，减半）
        if s.momentum_dir == "decelerating_down":
            score += 0.08
            reasons.append("🔄下跌减速，趋势可能反转")
        if s.reversal_hint == "bottoming":
            score += 0.18
            reasons.append("🔃见底信号")

        # 突破信号（pre_breakout 为弱信号，减半）
        if s.breakout_phase == "pre_breakout":
            score += 0.06
            reasons.append("⚡蓄势待突破")
        elif s.breakout_phase == "confirmed":
            score += 0.20
            reasons.append("🚀突破确认")

        # 均线支持
        if s.ma_alignment == "bullish":
            score += 0.12
            reasons.append("📊多头排列强化")
        elif s.ma_alignment == "converging" and s.price_trend == "up":
            score += 0.05
            reasons.append("📊空头收窄中")

        # 盘口支撑
        # (已在signals里体现)

        # ===== 下跌趋势信号 → 等待 =====
        if s.price_trend == "down" and s.momentum_dir == "accelerating_down":
            score -= 0.30
            reasons.append("⛔下跌加速，不宜买入")
        elif s.price_trend == "down" and s.volume_trend == "rising":
            score -= 0.20
            reasons.append("⛔放量下跌")
        elif s.price_trend == "down":
            score -= 0.15
            reasons.append("⛔价格趋势向下")

        if s.reversal_hint == "topping":
            score -= 0.15
            reasons.append("⛔见顶信号")
        if s.breakout_phase == "failed":
            score -= 0.15
            reasons.append("⛔突破失败")
        if s.ma_alignment == "bearish":
            score -= 0.10
            reasons.append("⛔空头排列")

    else:  # sell
        # ===== 下跌趋势信号 → 卖出 =====
        if s.price_trend == "down" and s.momentum_dir == "accelerating_down":
            score += 0.30
            reasons.append("📉下跌趋势加速，尽快卖出")
        elif s.price_trend == "down" and s.volume_trend == "rising":
            score += 0.22
            reasons.append("📉放量下跌，加速出逃")
        elif s.price_trend == "down":
            score += 0.15
            reasons.append("📉价格趋势向下")

        # 见顶信号 → 卖出
        if s.reversal_hint == "topping":
            score += 0.20
            reasons.append("🔃见顶信号，卖出")
        if s.momentum_dir == "decelerating_up":
            score += 0.08
            reasons.append("🔄上涨减速，可能见顶")

        # 均线瓦解
        if s.ma_alignment == "converging" and s.price_trend == "down":
            score += 0.10
            reasons.append("📊多头排列瓦解")
        elif s.ma_alignment == "bearish":
            score += 0.12
            reasons.append("📊空头排列形成")

        # 突破失败 → 卖出
        if s.breakout_phase == "failed":
            score += 0.15
            reasons.append("⛔突破失败，回撤中")

        # ===== 上升趋势信号 → 等待 =====
        if s.price_trend == "up" and s.momentum_dir == "accelerating_up":
            score -= 0.25
            reasons.append("📈上升趋势加速，不宜卖出")
        elif s.price_trend == "up" and s.volume_trend == "rising":
            score -= 0.18
            reasons.append("📈放量上涨，等待更好卖点")
        elif s.price_trend == "up":
            score -= 0.12
            reasons.append("📈价格趋势向上")

        if s.reversal_hint == "bottoming":
            score -= 0.12
            reasons.append("🔃见底信号，可能反弹")
        if s.breakout_phase in ("pre_breakout", "confirmed"):
            score -= 0.10
            reasons.append("⚡突破阶段，不宜卖出")
        if s.ma_alignment == "bullish":
            score -= 0.08
            reasons.append("📊多头排列")

    score = round(min(max(score, 0), 1), 3)

    # 决策（收紧阈值 + 涨跌幅过滤）
    # 涨跌幅门槛：从 detail 中提取趋势强度
    trend_str = s.trend_strength if s.trend_strength else 0
    MIN_TREND_STRENGTH = 0.003  # 近20分钟涨跌幅需 > 0.3%

    if action == "buy":
        if score >= 0.78:
            return score, "🟢买入！", reasons
        elif score >= 0.70:
            # 需要至少2个正向趋势信号 + 涨幅过滤
            positive_signals = [r for r in reasons if "📈" in r or "🔄" in r or "🔃" in r or "⚡" in r or "🚀" in r or "📊多头" in r]
            if len(positive_signals) >= 2 and trend_str >= MIN_TREND_STRENGTH:
                return score, "🟢买入！", reasons
        return score, "⏳等待", reasons
    else:
        if score >= 0.78:
            return score, "🔴卖出！", reasons
        elif score >= 0.70:
            negative_signals = [r for r in reasons if "📉" in r or "🔃" in r or "⛔突破" in r or "📊空头" in r or "📊多头排列瓦解" in r]
            if len(negative_signals) >= 2 and trend_str >= MIN_TREND_STRENGTH:
                return score, "🔴卖出！", reasons
        return score, "⏳等待", reasons


# ── 主分析入口 ────────────────────────────────────────────────
def analyze(code: str, action: str) -> Decision:
    """单次完整分析"""
    quote = fetch_realtime_quote(code)
    kline = fetch_minute_kline(code, count=120)

    closes = [k["close"] for k in kline]
    highs = [k["high"] for k in kline]
    vols = [k["volume"] for k in kline]

    # 6大趋势分析
    price_dir, price_strength = analyze_price_trend(closes)
    momentum = analyze_momentum(closes)
    ma_align, ma_detail = analyze_ma_alignment(closes)
    vol_trend, vol_slope = analyze_volume_trend(vols)
    reversal, rev_detail = detect_reversal(closes, vols)
    breakout, bk_detail = detect_breakout_phase(closes, highs, vols)
    pressure, press_detail = analyze_bid_ask_trend(quote)

    signals = TrendSignals(
        price_trend=price_dir,
        trend_strength=price_strength,
        momentum_dir=momentum,
        ma_alignment=ma_align,
        volume_trend=vol_trend,
        reversal_hint=reversal,
        breakout_phase=breakout,
        detail={
            "价格趋势": f"{price_dir}(强度{price_strength})",
            "动量": momentum,
            "均线": {**ma_detail},
            "量能": f"{vol_trend}(斜率{vol_slope})",
            "反转": {**rev_detail},
            "突破": {**bk_detail},
            "盘口": {**press_detail},
        }
    )

    score, decision_text, reasons = decide_from_signals(signals, action)

    now = datetime.now().strftime("%H:%M:%S")
    price = quote.get("price", 0)
    reasoning = " → ".join(reasons[:4]) if reasons else "数据不足"

    return Decision(
        ts=now, action=decision_text, composite=score,
        signals=signals, price=price, reasoning=reasoning,
    )


# ── 循环入口 ──────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="实时趋势买卖信号")
    parser.add_argument("--code", required=True)
    parser.add_argument("--action", required=True, choices=["buy", "sell"])
    parser.add_argument("--interval", type=int, default=30)
    parser.add_argument("--max-minutes", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    action_cn = "买入" if args.action == "buy" else "卖出"
    print(f"\n{'='*60}")
    print(f"📊 趋势驱动买卖信号 | {args.code} {action_cn}")
    print(f"   轮询: 每{args.interval}s | 超时: {args.max_minutes}min")
    print(f"{'='*60}\n")

    if args.once:
        d = analyze(args.code, args.action)
        print(json.dumps(asdict(d), ensure_ascii=False, indent=2))
        return

    start = datetime.now()
    iteration = 0

    while True:
        iteration += 1
        if datetime.now() - start > timedelta(minutes=args.max_minutes):
            print(f"\n⏰ 超时({args.max_minutes}min)，当天未出现明确趋势信号，建议观望")
            print("__DONE__")
            break

        if not is_trading_time():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⏸️ 非交易时间")
            time.sleep(60)
            continue

        try:
            d = analyze(args.code, args.action)
            print(f"[{d.ts}] #{iteration} {d.action}  综合:{d.composite:.3f}  ¥{d.price}")
            print(f"        └─ {d.reasoning}")

            if "🟢" in d.action or "🔴" in d.action:
                print(f"\n{'='*60}")
                print(f"🎯 信号触发: {d.action}")
                print(f"   综合分: {d.composite:.3f}")
                print(f"   当前价: {d.price}")
                print(f"   推理链: {d.reasoning}")
                print(f"{'='*60}")
                print(f"\n__SIGNAL__:{json.dumps(asdict(d), ensure_ascii=False)}")
                print("__DONE__")
                break

        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ {e}")
            traceback.print_exc()

        time.sleep(args.interval)


if __name__ == "__main__":
    main()
