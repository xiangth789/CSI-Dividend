# VERSION = "V8.0-TENCENT-INTRADAY"
from __future__ import annotations
import json, math, os, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import yfinance as yf
from quote_provider import fetch_tencent_quotes

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"data.json"
CACHE=ROOT/"history_cache.json"
DIV_CACHE=ROOT/"dividend_cache.json"
TZ=timezone(timedelta(hours=8))

# H30269 在 Yahoo 历史接口不可用，因此用官方跟踪该指数的 159547 ETF 做“指数价格位置代理”
INDEX_PROXY={"name":"华夏中证红利低波动ETF","code":"159547","ticker":"159547.SZ","tracks":"H30269"}
STOCKS=[{"name": "重庆银行", "code": "601963", "ticker": "601963.SS"}, {"name": "华润江中", "code": "600750", "ticker": "600750.SS"}, {"name": "华能蒙电", "code": "600863", "ticker": "600863.SS"}, {"name": "上海银行", "code": "601229", "ticker": "601229.SS"}, {"name": "南京银行", "code": "601009", "ticker": "601009.SS"}, {"name": "平安银行", "code": "000001", "ticker": "000001.SZ"}, {"name": "成都银行", "code": "601838", "ticker": "601838.SS"}, {"name": "沪农商行", "code": "601825", "ticker": "601825.SS"}, {"name": "山东高速", "code": "600350", "ticker": "600350.SS"}, {"name": "安徽建工", "code": "600502", "ticker": "600502.SS"}, {"name": "格力电器", "code": "000651", "ticker": "000651.SZ"}, {"name": "陕鼓动力", "code": "601369", "ticker": "601369.SS"}, {"name": "江苏银行", "code": "600919", "ticker": "600919.SS"}, {"name": "中国国贸", "code": "600007", "ticker": "600007.SS"}, {"name": "中国石油", "code": "601857", "ticker": "601857.SS"}, {"name": "民生银行", "code": "600016", "ticker": "600016.SS"}, {"name": "济川药业", "code": "600566", "ticker": "600566.SS"}, {"name": "长沙银行", "code": "601577", "ticker": "601577.SS"}, {"name": "中国海油", "code": "600938", "ticker": "600938.SS"}, {"name": "塔牌集团", "code": "002233", "ticker": "002233.SZ"}, {"name": "渝农商行", "code": "601077", "ticker": "601077.SS"}, {"name": "华夏银行", "code": "600015", "ticker": "600015.SS"}, {"name": "张家港行", "code": "002839", "ticker": "002839.SZ"}, {"name": "粤高速A", "code": "000429", "ticker": "000429.SZ"}, {"name": "厦门银行", "code": "601187", "ticker": "601187.SS"}, {"name": "隧道股份", "code": "600820", "ticker": "600820.SS"}, {"name": "苏州银行", "code": "002966", "ticker": "002966.SZ"}, {"name": "北京银行", "code": "601169", "ticker": "601169.SS"}, {"name": "新奥股份", "code": "600803", "ticker": "600803.SS"}, {"name": "洪城环境", "code": "600461", "ticker": "600461.SS"}, {"name": "中信银行", "code": "601998", "ticker": "601998.SS"}, {"name": "中国银行", "code": "601988", "ticker": "601988.SS"}, {"name": "齐鲁银行", "code": "601665", "ticker": "601665.SS"}, {"name": "建设银行", "code": "601939", "ticker": "601939.SS"}, {"name": "招商银行", "code": "600036", "ticker": "600036.SS"}, {"name": "中粮糖业", "code": "600737", "ticker": "600737.SS"}, {"name": "美的集团", "code": "000333", "ticker": "000333.SZ"}, {"name": "梅花生物", "code": "600873", "ticker": "600873.SS"}, {"name": "交通银行", "code": "601328", "ticker": "601328.SS"}, {"name": "工商银行", "code": "601398", "ticker": "601398.SS"}, {"name": "中国建筑", "code": "601668", "ticker": "601668.SS"}, {"name": "中信特钢", "code": "000708", "ticker": "000708.SZ"}, {"name": "三维化学", "code": "002469", "ticker": "002469.SZ"}, {"name": "江阴银行", "code": "002807", "ticker": "002807.SZ"}, {"name": "凤凰传媒", "code": "601928", "ticker": "601928.SS"}, {"name": "邮储银行", "code": "601658", "ticker": "601658.SS"}, {"name": "中国平安", "code": "601318", "ticker": "601318.SS"}, {"name": "长江传媒", "code": "600757", "ticker": "600757.SS"}, {"name": "中国移动", "code": "600941", "ticker": "600941.SS"}, {"name": "农业银行", "code": "601288", "ticker": "601288.SS"}]
ALL_TICKERS=[INDEX_PROXY["ticker"]]+[x["ticker"] for x in STOCKS]

def num(x,default=None):
    try:
        v=float(x); return v if math.isfinite(v) else default
    except Exception:return default

def position_score(annual,dd,mom,vol):
    if -12<=annual<=-5:a=95
    elif -5<annual<=3:a=80
    elif 3<annual<=10:a=60
    elif 10<annual<=20:a=35
    elif annual>20:a=15
    elif -22<=annual<-12:a=72
    else:a=45
    if 6<=dd<=18:d=90
    elif dd<6:d=max(50,min(90,50+dd*6))
    else:d=max(25,min(90,90-(dd-18)*3.5))
    if 0<=mom<=12:mo=80+mom
    elif mom<0:mo=max(20,min(75,75+mom*3))
    else:mo=max(30,min(92,92-(mom-12)*2.5))
    v=max(20,min(100,105-vol*3.5))
    return int(round(a*.35+d*.25+mo*.20+v*.20))

def load_cache():
    try:return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:return {}

def save_cache(c):CACHE.write_text(json.dumps(c,ensure_ascii=False),encoding="utf-8")

def ticker_frame(df,ticker):
    if df is None or df.empty:return pd.DataFrame()
    if isinstance(df.columns,pd.MultiIndex):
        try:x=df[ticker].copy()
        except Exception:return pd.DataFrame()
    else:x=df.copy()
    return x.dropna(how="all")

def build_daily_cache():
    print("Downloading 5y daily PRICE history for 51 tickers from Yahoo Finance...")
    df=yf.download(ALL_TICKERS,period="5y",interval="1d",group_by="ticker",
                   auto_adjust=False,actions=False,threads=True,progress=False,timeout=40)
    cache={"_source":"Yahoo Finance via yfinance",
           "_built_at":datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
           "_history_date":datetime.now(TZ).strftime("%Y-%m-%d")}
    ok=0
    for t in ALL_TICKERS:
        x=ticker_frame(df,t)
        if x.empty or "Close" not in x.columns:continue
        x=x.dropna(subset=["Close"])
        if len(x)<250:continue
        x=x.tail(1400)
        close=[float(v) for v in x["Close"]]
        high=[float(v) for v in x["High"]] if "High" in x.columns else close
        dates=[str(pd.Timestamp(v).date()) for v in x.index]
        cache[t]={"dates":dates,"closes":close,"highs":high}
        ok+=1
    print("Daily price history cached:",ok,"/",len(ALL_TICKERS))
    if INDEX_PROXY["ticker"] not in cache:
        raise RuntimeError("159547 ETF proxy history unavailable")
    if ok<45:
        raise RuntimeError(f"Yahoo daily history only returned {ok}/51 tickers")
    save_cache(cache);return cache

def load_div_cache():
    try:return json.loads(DIV_CACHE.read_text(encoding="utf-8"))
    except Exception:return {}

def save_div_cache(c):
    DIV_CACHE.write_text(json.dumps(c,ensure_ascii=False,indent=2),encoding="utf-8")

def _series_to_dividends(series):
    out=[]
    if series is None:return out
    try:
        series=series.dropna()
    except Exception:
        return out
    for dt,val in series.items():
        vv=num(val,0.0) or 0.0
        if vv<=0:continue
        try:d=str(pd.Timestamp(dt).date())
        except Exception:continue
        out.append({"date":d,"amount":round(vv,6)})
    # Yahoo can occasionally repeat a corporate-action row; deduplicate date+amount.
    seen=set();clean=[]
    for r in out:
        k=(r["date"],r["amount"])
        if k not in seen:
            seen.add(k);clean.append(r)
    clean.sort(key=lambda r:r["date"])
    return clean

def fetch_dividends_one(ticker):
    """Fetch corporate cash-dividend actions independently from bulk price download."""
    last=None
    for attempt in range(1,4):
        try:
            tk=yf.Ticker(ticker)
            # First choice: dedicated corporate-action endpoint exposed by yfinance.
            s=tk.dividends
            divs=_series_to_dividends(s)
            if divs:
                return divs,"Ticker.dividends"
            # Fallback: per-ticker history with actions=True.
            h=tk.history(period="5y",interval="1d",auto_adjust=False,
                         actions=True,repair=True,raise_errors=False)
            if h is not None and not h.empty and "Dividends" in h.columns:
                divs=_series_to_dividends(h["Dividends"])
                if divs:
                    return divs,"Ticker.history(actions=True)"
            last="empty dividend response"
        except Exception as e:
            last=repr(e)
        time.sleep(attempt*1.2)
    raise RuntimeError(last or "no dividend data")

def refresh_dividend_cache(force=False):
    old=load_div_cache()
    today=datetime.now(TZ).strftime("%Y-%m-%d")
    old_date=old.get("_dividend_date")
    have=sum(1 for t in [x["ticker"] for x in STOCKS] if old.get(t,{}).get("dividends"))
    if not force and old_date==today and have>=35:
        print("Dividend cache is fresh:",have,"/50")
        return old

    print("Refreshing dedicated dividend actions for 50 stocks...")
    new={
        "_source":"Yahoo Finance per-ticker corporate actions via yfinance",
        "_built_at":datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "_dividend_date":today
    }

    # Reuse old per-stock data if Yahoo transiently fails for a ticker.
    failures=[]
    def job(item):
        t=item["ticker"]
        divs,source=fetch_dividends_one(t)
        return t,divs,source

    # Moderate concurrency to reduce rate-limit risk.
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs={ex.submit(job,s):s for s in STOCKS}
        for fut in as_completed(futs):
            s=futs[fut];t=s["ticker"]
            try:
                t,divs,source=fut.result()
                new[t]={"dividends":divs,"source":source,
                        "updated_at":datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")}
                print("dividend ok",t,len(divs),source)
            except Exception as e:
                old_entry=old.get(t)
                if old_entry and old_entry.get("dividends"):
                    new[t]=old_entry
                    print("dividend fallback-cache",t,repr(e))
                else:
                    failures.append((t,repr(e)))
                    new[t]={"dividends":[],"error":repr(e)}
                    print("dividend failed",t,repr(e))

    valid=sum(1 for s in STOCKS if new.get(s["ticker"],{}).get("dividends"))
    print("Dividend history valid:",valid,"/50")
    save_div_cache(new)

    # This is a dividend index: if fewer than 35 names return any dividend history,
    # treat the corporate-action feed as broken rather than silently publishing blanks.
    if valid<35:
        raise RuntimeError(f"Dividend self-check failed: only {valid}/50 stocks have dividend history")
    return new

def in_active_market_session(now):
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return (570 <= hm <= 690) or (780 <= hm <= 900)  # 09:30-11:30, 13:00-15:00

def validate_realtime_quotes(quotes, now):
    valid = len(quotes)
    print("Tencent realtime quotes:", valid, "/51")
    if valid < 45:
        raise RuntimeError(f"Tencent realtime self-check failed: only {valid}/51 quotes")
    if in_active_market_session(now):
        today = now.strftime("%Y-%m-%d")
        todays = [q for q in quotes.values() if q.get("market_date") == today]
        if len(todays) < 45:
            raise RuntimeError(f"Realtime freshness failed: only {len(todays)}/51 quotes dated {today}")
        times = []
        for q in todays:
            try:
                times.append(datetime.strptime(q["quote_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ))
            except Exception:
                pass
        if times:
            newest = max(times)
            age = (now - newest).total_seconds() / 60
            print("Newest Tencent quote:", newest.strftime("%Y-%m-%d %H:%M:%S"), "age_min:", round(age,1))
            if age > 20:
                raise RuntimeError(f"Realtime freshness failed: newest quote is {age:.1f} minutes old")


def dividend_metrics(h,current,divs=None):
    """Calculate trailing dividend yield from dedicated corporate-action data."""
    divs=(divs or [])
    if not divs or not current:
        return {"div_yield":None,"div_ttm":0.0,"div_3y_avg_yield":None,
                "div_yield_premium":None,"div_years":[],"div_continuity":0}

    today=datetime.now(TZ).date()
    rows=[]
    for d in divs:
        try:
            dt=datetime.strptime(d["date"],"%Y-%m-%d").date()
            amt=num(d.get("amount"),0.0) or 0.0
            if amt>0: rows.append((dt,amt))
        except Exception:
            pass

    ttm=sum(a for dt,a in rows if 0 <= (today-dt).days <= 365)
    div_yield=(ttm/current*100) if current>0 else None

    # Aggregate cash dividend by calendar year and pair with average annual close.
    dates=[datetime.strptime(s,"%Y-%m-%d").date() for s in h.get("dates",[])]
    closes=[num(v) for v in h.get("closes",[])]
    yearly=[]
    for yr in range(today.year-1,today.year-4,-1):
        cash=sum(a for dt,a in rows if dt.year==yr)
        px=[p for dt,p in zip(dates,closes) if dt.year==yr and p]
        avgpx=float(np.mean(px)) if px else None
        yld=(cash/avgpx*100) if cash>0 and avgpx else None
        yearly.append({"year":yr,"cash":round(cash,4),"yield":round(yld,3) if yld is not None else None})

    valid=[r["yield"] for r in yearly if r["yield"] is not None]
    avg3=float(np.mean(valid)) if valid else None
    premium=(div_yield-avg3) if div_yield is not None and avg3 is not None else None
    continuity=sum(1 for r in yearly if r["cash"]>0)

    return {
        "div_yield":round(div_yield,3) if div_yield is not None else None,
        "div_ttm":round(ttm,4),
        "div_3y_avg_yield":round(avg3,3) if avg3 is not None else None,
        "div_yield_premium":round(premium,3) if premium is not None else None,
        "div_years":yearly,
        "div_continuity":continuity
    }

def dividend_score_from_cross_section(rows):
    """Score dividend attractiveness using current yield rank + premium to own 3y average."""
    valid=[r for r in rows if r.get("ok") and r.get("div_yield") is not None]
    vals=sorted([r["div_yield"] for r in valid])
    n=len(vals)
    if not n:return
    for r in valid:
        y=r["div_yield"]
        rank=sum(v<=y for v in vals)/n
        rank_score=35+65*rank
        prem=r.get("div_yield_premium")
        if prem is None:
            own_score=60
        elif prem>=1.5: own_score=100
        elif prem>=0.5: own_score=85
        elif prem>=-0.3: own_score=70
        elif prem>=-1.0: own_score=50
        else: own_score=30
        ds=int(round(rank_score*0.70+own_score*0.30))
        r["div_score"]=ds
        r["position_score"]=r.get("score")
        r["score"]=int(round((r.get("position_score") or 0)*0.55 + ds*0.45))

def calc(h,current,current_date=None):
    c=[num(x) for x in h["closes"] if num(x) is not None]
    hi=[num(x) for x in h["highs"] if num(x) is not None]
    dates=h.get("dates",[])
    # If Yahoo daily cache already contains the same trading day, remove that last
    # close before appending the Tencent quote so today's price is counted once.
    if current_date and dates and dates[-1] == current_date and len(c)>1:
        c=c[:-1]
        hi=hi[:-1] if len(hi)>1 else hi
    if len(c)<249:raise ValueError("history <249")
    ma250=float(np.mean(c[-249:]+[current]))
    annual=(current/ma250-1)*100
    high=max(hi[-249:]+[current]);dd=max(0.0,(1-current/high)*100)
    anchor=c[-60];mom=(current/anchor-1)*100
    seq=c[-20:]+[current];rets=[seq[i]/seq[i-1]-1 for i in range(1,len(seq))]
    vol=float(np.std(rets,ddof=1)*np.sqrt(252)*100) if len(rets)>1 else 0
    prev=c[-1];change=(current/prev-1)*100 if prev else 0
    return {"close":round(current,3),"change":round(change,3),"ma250":round(ma250,3),
             "annual":round(annual,3),"dd":round(dd,3),"mom":round(mom,3),"vol":round(vol,3),
             "score":position_score(annual,dd,mom,vol)}

def main():
    now=datetime.now(TZ);cache=load_cache()
    need=INDEX_PROXY["ticker"] not in cache or sum(t in cache for t in ALL_TICKERS)<45
    if now.hour>=16 and cache.get("_history_date")!=now.strftime("%Y-%m-%d"):need=True
    if need:cache=build_daily_cache()
    force_div=os.getenv("FORCE_DIVIDENDS","0")=="1"
    div_cache=refresh_dividend_cache(force=force_div)
    quote_codes=[INDEX_PROXY["code"]]+[s["code"] for s in STOCKS]
    quotes=fetch_tencent_quotes(quote_codes)
    validate_realtime_quotes(quotes, now)

    def produce(item):
        t=item["ticker"];code=item["code"];h=cache.get(t)
        if not h:return None
        q=quotes.get(code)
        if not q:
            raise RuntimeError(f"missing Tencent quote: {code}")
        p=num(q.get("price"))
        if not p:return None
        market_date=q.get("market_date") or h["dates"][-1]
        m=calc(h,p,market_date)
        # Use exchange quote for the displayed intraday change rather than
        # recomputing against a possibly same-day Yahoo daily cache.
        if q.get("change_pct") is not None:
            m["change"]=round(float(q["change_pct"]),3)
        m.update(dividend_metrics(h,p,div_cache.get(t,{}).get("dividends",[])))
        m["market_date"]=market_date
        m["quote_time"]=q.get("quote_time")
        m["quote_source"]="Tencent Finance"
        m["open"]=q.get("open")
        m["high_today"]=q.get("high")
        m["low_today"]=q.get("low")
        m["turnover"]=q.get("turnover")
        m["pe_ttm_live"]=q.get("pe_ttm")
        m["pb_live"]=q.get("pb")
        return m

    idx=produce(INDEX_PROXY)
    if idx is None:raise RuntimeError("No 159547 proxy data")
    idx["proxy_code"]="159547";idx["tracks_index"]="H30269";idx["is_proxy"]=True

    stock_rows=[];ok=0
    for s in STOCKS:
        try:
            m=produce(s)
            if m:
                stock_rows.append({"name":s["name"],"code":s["code"],"ok":True,**m});ok+=1
            else:stock_rows.append({"name":s["name"],"code":s["code"],"ok":False})
        except Exception as e:
            print("stock failed",s["ticker"],repr(e))
            stock_rows.append({"name":s["name"],"code":s["code"],"ok":False})

    dividend_score_from_cross_section(stock_rows)
    div_valid=sum(1 for r in stock_rows if r.get("ok") and r.get("div_yield") is not None)
    print("TTM dividend yield valid:",div_valid,"/50")
    if div_valid<35:
        raise RuntimeError(f"TTM dividend yield self-check failed: only {div_valid}/50 valid")

    payload={"status":"ok","version":"V8.0","source":"Tencent Finance realtime + Yahoo Finance history",
             "index_source":"159547 ETF proxy for H30269","score_model":"55%价格位置 + 45%股息吸引力","dividend_source":"Yahoo per-ticker corporate actions","realtime_source":"Tencent Finance qt.gtimg.cn","quote_valid_count":len(quotes),
             "updated_at":now.strftime("%Y-%m-%d %H:%M:%S"),
             "market_date":idx.get("market_date","--"),"index":idx,
             "stocks":stock_rows,"constituent_count":len(STOCKS),"valid_stock_count":ok,"valid_dividend_count":div_valid}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print("SUCCESS V8.0",payload["updated_at"],"valid stocks:",ok,"valid dividends:",div_valid,"realtime quotes:",len(quotes),"index proxy:159547")

if __name__=="__main__":
    main()
