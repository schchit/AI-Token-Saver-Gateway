#!/usr/bin/env python3
"""联网生成 A 股盘前决策，并推送为 GitHub Issue；不连接券商、不自动下单。"""
from __future__ import annotations

import datetime as dt
import html
import json
import math
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TZ = ZoneInfo("Asia/Shanghai")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
PROMPT = ROOT / "prompt.md"
PORTFOLIO = ROOT / "portfolio.json"
LATEST = ROOT / "latest.md"
REPORTS = ROOT / "reports"


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def log(msg: str) -> None:
    print(f"[a-share-daily] {msg}", flush=True)


def fnum(value: Any, digits: int = 2) -> float | None:
    try:
        if value in (None, "", "-", "--"):
            return None
        x = float(value)
        return round(x, digits) if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def fetch(url: str, *, method: str = "GET", payload: dict | None = None,
          headers: dict | None = None, timeout: int = 30, retries: int = 3) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    hdr = {"User-Agent": UA, "Accept": "application/json,text/plain,*/*"}
    if payload is not None:
        hdr["Content-Type"] = "application/json"
    hdr.update(headers or {})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers=hdr, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(attempt + 1)
    raise RuntimeError(f"{url}: {last}")


def fetch_json(url: str, **kwargs: Any) -> Any:
    return json.loads(fetch(url, **kwargs).decode("utf-8"))


def urlq(url: str, params: dict[str, Any]) -> str:
    return url + "?" + urllib.parse.urlencode(params)


def diff_rows(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        return [x for x in data.values() if isinstance(x, dict)]
    return []


def collect_quotes() -> tuple[list[dict], str | None]:
    endpoint = "https://82.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 500, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fid": "f12",
        "fs": "m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23,m:0 t:81 s:2048",
        "fields": "f2,f3,f5,f6,f8,f9,f10,f12,f14,f20,f21,f23,f24,f25,f62"
    }
    try:
        first = fetch_json(urlq(endpoint, params), timeout=25)
        data = (first or {}).get("data") or {}
        rows = diff_rows(data.get("diff"))
        if not rows:
            raise RuntimeError("行情接口没有返回股票")
        total = int(data.get("total") or len(rows))
        pages = min(20, math.ceil(total / len(rows)))
        for pn in range(2, pages + 1):
            p = dict(params); p["pn"] = pn
            part = fetch_json(urlq(endpoint, p), timeout=25)
            rows.extend(diff_rows(((part or {}).get("data") or {}).get("diff")))
            time.sleep(0.1)
        out = []
        for x in rows:
            code, name = str(x.get("f12") or ""), str(x.get("f14") or "")
            if not code or not name:
                continue
            out.append({
                "code": code, "name": name, "price": fnum(x.get("f2")),
                "change_pct": fnum(x.get("f3")), "volume": fnum(x.get("f5"), 0),
                "amount": fnum(x.get("f6"), 0), "turnover": fnum(x.get("f8")),
                "pe": fnum(x.get("f9")), "volume_ratio": fnum(x.get("f10")),
                "market_cap": fnum(x.get("f20"), 0), "float_cap": fnum(x.get("f21"), 0),
                "pb": fnum(x.get("f23")), "change_60d": fnum(x.get("f24")),
                "change_ytd": fnum(x.get("f25")), "net_inflow": fnum(x.get("f62"), 0),
            })
        return out, None
    except Exception as exc:
        return [], str(exc)


def collect_boards() -> tuple[list[dict], str | None]:
    endpoint = "https://17.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 500, "po": 1, "np": 1, "fltt": 2, "invt": 2,
        "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fid": "f3",
        "fs": "m:90 t:2 f:!50", "fields": "f3,f8,f12,f14,f20,f104,f105,f128,f136"
    }
    try:
        data = fetch_json(urlq(endpoint, params), timeout=25)
        rows = diff_rows(((data or {}).get("data") or {}).get("diff"))
        out = [{
            "name": str(x.get("f14") or ""), "code": str(x.get("f12") or ""),
            "change_pct": fnum(x.get("f3")), "turnover": fnum(x.get("f8")),
            "market_cap": fnum(x.get("f20"), 0), "rising": fnum(x.get("f104"), 0),
            "falling": fnum(x.get("f105"), 0), "leader": x.get("f128"),
            "leader_change_pct": fnum(x.get("f136"))
        } for x in rows if x.get("f14")]
        return sorted(out, key=lambda x: x.get("change_pct") or -999, reverse=True), None
    except Exception as exc:
        return [], str(exc)


def collect_announcements() -> tuple[list[dict], str | None]:
    endpoint = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    today = now().date(); begin = today - dt.timedelta(days=2)
    params = {
        "sr": -1, "page_size": 100, "page_index": 1, "ann_type": "A",
        "client_source": "web", "f_node": 0, "s_node": 0,
        "begin_time": begin.isoformat(), "end_time": today.isoformat()
    }
    try:
        out: list[dict] = []
        for page in range(1, 4):
            p = dict(params); p["page_index"] = page
            data = fetch_json(urlq(endpoint, p), timeout=25)
            rows = (((data or {}).get("data") or {}).get("list") or [])
            if not rows:
                break
            for row in rows:
                codes = row.get("codes") or []
                code = next((c for c in codes if str(c.get("ann_type", "")).startswith("A")), codes[0] if codes else {})
                stock_code = str(code.get("stock_code") or "")
                out.append({
                    "code": stock_code, "name": code.get("short_name"),
                    "title": row.get("title"), "date": row.get("notice_date"),
                    "url": f"https://data.eastmoney.com/notices/detail/{stock_code}/{row.get('art_code')}.html"
                })
        return out[:250], None
    except Exception as exc:
        return [], str(exc)


def collect_yahoo() -> tuple[list[dict], str | None]:
    symbols = ["000001.SS", "399001.SZ", "^HSI", "^GSPC", "^IXIC", "^VIX", "CNH=X", "GC=F", "CL=F", "HG=F"]
    out, errors = [], []
    for symbol in symbols:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}?range=5d&interval=1d"
            result = fetch_json(url, timeout=20)["chart"]["result"][0]
            meta = result.get("meta") or {}; quote = (result.get("indicators") or {}).get("quote", [{}])[0]
            closes = [x for x in (quote.get("close") or []) if x is not None]
            last = fnum(meta.get("regularMarketPrice") or (closes[-1] if closes else None))
            prev = fnum(meta.get("chartPreviousClose") or (closes[-2] if len(closes) > 1 else None))
            change = round((last / prev - 1) * 100, 2) if last and prev else None
            out.append({"symbol": symbol, "name": meta.get("shortName") or symbol, "price": last, "change_pct": change})
        except Exception as exc:
            errors.append(f"{symbol}: {exc}")
    return out, "; ".join(errors) or None


def collect_news() -> tuple[list[dict], str | None]:
    queries = [
        "A股 中国 产业 政策 财经 when:1d", "中国 上市公司 业绩 订单 回购 并购 when:1d",
        "人工智能 电网 半导体 机器人 创新药 中国 when:2d", "China markets economy Reuters when:1d"
    ]
    out, errors, seen = [], [], set()
    for query in queries:
        try:
            rss = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
            root = ET.fromstring(fetch(rss, timeout=25))
            for item in root.findall("./channel/item")[:15]:
                title = html.unescape(item.findtext("title") or "").strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                out.append({"title": title, "url": item.findtext("link"), "published": item.findtext("pubDate"), "query": query})
        except Exception as exc:
            errors.append(f"{query}: {exc}")
    return out[:50], "; ".join(errors) or None


def market_summary(stocks: list[dict]) -> dict:
    changes = [x["change_pct"] for x in stocks if x.get("change_pct") is not None]
    valid = [x for x in stocks if x.get("price") is not None and x.get("change_pct") is not None]
    return {
        "stock_count": len(valid), "rising": sum(x["change_pct"] > 0 for x in valid),
        "falling": sum(x["change_pct"] < 0 for x in valid), "flat": sum(x["change_pct"] == 0 for x in valid),
        "limit_up_like": sum(x["change_pct"] >= 9.5 for x in valid), "limit_down_like": sum(x["change_pct"] <= -9.5 for x in valid),
        "median_change_pct": round(statistics.median(changes), 2) if changes else None,
        "total_amount_cny": round(sum((x.get("amount") or 0) for x in valid), 0),
    }


def select_candidates(stocks: list[dict], announcements: list[dict]) -> list[dict]:
    ann_codes = {a.get("code") for a in announcements}
    eligible = []
    for x in stocks:
        price, amount, cap = x.get("price"), x.get("amount"), x.get("market_cap")
        pe, pb, c60 = x.get("pe"), x.get("pb"), x.get("change_60d")
        if not price or price <= 0 or not amount or amount < 8e7 or not cap or cap < 5e9:
            continue
        if "ST" in x["name"].upper() or price * 100 > 10000:
            continue
        valuation = (15 if pe and 0 < pe < 30 else 6 if pe and pe < 60 else 0) + (8 if pb and 0 < pb < 3 else 0)
        quality = min(20, math.log10(max(cap, 1)) * 1.8) + min(15, math.log10(max(amount, 1)) * 1.5)
        trend = 10 if c60 is not None and -15 <= c60 <= 25 else 3
        event = 10 if x["code"] in ann_codes else 0
        score = valuation + quality + trend + event + max(-8, min(8, (x.get("change_pct") or 0)))
        eligible.append({**x, "screen_score": round(score, 2), "recent_announcement": x["code"] in ann_codes})
    return sorted(eligible, key=lambda x: x["screen_score"], reverse=True)[:40]


def gather() -> dict:
    errors = []
    stocks, err = collect_quotes(); errors += [f"A股行情: {err}"] if err else []
    boards, err = collect_boards(); errors += [f"行业板块: {err}"] if err else []
    anns, err = collect_announcements(); errors += [f"公告: {err}"] if err else []
    global_markets, err = collect_yahoo(); errors += [f"全球市场: {err}"] if err else []
    news, err = collect_news(); errors += [f"新闻: {err}"] if err else []
    portfolio = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    return {
        "generated_at": now().isoformat(), "portfolio": portfolio, "market_breadth": market_summary(stocks),
        "industry_leaders": boards[:20], "industry_laggards": boards[-15:], "global_markets": global_markets,
        "recent_announcements": anns, "news": news, "screened_candidates": select_candidates(stocks, anns),
        "data_errors": errors, "universe_size": len(stocks),
        "source_notes": ["东方财富全市场行情与公告", "Yahoo Finance 全球市场", "Google News RSS 新闻聚合"]
    }


SYSTEM = """你是严格、可证伪的中国A股投资决策系统。先判断产业趋势和利润流向，再看公司兑现、估值预期差与群体情绪。不得承诺收益，不得杜撰数据，不得把新闻热度当产业证据。账户只有1万元，A股100股一手，不用杠杆，最多3只股票；市场未确认企稳时现金至少50%。没有明显正期望机会时，唯一正确动作是保持现金。输出中文、可执行、明确证伪条件，并引用数据包中的来源链接；若使用联网搜索，给出可核查来源。"""


def llm_prompt(packet: dict) -> str:
    raw = json.dumps(packet, ensure_ascii=False, indent=2)
    raw = raw[:int(os.getenv("MAX_PACKET_CHARS", "150000"))]
    return PROMPT.read_text(encoding="utf-8") + "\n\n## 本次联网数据包\n```json\n" + raw + "\n```"


def openai_engine(prompt: str) -> tuple[str | None, str | None]:
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return None, "未配置 OPENAI_API_KEY"
    payload = {
        "model": (os.getenv("OPENAI_MODEL") or "gpt-5.6-terra").strip(),
        "reasoning": {"effort": (os.getenv("OPENAI_REASONING_EFFORT") or "high").strip()},
        "tools": [{"type": "web_search"}], "store": False, "max_output_tokens": 9000,
        "input": [{"role": "developer", "content": [{"type": "input_text", "text": SYSTEM}]},
                  {"role": "user", "content": [{"type": "input_text", "text": prompt}]}]
    }
    try:
        data = fetch_json("https://api.openai.com/v1/responses", method="POST", payload=payload,
                          headers={"Authorization": f"Bearer {key}"}, timeout=240, retries=2)
        if isinstance(data.get("output_text"), str) and data["output_text"].strip():
            return data["output_text"].strip(), None
        texts = []
        for item in data.get("output") or []:
            for part in item.get("content") or []:
                if part.get("type") == "output_text" and part.get("text"):
                    texts.append(part["text"])
        return ("\n".join(texts).strip() or None), None
    except Exception as exc:
        return None, str(exc)


def github_models_engine(prompt: str) -> tuple[str | None, str | None]:
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    if not token:
        return None, "没有 GITHUB_TOKEN"
    preferred = [(os.getenv("GITHUB_MODELS_MODEL") or "").strip(), "openai/gpt-5", "openai/gpt-4.1", "openai/gpt-4o"]
    model = next((x for x in preferred if x), "openai/gpt-4.1")
    try:
        catalog = fetch_json("https://models.github.ai/catalog/models", headers={"Authorization": f"Bearer {token}"}, timeout=30, retries=1)
        available = {str(x.get("id")) for x in catalog if isinstance(x, dict)}
        model = next((x for x in preferred if x and x in available), "openai/gpt-4.1")
    except Exception as exc:
        log(f"GitHub Models catalog unavailable: {exc}")
    payload = {"model": model, "temperature": 0.1, "max_tokens": 7000,
               "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    try:
        data = fetch_json("https://models.github.ai/inference/chat/completions", method="POST", payload=payload,
                          headers={"Authorization": f"Bearer {token}"}, timeout=180, retries=2)
        text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content"))
        return (text.strip() if isinstance(text, str) and text.strip() else None), None
    except Exception as exc:
        return None, f"{model}: {exc}"


def fallback(packet: dict, errors: list[str]) -> str:
    b, p = packet.get("market_breadth") or {}, packet.get("portfolio") or {}
    return f"""# A股盘前决策｜{now().date().isoformat()}

**今日账户动作：保持现金**  
**今日最高优先级标的：无**  
**市场状态：自动化降级模式**  
**建议仓位：0%新增仓位**  
**一句话判断：研究链路没有完整运行，纪律要求在证据不足时不下注。**

## 一、市场轮廓
- 股票样本：{b.get('stock_count', '未知')}只
- 上涨／下跌：{b.get('rising', '未知')}／{b.get('falling', '未知')}
- 中位涨跌幅：{b.get('median_change_pct', '未知')}%

## 二、唯一执行指令
**今日不交易，保持现金。**

## 三、账户
- 初始本金：{p.get('initial_capital_cny', 10000)}元
- 现金：{p.get('cash_cny', 10000)}元
- 持仓：{len(p.get('positions') or [])}只

## 四、降级原因
{chr(10).join('- ' + x for x in errors)}
"""


def validate(report: str) -> str:
    report = report.strip()
    if not all(x in report for x in ("今日账户动作", "唯一执行指令", "账户")):
        report = f"# A股盘前决策｜{now().date().isoformat()}\n\n**今日账户动作：保持现金（格式校验未通过）**\n\n" + report
    return report + "\n\n---\n> 自动化公开信息研究；不保证收益，不连接券商，不自动下单。实际成交仅在账户持有人明确执行后成立。\n"


def github_api(path: str, *, method: str = "GET", payload: dict | None = None) -> Any:
    token = (os.getenv("GITHUB_TOKEN") or "").strip()
    return fetch_json("https://api.github.com" + path, method=method, payload=payload,
                      headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=40)


def publish(report: str) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    date = now().date().isoformat()
    (REPORTS / f"{date}.md").write_text(report + "\n", encoding="utf-8")
    LATEST.write_text(report + "\n", encoding="utf-8")
    repo = (os.getenv("GITHUB_REPOSITORY") or "").strip()
    if not repo:
        return
    title = f"A股盘前决策 | {date}"
    issues = github_api(f"/repos/{repo}/issues?state=all&per_page=100")
    existing = next((x for x in issues if x.get("title") == title and "pull_request" not in x), None)
    body = report[:63500] + ("\n\n> 完整版见 latest.md。" if len(report) > 63500 else "")
    payload = {"title": title, "body": body, "assignees": [(os.getenv("REPORT_ASSIGNEE") or repo.split('/')[0]).strip()]}
    if existing:
        github_api(f"/repos/{repo}/issues/{existing['number']}", method="PATCH", payload=payload)
    else:
        github_api(f"/repos/{repo}/issues", method="POST", payload=payload)


def main() -> int:
    packet = gather(); prompt = llm_prompt(packet); errors = []
    report, err = openai_engine(prompt); engine = "OpenAI Responses + Web Search"
    if err:
        errors.append("OpenAI: " + err); report, err = github_models_engine(prompt); engine = "GitHub Models + 联网数据采集"
    if err:
        errors.append("GitHub Models: " + err)
    if not report:
        report, engine = fallback(packet, errors), "安全降级"
    report = validate(report) + f"\n<!-- generation_engine: {engine} -->\n"
    publish(report); log(f"published with {engine}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
