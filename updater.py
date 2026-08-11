# VERSION = "V6.4-YAHOO-ETF-PROXY"
from __future__ import annotations
import json, math
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"data.json"
CACHE=ROOT/"history_cache.json"
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
    print("Downloading 2y daily history for 51 tickers from Yahoo Finance...")
    df=yf.download(ALL_TICKERS,period="2y",interval="1d",group_by="ticker",
                   auto_adjust=False,threads=True,progress=False,timeout=30)
    cache={"_source":"Yahoo Finance via yfinance",
           "_built_at":datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S"),
           "_history_date":datetime.now(TZ).strftime("%Y-%m-%d")}
    ok=0
    for t in ALL_TICKERS:
        x=ticker_frame(df,t)
        if x.empty or "Close" not in x.columns:continue
        x=x.dropna(subset=["Close"])
        if len(x)<250:continue
        close=[float(v) for v in x["Close"].tail(280)]
        high=[float(v) for v in x["High"].tail(280)] if "High" in x.columns else close
        dates=[str(pd.Timestamp(v).date()) for v in x.tail(280).index]
        cache[t]={"dates":dates,"closes":close,"highs":high}
        ok+=1
    print("Daily history cached:",ok,"/",len(ALL_TICKERS))
    if INDEX_PROXY["ticker"] not in cache:
        raise RuntimeError("159547 ETF proxy history unavailable")
    if ok<45:
        raise RuntimeError(f"Yahoo daily history only returned {ok}/51 tickers")
    save_cache(cache);return cache

def download_intraday():
    print("Downloading latest 5m prices...")
    try:
        return yf.download(ALL_TICKERS,period="1d",interval="5m",group_by="ticker",
                           auto_adjust=False,threads=True,progress=False,timeout=25)
    except Exception as e:
        print("Intraday failed:",repr(e));return pd.DataFrame()

def latest_from_intraday(df,ticker):
    x=ticker_frame(df,ticker)
    if x.empty or "Close" not in x.columns:return None,None
    x=x.dropna(subset=["Close"])
    if x.empty:return None,None
    return num(x.iloc[-1]["Close"]),str(x.index[-1])

def calc(h,current):
    c=[num(x) for x in h["closes"] if num(x) is not None]
    hi=[num(x) for x in h["highs"] if num(x) is not None]
    if len(c)<250:raise ValueError("history <250")
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
    intra=download_intraday()

    def produce(item):
        t=item["ticker"];h=cache.get(t)
        if not h:return None
        p,ts=latest_from_intraday(intra,t)
        if p is None:p=num(h["closes"][-1]);ts=h["dates"][-1]+" close"
        if not p:return None
        m=calc(h,p);m["market_date"]=h["dates"][-1];m["quote_time"]=ts
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

    payload={"status":"ok","source":"Yahoo Finance / yfinance",
             "index_source":"159547 ETF proxy for H30269",
             "updated_at":now.strftime("%Y-%m-%d %H:%M:%S"),
             "market_date":idx.get("market_date","--"),"index":idx,
             "stocks":stock_rows,"constituent_count":len(STOCKS),"valid_stock_count":ok}
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print("SUCCESS",payload["updated_at"],"valid stocks:",ok,"index proxy:159547")

if __name__=="__main__":
    main()
