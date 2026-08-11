from __future__ import annotations
import json, math, os, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import pandas as pd
import akshare as ak

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"data.json"
CACHE=ROOT/"history_cache.json"
TZ=timezone(timedelta(hours=8))
INDEX_CODE="H30269"

def fnum(x, default=None):
    try:
        v=float(x)
        return v if math.isfinite(v) else default
    except: return default

def mean(a): return float(np.mean(a))
def stdev(a): return float(np.std(a, ddof=1)) if len(a)>1 else 0.0

def position_score(annual, dd, mom, vol):
    if -12<=annual<=-5: a=95
    elif -5<annual<=3: a=80
    elif 3<annual<=10: a=60
    elif 10<annual<=20: a=35
    elif annual>20: a=15
    elif -22<=annual<-12: a=72
    else: a=45
    if 6<=dd<=18: d=90
    elif dd<6: d=max(50,min(90,50+dd*6))
    else: d=max(25,min(90,90-(dd-18)*3.5))
    if 0<=mom<=12: mo=80+mom
    elif mom<0: mo=max(20,min(75,75+mom*3))
    else: mo=max(30,min(92,92-(mom-12)*2.5))
    v=max(20,min(100,105-vol*3.5))
    return int(round(a*.35+d*.25+mo*.20+v*.20))

def calc_from_closes(closes, highs, current):
    c=[float(x) for x in closes if pd.notna(x)]
    h=[float(x) for x in highs if pd.notna(x)]
    if len(c)<250: raise ValueError("history < 250")
    base=c[-249:]
    ma250=mean(base+[current])
    annual=(current/ma250-1)*100
    high=max(h[-249:]+[current])
    dd=max(0.0,(1-current/high)*100)
    anchor=c[-60] if len(c)>=60 else c[0]
    mom=(current/anchor-1)*100
    seq=c[-20:]+[current]
    rets=[seq[i]/seq[i-1]-1 for i in range(1,len(seq))]
    vol=stdev(rets)*np.sqrt(252)*100
    return ma250,annual,dd,mom,float(vol)

def market_prefix(code):
    return "sh" if str(code).startswith(("5","6","9")) else "sz"

def get_constituents():
    df=ak.index_stock_cons_csindex(symbol=INDEX_CODE)
    if df is None or df.empty: raise RuntimeError("constituents empty")
    out=[]
    for _,r in df.iterrows():
        code=str(r["成分券代码"]).zfill(6)
        out.append({"code":code,"name":str(r["成分券名称"])})
    if len(out)!=50: print("warning constituents:",len(out))
    return out

def load_cache():
    try:return json.loads(CACHE.read_text(encoding="utf-8"))
    except:return {}

def save_cache(c): CACHE.write_text(json.dumps(c,ensure_ascii=False),encoding="utf-8")

def hist_stock(code):
    start=(datetime.now(TZ)-timedelta(days=520)).strftime("%Y%m%d")
    end=datetime.now(TZ).strftime("%Y%m%d")
    df=ak.stock_zh_a_hist(symbol=code,period="daily",start_date=start,end_date=end,adjust="qfq")
    if df is None or len(df)<250: raise RuntimeError("stock history insufficient")
    return {
        "date":str(df.iloc[-1]["日期"]),
        "closes":[float(x) for x in pd.to_numeric(df["收盘"],errors="coerce").dropna().tolist()[-270:]],
        "highs":[float(x) for x in pd.to_numeric(df["最高"],errors="coerce").dropna().tolist()[-270:]],
    }

def hist_index():
    start=(datetime.now(TZ)-timedelta(days=520)).strftime("%Y%m%d")
    end=datetime.now(TZ).strftime("%Y%m%d")
    df=ak.stock_zh_index_hist_csindex(symbol=INDEX_CODE,start_date=start,end_date=end)
    if df is None or len(df)<250: raise RuntimeError("index history insufficient")
    return {
        "date":str(df.iloc[-1]["日期"]),
        "closes":[float(x) for x in pd.to_numeric(df["收盘"],errors="coerce").dropna().tolist()[-270:]],
        "highs":[float(x) for x in pd.to_numeric(df["最高"],errors="coerce").dropna().tolist()[-270:]],
    }

def need_refresh_history(cache):
    today=datetime.now(TZ).strftime("%Y-%m-%d")
    return cache.get("_history_date")!=today

def get_spots():
    df=ak.stock_zh_a_spot_em()
    df["代码"]=df["代码"].astype(str).str.zfill(6)
    return df.set_index("代码")

def get_index_spot():
    df=ak.stock_zh_index_spot_em(symbol="中证系列指数")
    df["代码"]=df["代码"].astype(str)
    row=df[df["代码"].isin([INDEX_CODE,"H30269"])]
    if row.empty:
        # fall back to latest official daily close
        return None
    r=row.iloc[0]
    return {"price":fnum(r["最新价"]),"change":fnum(r.get("涨跌幅"),0.0)}

def main():
    now=datetime.now(TZ)
    constituents=get_constituents()
    cache=load_cache()

    if need_refresh_history(cache):
        new={"_history_date":now.strftime("%Y-%m-%d")}
        try:new["index"]=hist_index()
        except Exception as e:
            if "index" in cache:new["index"]=cache["index"]
            else: raise
        def task(s):
            try:return s["code"],hist_stock(s["code"])
            except Exception as e:return s["code"],cache.get(s["code"])
        with ThreadPoolExecutor(max_workers=6) as ex:
            fut=[ex.submit(task,s) for s in constituents]
            for f in as_completed(fut):
                code,h=f.result()
                if h:new[code]=h
        cache=new
        save_cache(cache)

    spots=get_spots()
    idx_spot=get_index_spot()

    # index
    ih=cache["index"]
    idx_current=idx_spot["price"] if idx_spot and idx_spot.get("price") else float(ih["closes"][-1])
    ima,ia,idd,imom,ivol=calc_from_closes(ih["closes"],ih["highs"],idx_current)
    idx_score=position_score(ia,idd,imom,ivol)
    idx_change=idx_spot["change"] if idx_spot else 0.0

    stocks=[]
    for s in constituents:
        code=s["code"]; h=cache.get(code)
        if not h or code not in spots.index:
            stocks.append({"code":code,"name":s["name"],"ok":False}); continue
        r=spots.loc[code]
        price=fnum(r.get("最新价"))
        if not price:
            stocks.append({"code":code,"name":s["name"],"ok":False}); continue
        try:
            ma,annual,dd,mom,vol=calc_from_closes(h["closes"],h["highs"],price)
            stocks.append({
                "code":code,"name":s["name"],"ok":True,
                "market_date":h.get("date"),
                "close":round(price,3),"change":round(fnum(r.get("涨跌幅"),0.0),3),
                "ma250":round(ma,3),"annual":round(annual,3),"dd":round(dd,3),
                "mom":round(mom,3),"vol":round(vol,3),
                "score":position_score(annual,dd,mom,vol)
            })
        except:
            stocks.append({"code":code,"name":s["name"],"ok":False})

    payload={
      "status":"ok",
      "updated_at":now.strftime("%Y-%m-%d %H:%M:%S"),
      "market_date":ih.get("date"),
      "index":{
        "close":round(idx_current,3),"change":round(idx_change,3),"ma250":round(ima,3),
        "annual":round(ia,3),"dd":round(idd,3),"mom":round(imom,3),"vol":round(ivol,3),
        "score":idx_score
      },
      "stocks":stocks,
      "constituent_count":len(constituents)
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding="utf-8")
    print("updated",payload["updated_at"],"stocks",len(stocks))

if __name__=="__main__":
    main()
