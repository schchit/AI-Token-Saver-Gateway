"""Deterministic, auditable fallback decision engine for the daily report."""
from __future__ import annotations

import json
import math
from typing import Any

import main as core

WATCHLIST = {
    "600406": ("国电南瑞", "新型电网与电力控制"),
    "000400": ("许继电气", "新型电网与特高压"),
    "600312": ("平高电气", "新型电网与特高压"),
    "601138": ("工业富联", "AI服务器与算力基础设施"),
    "000938": ("紫光股份", "AI网络与算力基础设施"),
    "300308": ("中际旭创", "AI光连接"),
    "603019": ("中科曙光", "算力基础设施"),
    "688041": ("海光信息", "国产算力芯片"),
    "002371": ("北方华创", "半导体设备国产化"),
    "688012": ("中微公司", "半导体设备国产化"),
    "688120": ("华海清科", "半导体设备国产化"),
    "300124": ("汇川技术", "工业自动化与机器人"),
    "002050": ("三花智控", "机器人与热管理"),
    "600276": ("恒瑞医药", "创新药与国际化"),
    "601899": ("紫金矿业", "铜金资源约束"),
    "600690": ("海尔智家", "中国制造全球份额"),
    "000651": ("格力电器", "现金流与股东回报"),
    "601318": ("中国平安", "保险修复与资产重估"),
}

THEMES = [
    ("新型电网与算力电力基础设施", 94, ["电网", "特高压", "输变电", "电力设备", "算电协同"]),
    ("AI服务器、网络、光连接、液冷与供电", 92, ["人工智能", "AI服务器", "算力", "光模块", "液冷", "数据中心"]),
    ("半导体设备与材料国产化", 89, ["半导体", "集成电路", "晶圆", "光刻", "刻蚀", "薄膜"]),
    ("工业机器人、自动化与控制", 86, ["机器人", "自动化", "工业控制", "减速器", "伺服"]),
    ("创新药与国际化兑现", 83, ["创新药", "临床", "FDA", "授权", "医药"]),
    ("铜金等资源约束", 79, ["铜", "黄金", "有色", "矿业"]),
    ("中国制造全球份额", 75, ["出口", "海外", "全球化", "家电", "轮胎"]),
    ("保险、资产重估与股东回报", 70, ["保险", "回购", "分红", "资产重估"]),
]


def select_candidates(stocks: list[dict], announcements: list[dict]) -> list[dict]:
    announcement_codes = {item.get("code") for item in announcements}
    eligible = []
    for stock in stocks:
        price = stock.get("price")
        if not price or price <= 0 or "ST" in stock["name"].upper() or price * 100 > 10000:
            continue
        amount = stock.get("amount")
        if amount is not None and amount < 5e7 and stock["code"] not in WATCHLIST:
            continue
        pe, pb, change_60d = stock.get("pe"), stock.get("pb"), stock.get("change_60d")
        valuation = (18 if pe and 0 < pe < 25 else 9 if pe and pe < 50 else 2)
        valuation += 9 if pb and 0 < pb < 3 else 2
        liquidity = min(18, math.log10(max(amount or 1e8, 1)) * 1.4)
        scale = min(15, math.log10(max(stock.get("market_cap") or 1e10, 1)) * 1.2)
        trend = 9 if change_60d is None or -18 <= change_60d <= 28 else 2
        event = 9 if stock["code"] in announcement_codes else 0
        strategic = 18 if stock["code"] in WATCHLIST else 0
        lot_cost = round(price * 100, 2)
        affordability = 8 if lot_cost <= 3500 else 2 if lot_cost <= 5000 else -8
        score = valuation + liquidity + scale + trend + event + strategic + affordability
        score += max(-6, min(6, stock.get("change_pct") or 0))
        theme = WATCHLIST.get(stock["code"], (stock["name"], "全市场估值／事件候选"))[1]
        eligible.append({
            **stock, "theme": theme, "lot_cost_cny": lot_cost,
            "screen_score": round(score, 2),
            "recent_announcement": stock["code"] in announcement_codes,
        })
    return sorted(eligible, key=lambda item: item["screen_score"], reverse=True)[:40]


def theme_ranking(packet: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = json.dumps({
        "news": packet.get("news"),
        "announcements": packet.get("recent_announcements"),
    }, ensure_ascii=False)
    boards = packet.get("industry_leaders") or []
    ranked = []
    for name, base, keywords in THEMES:
        hits = sum(evidence.count(keyword) for keyword in keywords)
        matches = [b for b in boards if any(k in str(b.get("name")) for k in keywords)]
        board_signal = max([b.get("change_pct") or 0 for b in matches] or [0])
        score = base + min(hits, 5) + max(-4, min(4, board_signal))
        crowding = "高" if board_signal >= 3 else "中" if board_signal >= 0 else "低"
        ranked.append({
            "name": name, "score": round(score, 1), "news_hits": hits,
            "board_signal": round(board_signal, 2), "crowding": crowding,
        })
    return sorted(ranked, key=lambda item: item["score"], reverse=True)


def market_state(breadth: dict[str, Any]) -> str:
    total = breadth.get("stock_count") or 0
    rising, falling = breadth.get("rising") or 0, breadth.get("falling") or 0
    median = breadth.get("median_change_pct")
    if total < 1000:
        return "数据不足"
    if falling / max(total, 1) >= 0.75 or (median is not None and median <= -1.5):
        return "恐慌"
    if rising / max(total, 1) >= 0.65 and (median or 0) >= 0.8:
        return "趋势"
    if rising >= falling:
        return "修复"
    return "混合偏弱"


def rule_engine(packet: dict[str, Any]) -> str:
    breadth = packet.get("market_breadth") or {}
    portfolio = packet.get("portfolio") or {}
    total = breadth.get("stock_count") or 0
    rising, falling = breadth.get("rising") or 0, breadth.get("falling") or 0
    median = breadth.get("median_change_pct")
    state = market_state(breadth)
    candidates = packet.get("screened_candidates") or []
    themes = theme_ranking(packet)
    top = candidates[0] if candidates else None
    positions = portfolio.get("positions") or []
    buy_ok = bool(
        top and total >= 1000 and state in ("修复", "趋势") and not positions
        and top.get("lot_cost_cny", 99999) <= 2500
        and -3 <= (top.get("change_pct") or 0) <= 2.5
        and top.get("screen_score", 0) >= 70
    )
    action = "买入" if buy_ok else ("继续持有" if positions else "保持现金")
    target = f"{top['code']} {top['name']}" if buy_ok and top else "无"
    suggested_position = "25%以内" if buy_ok else ("按现有持仓" if positions else "0%")

    news_lines = []
    for item in (packet.get("news") or [])[:6]:
        title, url = str(item.get("title") or ""), str(item.get("url") or "")
        if title:
            news_lines.append(f"- [{title}]({url})" if url else f"- {title}")
    if not news_lines:
        news_lines = ["- 新闻聚合源未返回足够信息，本项降级。"]

    theme_lines = [
        f"{index}. **{item['name']}**：确定性评分 {item['score']}；新闻/公告命中 {item['news_hits']}；"
        f"板块信号 {item['board_signal']}%；拥挤度 {item['crowding']}。"
        for index, item in enumerate(themes[:5], 1)
    ]
    candidate_lines = []
    for index, candidate in enumerate(candidates[:5], 1):
        conclusion = "条件买入候选" if buy_ok and index == 1 else "等待更多经营与价格证据"
        candidate_lines.append(
            f"{index}. **{candidate['code']} {candidate['name']}**｜{candidate.get('theme')}｜"
            f"100股约 {candidate.get('lot_cost_cny')} 元｜PE {candidate.get('pe')}／PB {candidate.get('pb')}｜"
            f"上一交易日 {candidate.get('change_pct')}%｜筛选分 {candidate.get('screen_score')}｜{conclusion}。"
        )
    if not candidate_lines:
        candidate_lines = ["1. 数据不足，不生成个股候选。"]

    if buy_ok and top:
        low, high = round(top["price"] * 0.985, 2), round(top["price"] * 1.005, 2)
        instruction = (
            f"**候选买入 {top['code']} {top['name']} 100股，条件价格 {low}—{high} 元。** "
            "仅在开盘30分钟后指数不再创新低、全市场上涨家数明显改善且目标股未放量冲高时执行；"
            "任一条件不满足则取消。买入后下跌8%重新验证，基本面失效直接退出。"
        )
    elif positions:
        instruction = "**今日不新增仓位，继续持有已确认持仓；只有基本面失效或风险阈值触发才卖出。**"
    else:
        instruction = "**今日不交易，保持现金。**"

    errors = packet.get("data_errors") or []
    data_status = "\n".join(f"- {error}" for error in errors) if errors else "- 主要公开数据源均返回结果。"
    initial = portfolio.get("initial_capital_cny", 10000)
    cash = portfolio.get("cash_cny", 10000)
    return f"""# A股盘前决策｜{core.now().date().isoformat()}

**今日账户动作：{action}**  
**今日最高优先级标的：{target}**  
**市场状态：{state}**  
**建议总仓位：{suggested_position}**  
**一句话判断：先用产业确定性过滤方向，再用上一交易日广度、估值和100股账户约束决定是否下注；没有完整证据就保留现金。**

## 一、过去24小时真正改变定价的信息
{chr(10).join(news_lines)}

## 二、产业增长结构排名
{chr(10).join(theme_lines)}

## 三、全市场候选排名
{chr(10).join(candidate_lines)}

## 四、唯一执行指令
{instruction}

## 五、当前账户账本
- 初始本金：{initial}元
- 现金：{cash}元
- 已确认持仓：{len(positions)}只
- 已实现盈亏：{portfolio.get('realized_pnl_cny', 0)}元
- 账户风险上限：最大回撤15%；最多3只股票；不用杠杆

## 六、什么事实会证明今天判断错误
1. 目标产业的订单、价格或资本开支没有继续增长，且上市公司收入与现金流未兑现。
2. 市场广度继续恶化，上一交易日的相对强势标的转为放量破位。
3. 候选公司公告出现利润质量、应收、负债、治理或减持方面的重大反证。

## 七、数据完整性与来源
- 全市场样本：{total}只；上涨/下跌：{rising}/{falling}；中位涨跌幅：{median}%
- 数据源：东方财富／新浪／腾讯行情（按可用性降级）、上市公司公告、Yahoo Finance、Google News RSS
{data_status}
"""
