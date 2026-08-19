"""Alternative A-share quote sources used when Eastmoney is unavailable."""
from __future__ import annotations

import json
import re
import time
from typing import Any

import main as core

ORIGINAL_COLLECT_QUOTES = core.collect_quotes
WATCHLIST_CODES = [
    "600406", "000400", "600312", "601138", "000938", "300308",
    "603019", "688041", "002371", "688012", "688120", "300124",
    "002050", "600276", "601899", "600690", "000651", "601318",
]


def parse_sina(text: str) -> list[dict[str, Any]]:
    text = text.strip().lstrip("\ufeff")
    try:
        data = json.loads(text)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        fixed = re.sub(r'([,{])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', r'\1"\2":', text)
        fixed = fixed.replace("'", '"')
        data = json.loads(fixed)
        return data if isinstance(data, list) else []


def collect_sina() -> tuple[list[dict[str, Any]], str | None]:
    endpoints = [
        "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
        "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData",
    ]
    errors: list[str] = []
    for endpoint in endpoints:
        try:
            rows: list[dict[str, Any]] = []
            for page in range(1, 76):
                params = {
                    "page": page, "num": 80, "sort": "symbol", "asc": 1,
                    "node": "hs_a", "symbol": "", "_s_r_a": "page",
                }
                raw = core.fetch(core.urlq(endpoint, params), timeout=25, retries=2)
                part = parse_sina(raw.decode("utf-8", errors="replace"))
                if not part:
                    break
                rows.extend(part)
                if len(part) < 80:
                    break
                time.sleep(0.05)
            if len(rows) < 500:
                raise RuntimeError(f"only {len(rows)} rows")
            out = []
            for item in rows:
                symbol = str(item.get("symbol") or "")
                code = re.sub(r"^[A-Za-z]+", "", symbol)
                name = str(item.get("name") or "")
                if not code or not name:
                    continue
                out.append({
                    "code": code,
                    "name": name,
                    "price": core.fnum(item.get("trade")),
                    "change_pct": core.fnum(item.get("changepercent")),
                    "volume": core.fnum(item.get("volume"), 0),
                    "amount": core.fnum(item.get("amount"), 0),
                    "turnover": core.fnum(item.get("turnoverratio")),
                    "pe": core.fnum(item.get("per")),
                    "volume_ratio": None,
                    "market_cap": core.fnum(item.get("mktcap"), 0),
                    "float_cap": core.fnum(item.get("nmc"), 0),
                    "pb": core.fnum(item.get("pb")),
                    "change_60d": None,
                    "change_ytd": None,
                    "net_inflow": None,
                    "source": "新浪财经",
                })
            return out, None
        except Exception as exc:
            errors.append(f"{endpoint}: {exc}")
    return [], "; ".join(errors)


def collect_tencent_watchlist() -> tuple[list[dict[str, Any]], str | None]:
    symbols = [("sh" if code.startswith("6") else "sz") + code for code in WATCHLIST_CODES]
    try:
        raw = core.fetch("https://qt.gtimg.cn/q=" + ",".join(symbols), timeout=25)
        text = raw.decode("gb18030", errors="replace")
        out = []
        for block in text.split(";"):
            if '="' not in block:
                continue
            values = block.split('="', 1)[1].rstrip('"').split("~")
            if len(values) < 33:
                continue
            price, previous = core.fnum(values[3]), core.fnum(values[4])
            change_pct = core.fnum(values[32])
            if change_pct is None and price and previous:
                change_pct = round((price / previous - 1) * 100, 2)
            out.append({
                "code": values[2], "name": values[1], "price": price,
                "change_pct": change_pct, "volume": core.fnum(values[6], 0),
                "amount": None, "turnover": None,
                "pe": core.fnum(values[39]) if len(values) > 39 else None,
                "volume_ratio": None, "market_cap": None, "float_cap": None,
                "pb": core.fnum(values[46]) if len(values) > 46 else None,
                "change_60d": None, "change_ytd": None, "net_inflow": None,
                "source": "腾讯行情",
            })
        return out, None if out else "no rows"
    except Exception as exc:
        return [], str(exc)


def collect_quotes() -> tuple[list[dict[str, Any]], str | None]:
    errors: list[str] = []
    for name, collector in (
        ("Eastmoney", ORIGINAL_COLLECT_QUOTES),
        ("Sina", collect_sina),
        ("Tencent watchlist", collect_tencent_watchlist),
    ):
        rows, error = collector()
        if rows:
            warning = "; ".join(errors) if errors else None
            return rows, warning
        errors.append(f"{name}: {error or 'no rows'}")
    return [], "; ".join(errors)
