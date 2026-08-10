# -*- coding: utf-8 -*-
from __future__ import annotations
import json, math, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np
import pandas as pd
import akshare as ak

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"data.json"
CACHE=ROOT/"history_cache.json"
INDEX="H30269"
TZ=ZoneInfo("Asia/Shanghai")

def clamp(x,a,b): return max(a,min(b,x))
def score(m):
    a=95 if -12<=m["annual"]<=-5 else 80 if -5<m["annual"]<=3 else 60 if 3<m["annual"]<=10 else 35 if 10<m["annual"]<=20 else 15 if m["annual"]>20 else 72 if m["annual"]>=-22 else 45
    dd=m["dd"]
    d=90 if 6<=dd<=18 else clamp(50+dd*6,50,90) if dd<6 else clamp(90-(dd-18)*3.5,25,90)
    mom=m["mom"]
    mo=80+mom if 0<=mom<=12 else clamp(75+mom*3,20,75) if mom<0 else clamp(92-(mom-12)*2.5,30,92)
    v=clamp(105-m["vol"]*3.5,20,100)
    return round(a*.35+d*.25+mo*.20+v*.20)

def metrics(closes, highs, latest):
    c=np.array(closes,dtype=float)
    h=np.array(highs,dtype=float)
    if len(c)<250: raise ValueError("history<250")
    dyn=np.r_[c[-249:], latest]
    ma250=float(np.mean(dyn))
    annual=(latest/ma250-1)*100
    high=max(float(np.max(h[-249:])), latest)
    dd=(1-latest/high)*100
    anchor=float(c[-60])
    mom=(latest/anchor-1)*100
    recent=np.r_[c[-20:], latest]
    ret=recent[1:]/recent[:-1]-1
    vol=float(np.std(ret,ddof=1)*np.sqrt(252)*100)
    return dict(close=float(latest),ma250=ma250,annual=annual,dd=dd,mom=mom,vol=vol)

def get_constituents():
    df=ak.index_stock_cons_csindex(symbol=INDEX)
    code_col="成分券代码"; name_col="成分券名称"
    if code_col not in df.columns: raise RuntimeError("constituent columns changed")
    out=[]
    for _,r in df.iterrows():
        code=str(r[code_col]).zfill(6)
        out.append({"code":code,"name":str(r[name_col])})
    return out

def build_history(constituents):
    start=(datetime.now(TZ)-timedelta(days=520)).strftime("%Y%m%d")
    end=datetime.now(TZ).strftime("%Y%m%d")
    cache={"date":datetime.now(TZ).date().isoformat(),"stocks":{}}
    for i,s in enumerate(constituents,1):
        try:
            df=ak.stock_zh_a_hist(symbol=s["code"],period="daily",start_date=start,end_date=end,adjust="")
            if len(df)<250: continue
            cache["stocks"][s["code"]]={
                "name":s["name"],
                "dates":[str(x)[:10] for x in df["日期"].tolist()],
                "closes":[float(x) for x in df["收盘"].tolist()],
                "highs":[float(x) for x in df["最高"].tolist()],
            }
        except Exception as e:
            print("history fail",s["code"],e)
        time.sleep(.08)
    CACHE.write_text(json.dumps(cache,ensure_ascii=False),encoding="utf-8")
    return cache

def get_cache(constituents):
    today=datetime.now(TZ).date().isoformat()
    if CACHE.exists():
        try:
            c=json.loads(CACHE.read_text(encoding="utf-8"))
            # refresh history once each calendar day or if constituent count changed materially
            if c.get("date")==today and len(c.get("stocks",{}))>=45:
                return c
        except: pass
    return build_history(constituents)

def latest_stock_prices():
    df=ak.stock_zh_a_spot_em()
    return {str(r["代码"]).zfill(6): float(r["最新价"]) for _,r in df.iterrows()
            if pd.notna(r.get("最新价")) and str(r.get("代码","")).strip()}

def index_history():
    start=(datetime.now(TZ)-timedelta(days=520)).strftime("%Y%m%d")
    end=datetime.now(TZ).strftime("%Y%m%d")
    df=ak.stock_zh_index_hist_csindex(symbol=INDEX,start_date=start,end_date=end)
    df=df.sort_values("日期")
    closes=[float(x) for x in df["收盘"].dropna().tolist()]
    highs=[float(x) for x in df["最高"].dropna().tolist()]
    date=str(df.iloc[-1]["日期"])[:10]
    latest=float(df.iloc[-1]["收盘"])
    return date, closes, highs, latest

def main():
    constituents=get_constituents()
    cache=get_cache(constituents)
    spot=latest_stock_prices()
    rows=[]
    for s in constituents:
        h=cache.get("stocks",{}).get(s["code"])
        latest=spot.get(s["code"])
        if not h or latest is None or not math.isfinite(latest): continue
        m=metrics(h["closes"],h["highs"],latest)
        m.update(code=s["code"],name=s["name"])
        m["score"]=score(m)
        rows.append(m)

    idate,ic,ih,ilatest=index_history()
    im=metrics(ic,ih,ilatest)

    now=datetime.now(TZ)
    data={
        "updated_at":now.strftime("%Y-%m-%d %H:%M:%S"),
        "market_date":idate,
        "index":im,
        "stocks":rows,
        "count":len(rows)
    }
    OUT.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    print("updated",len(rows),"stocks")

if __name__=="__main__":
    main()
