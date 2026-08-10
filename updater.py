# -*- coding: utf-8 -*-
import json, time, requests
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import akshare as ak

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "data.json"
CACHE = ROOT / "history_cache.json"
DIVCACHE = ROOT / "dividend_cache.json"
INDEX = "H30269"
TZ = ZoneInfo("Asia/Shanghai")

S = requests.Session()
S.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.qq.com/"
})

def clamp(x, a, b):
    return max(a, min(b, x))

def retry(fn, n=4):
    last = None
    for i in range(n):
        try:
            return fn()
        except Exception as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last

# ---------- 评分 ----------
def position_score(m):
    annual = m["annual"]
    a = 95 if -12 <= annual <= -5 else \
        80 if -5 < annual <= 3 else \
        60 if 3 < annual <= 10 else \
        35 if 10 < annual <= 20 else \
        15 if annual > 20 else \
        72 if annual >= -22 else 45

    dd = m["dd"]
    d = 90 if 6 <= dd <= 18 else \
        clamp(50 + dd * 6, 50, 90) if dd < 6 else \
        clamp(90 - (dd - 18) * 3.5, 25, 90)

    mom = m["mom"]
    mo = 80 + mom if 0 <= mom <= 12 else \
        clamp(75 + mom * 3, 20, 75) if mom < 0 else \
        clamp(92 - (mom - 12) * 2.5, 30, 92)

    v = clamp(105 - m["vol"] * 3.5, 20, 100)
    return round(a * .35 + d * .25 + mo * .20 + v * .20)

def dividend_score(y):
    if y is None:
        return None
    if y >= 6: return 95
    if y >= 5: return 85
    if y >= 4: return 75
    if y >= 3: return 60
    if y >= 2: return 45
    return 25

def combined_score(pos, div_yield):
    ds = dividend_score(div_yield)
    # 股息率数据正常时：位置75% + 股息率25%
    # 若股息率暂时取不到，不造假，回退到位置评分
    return round(pos * .75 + ds * .25) if ds is not None else pos

def advice(score):
    if score >= 80: return "强烈买入"
    if score >= 65: return "建议买入"
    if score >= 45: return "持有 / 观察"
    if score >= 30: return "建议减仓"
    return "建议卖出 / 回避"

def metrics(c, h, latest):
    c = np.array(c, float)
    h = np.array(h, float)
    if len(c) < 250:
        raise ValueError("history<250")

    ma = float(np.mean(np.r_[c[-249:], latest]))
    annual = (latest / ma - 1) * 100
    dd = (1 - latest / max(float(np.max(h[-249:])), latest)) * 100
    mom = (latest / float(c[-60]) - 1) * 100
    recent = np.r_[c[-20:], latest]
    ret = recent[1:] / recent[:-1] - 1
    vol = float(np.std(ret, ddof=1) * np.sqrt(252) * 100)

    return {
        "close": float(latest),
        "ma250": ma,
        "annual": annual,
        "dd": dd,
        "mom": mom,
        "vol": vol,
    }

# ---------- 成分股 ----------
def constituents():
    def f():
        d = ak.index_stock_cons_csindex(symbol=INDEX)
        if d is None or d.empty:
            raise RuntimeError("empty constituents")
        return d

    d = retry(f, 4)
    out = []
    for _, r in d.iterrows():
        code = str(r["成分券代码"]).zfill(6)
        out.append({
            "code": code,
            "name": str(r["成分券名称"]),
            "market": "SH" if code.startswith(("5", "6", "9")) else "SZ"
        })
    return out

# ---------- 腾讯历史K线 ----------
def qq_hist(symbol, days=380):
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

    def f():
        r = S.get(
            url,
            params={"param": f"{symbol},day,,,{days},qfq", "_var": "kline_dayqfq"},
            timeout=20
        )
        r.raise_for_status()
        t = r.text.split("=", 1)[1] if "=" in r.text else r.text
        o = json.loads(t)
        rows = o.get("data", {}).get(symbol, {}).get("qfqday") or \
               o.get("data", {}).get(symbol, {}).get("day")
        if not rows or len(rows) < 250:
            raise RuntimeError("history insufficient")
        return rows

    rows = retry(f, 4)
    return {
        "dates": [str(x[0]) for x in rows],
        "closes": [float(x[2]) for x in rows],
        "highs": [float(x[3]) for x in rows]
    }

# ---------- 腾讯批量实时价 ----------
def qq_quotes(cons):
    syms = [
        ("sh" if s["market"] == "SH" else "sz") + s["code"]
        for s in cons
    ]
    out = {}
    for i in range(0, len(syms), 35):
        batch = syms[i:i + 35]

        def f():
            r = S.get("https://qt.gtimg.cn/q=" + ",".join(batch), timeout=20)
            r.raise_for_status()
            if not r.text.strip():
                raise RuntimeError("empty quotes")
            return r.text

        txt = retry(f, 4)
        for line in txt.splitlines():
            if '="' not in line:
                continue
            left, p = line.split('="', 1)
            p = p.rstrip('";\r\n')
            parts = p.split("~")
            if len(parts) > 3:
                try:
                    price = float(parts[3])
                    if price > 0:
                        out[left.replace("v_", "").strip()] = price
                except Exception:
                    pass
        time.sleep(.3)
    return out

# ---------- 历史缓存 ----------
def load_cache(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def save_cache(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")

def ensure_hist(cons):
    c = load_cache(CACHE, {"date": "", "stocks": {}})
    today = datetime.now(TZ).date().isoformat()
    refresh = c.get("date") != today
    sc = c.setdefault("stocks", {})
    ok = 0

    for s in cons:
        old = sc.get(s["code"])
        need = refresh or not old or len(old.get("closes", [])) < 250
        if not need:
            ok += 1
            continue

        sym = ("sh" if s["market"] == "SH" else "sz") + s["code"]
        try:
            h = qq_hist(sym)
            sc[s["code"]] = {
                "name": s["name"], "market": s["market"], **h
            }
            ok += 1
        except Exception as e:
            print("history fail", s["code"], e)
        time.sleep(.45)

    if ok >= 45:
        c["date"] = today
    save_cache(CACHE, c)
    return c

# ---------- 个股TTM股息率 ----------
def _find_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    for c in df.columns:
        cs = str(c)
        for k in candidates:
            if k in cs:
                return c
    return None

def _to_float(x):
    if x is None or pd.isna(x):
        return None
    try:
        return float(x)
    except Exception:
        import re
        m = re.search(r"-?\d+(?:\.\d+)?", str(x))
        return float(m.group()) if m else None

def stock_ttm_dps(code):
    """
    巨潮资讯分红数据：
    优先按除权/登记/实施日期筛选最近365天，
    派息比例按“每10股派息额”处理，除以10得到每股现金分红。
    """
    def f():
        d = ak.stock_dividend_cninfo(symbol=code)
        if d is None or d.empty:
            raise RuntimeError("empty dividend")
        return d

    d = retry(f, 3)
    date_col = _find_col(d, [
        "除权日", "除息日", "股权登记日", "实施方案公告日期", "实施公告日"
    ])
    payout_col = _find_col(d, [
        "派息比例", "现金分红比例", "每10股派息"
    ])
    if payout_col is None:
        raise RuntimeError("no payout column")

    now = pd.Timestamp(datetime.now(TZ).date())
    cutoff = now - pd.Timedelta(days=365)
    total_per10 = 0.0
    used = 0

    if date_col is not None:
        tmp = d.copy()
        tmp["_dt"] = pd.to_datetime(tmp[date_col], errors="coerce")
        tmp = tmp[(tmp["_dt"] >= cutoff) & (tmp["_dt"] <= now)]
    else:
        tmp = d.head(2)

    for _, r in tmp.iterrows():
        v = _to_float(r[payout_col])
        if v is not None and v > 0:
            total_per10 += v
            used += 1

    if used == 0:
        return None
    return total_per10 / 10.0

def ensure_dividends(cons):
    c = load_cache(DIVCACHE, {"date": "", "stocks": {}})
    today = datetime.now(TZ).date().isoformat()
    sc = c.setdefault("stocks", {})

    # 每天只更新一次分红缓存，盘中5分钟任务不会反复请求
    if c.get("date") == today and len(sc) >= 40:
        return c

    success = 0
    for s in cons:
        try:
            dps = stock_ttm_dps(s["code"])
            sc[s["code"]] = {
                "name": s["name"],
                "ttm_dps": dps
            }
            success += 1
        except Exception as e:
            print("dividend fail", s["code"], e)
        time.sleep(.25)

    # 部分接口失败时保留旧缓存
    if success >= 35:
        c["date"] = today
    save_cache(DIVCACHE, c)
    return c

# ---------- 指数历史 ----------
def index_hist():
    start = (datetime.now(TZ) - timedelta(days=650)).strftime("%Y%m%d")
    end = datetime.now(TZ).strftime("%Y%m%d")

    def f():
        d = ak.stock_zh_index_hist_csindex(
            symbol=INDEX, start_date=start, end_date=end
        )
        if d is None or len(d) < 250:
            raise RuntimeError("index history unavailable")
        return d

    d = retry(f, 5).sort_values("日期")
    c = pd.to_numeric(d["收盘"], errors="coerce").dropna().tolist()
    h = pd.to_numeric(d["最高"], errors="coerce").dropna().tolist()
    return (
        str(pd.to_datetime(d.iloc[-1]["日期"]).date()),
        c, h, float(d.iloc[-1]["收盘"])
    )

# ---------- 指数官方估值/股息率 ----------
def index_dividend_yield():
    def f():
        d = ak.stock_zh_index_value_csindex(symbol=INDEX)
        if d is None or d.empty:
            raise RuntimeError("empty index valuation")
        return d

    try:
        d = retry(f, 4)
        # 官方接口通常最新日期在首行；保险起见按日期倒序
        if "日期" in d.columns:
            d = d.copy()
            d["日期"] = pd.to_datetime(d["日期"], errors="coerce")
            d = d.sort_values("日期", ascending=False)
        for col in ["股息率1", "股息率2", "股息率"]:
            if col in d.columns:
                vals = pd.to_numeric(d[col], errors="coerce").dropna()
                if len(vals):
                    return float(vals.iloc[0])
    except Exception as e:
        print("index dividend fail", e)
    return None

def main():
    cons = constituents()
    print("constituents", len(cons))

    hist_cache = ensure_hist(cons)
    div_cache = ensure_dividends(cons)
    quotes = qq_quotes(cons)
    print("quotes", len(quotes))

    rows = []
    for s in cons:
        h = hist_cache.get("stocks", {}).get(s["code"])
        d = div_cache.get("stocks", {}).get(s["code"], {})
        key = ("sh" if s["market"] == "SH" else "sz") + s["code"]
        q = quotes.get(key)
        if not h or q is None:
            continue

        try:
            m = metrics(h["closes"], h["highs"], q)
            ttm_dps = d.get("ttm_dps")
            div_yield = (ttm_dps / q * 100) if ttm_dps is not None and q > 0 else None
            pos = position_score(m)
            total = combined_score(pos, div_yield)

            m.update(
                code=s["code"],
                name=s["name"],
                market=s["market"],
                dividend_yield=div_yield,
                position_score=pos,
                score=total,
                advice=advice(total)
            )
            rows.append(m)
        except Exception as e:
            print("metric fail", s["code"], e)

    if len(rows) < 40:
        raise RuntimeError(f"too few valid stock rows: {len(rows)}")

    market_date, ic, ih, il = index_hist()
    im = metrics(ic, ih, il)
    idx_div = index_dividend_yield()
    idx_pos = position_score(im)
    idx_score = combined_score(idx_pos, idx_div)
    im.update(
        dividend_yield=idx_div,
        position_score=idx_pos,
        score=idx_score,
        advice=advice(idx_score)
    )

    now = datetime.now(TZ)
    payload = {
        "status": "ok",
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "market_date": market_date,
        "index": im,
        "stocks": rows,
        "count": len(rows),
        "score_ranges": [
            {"min": 80, "max": 100, "label": "强烈买入"},
            {"min": 65, "max": 79, "label": "建议买入"},
            {"min": 45, "max": 64, "label": "持有 / 观察"},
            {"min": 30, "max": 44, "label": "建议减仓"},
            {"min": 0, "max": 29, "label": "建议卖出 / 回避"}
        ]
    }
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print("SUCCESS", len(rows))

if __name__ == "__main__":
    main()
