from __future__ import annotations
import re
from datetime import datetime
from typing import Dict, Iterable
import requests

TENCENT_URLS = (
    "https://qt.gtimg.cn/q={codes}",
    "http://qt.gtimg.cn/q={codes}",
)

def to_tencent_code(code: str) -> str:
    code = str(code).strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"invalid A-share code: {code}")
    return ("sh" if code.startswith(("5","6","9")) else "sz") + code

def _f(v, default=None):
    try:
        x = float(v)
        return x
    except Exception:
        return default

def parse_tencent_quote_line(line: str):
    line = line.strip()
    m = re.search(r'v_(?:sh|sz)(\d{6})="(.*)"\s*;?$', line)
    if not m:
        raise ValueError("unrecognized Tencent quote line")
    code = m.group(1)
    fields = m.group(2).split("~")
    if len(fields) < 35:
        raise ValueError(f"short Tencent quote for {code}: {len(fields)} fields")
    price = _f(fields[3])
    if price is None or price <= 0:
        raise ValueError(f"invalid latest price for {code}")
    raw_time = fields[30].strip()
    quote_time = raw_time
    market_date = None
    if len(raw_time) >= 14 and raw_time[:14].isdigit():
        dt = datetime.strptime(raw_time[:14], "%Y%m%d%H%M%S")
        quote_time = dt.strftime("%Y-%m-%d %H:%M:%S")
        market_date = dt.strftime("%Y-%m-%d")
    return {
        "code": code,
        "name": fields[1].strip(),
        "price": price,
        "prev_close": _f(fields[4]),
        "open": _f(fields[5]),
        "volume": _f(fields[6]),
        "quote_time": quote_time,
        "market_date": market_date,
        "change": _f(fields[31]),
        "change_pct": _f(fields[32]),
        "high": _f(fields[33]),
        "low": _f(fields[34]),
        "amount_wan": _f(fields[37]) if len(fields) > 37 else None,
        "turnover": _f(fields[38]) if len(fields) > 38 else None,
        "pe_ttm": _f(fields[39]) if len(fields) > 39 else None,
        "pb": _f(fields[48]) if len(fields) > 48 else None,
        "source": "Tencent Finance",
    }

def parse_tencent_quote_text(text: str) -> Dict[str, dict]:
    result = {}
    for line in text.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        # Some responses concatenate entries with ';' instead of line breaks.
        chunks = re.findall(r'v_(?:sh|sz)\d{6}=".*?";', line)
        if not chunks:
            chunks = [line]
        for chunk in chunks:
            try:
                q = parse_tencent_quote_line(chunk)
                result[q["code"]] = q
            except Exception:
                continue
    return result

def fetch_tencent_quotes(codes: Iterable[str], timeout: int = 15) -> Dict[str, dict]:
    api_codes = [to_tencent_code(c) for c in codes]
    joined = ",".join(api_codes)
    last_error = None
    headers = {
        "User-Agent": "Mozilla/5.0 dividend-low-vol-monitor/8.0",
        "Referer": "https://gu.qq.com/",
        "Accept": "*/*",
    }
    for template in TENCENT_URLS:
        try:
            r = requests.get(template.format(codes=joined), headers=headers, timeout=timeout)
            r.raise_for_status()
            r.encoding = "gbk"
            data = parse_tencent_quote_text(r.text)
            if data:
                return data
            last_error = RuntimeError("Tencent response parsed 0 quotes")
        except Exception as e:
            last_error = e
    raise RuntimeError(f"Tencent quote request failed: {last_error!r}")
