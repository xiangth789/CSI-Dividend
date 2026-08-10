# -*- coding: utf-8 -*-
import json,time,math,requests
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, akshare as ak

ROOT=Path(__file__).resolve().parent
OUT=ROOT/"data.json"; CACHE=ROOT/"history_cache.json"
INDEX="H30269"; TZ=ZoneInfo("Asia/Shanghai")
S=requests.Session()
S.headers.update({"User-Agent":"Mozilla/5.0","Referer":"https://finance.qq.com/"})

def clamp(x,a,b): return max(a,min(b,x))
def retry(fn,n=4):
    last=None
    for i in range(n):
        try:return fn()
        except Exception as e:
            last=e; time.sleep(2*(i+1))
    raise last

def score(m):
    a=95 if -12<=m["annual"]<=-5 else 80 if -5<m["annual"]<=3 else 60 if 3<m["annual"]<=10 else 35 if 10<m["annual"]<=20 else 15 if m["annual"]>20 else 72 if m["annual"]>=-22 else 45
    dd=m["dd"]; d=90 if 6<=dd<=18 else clamp(50+dd*6,50,90) if dd<6 else clamp(90-(dd-18)*3.5,25,90)
    mom=m["mom"]; mo=80+mom if 0<=mom<=12 else clamp(75+mom*3,20,75) if mom<0 else clamp(92-(mom-12)*2.5,30,92)
    v=clamp(105-m["vol"]*3.5,20,100)
    return round(a*.35+d*.25+mo*.2+v*.2)

def metrics(c,h,latest):
    c=np.array(c,float); h=np.array(h,float)
    if len(c)<250: raise ValueError("history<250")
    ma=float(np.mean(np.r_[c[-249:],latest]))
    annual=(latest/ma-1)*100
    dd=(1-latest/max(float(np.max(h[-249:])),latest))*100
    mom=(latest/float(c[-60])-1)*100
    recent=np.r_[c[-20:],latest]; ret=recent[1:]/recent[:-1]-1
    vol=float(np.std(ret,ddof=1)*np.sqrt(252)*100)
    return {"close":float(latest),"ma250":ma,"annual":annual,"dd":dd,"mom":mom,"vol":vol}

def constituents():
    def f():
        d=ak.index_stock_cons_csindex(symbol=INDEX)
        if d is None or d.empty: raise RuntimeError("empty constituents")
        return d
    d=retry(f,4)
    out=[]
    for _,r in d.iterrows():
        code=str(r["成分券代码"]).zfill(6)
        out.append({"code":code,"name":str(r["成分券名称"]),"market":"SH" if code.startswith(("5","6","9")) else "SZ"})
    return out

def qq_hist(symbol,days=380):
    url="https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    def f():
        r=S.get(url,params={"param":f"{symbol},day,,,{days},qfq","_var":"kline_dayqfq"},timeout=20); r.raise_for_status()
        t=r.text.split("=",1)[1] if "=" in r.text else r.text
        o=json.loads(t); rows=o.get("data",{}).get(symbol,{}).get("qfqday") or o.get("data",{}).get(symbol,{}).get("day")
        if not rows or len(rows)<250: raise RuntimeError("history insufficient")
        return rows
    rows=retry(f,4)
    return {"dates":[str(x[0]) for x in rows],"closes":[float(x[2]) for x in rows],"highs":[float(x[3]) for x in rows]}

def qq_quotes(cons):
    syms=[("sh" if s["market"]=="SH" else "sz")+s["code"] for s in cons]
    out={}
    for i in range(0,len(syms),35):
        batch=syms[i:i+35]
        def f():
            r=S.get("https://qt.gtimg.cn/q="+",".join(batch),timeout=20); r.raise_for_status()
            if not r.text.strip(): raise RuntimeError("empty quotes")
            return r.text
        txt=retry(f,4)
        for line in txt.splitlines():
            if '="' not in line: continue
            left,p=line.split('="',1); p=p.rstrip('";\r\n'); parts=p.split("~")
            if len(parts)>3:
                try:
                    price=float(parts[3])
                    if price>0: out[left.replace("v_","").strip()]=price
                except: pass
        time.sleep(.3)
    return out

def load_cache():
    try:return json.loads(CACHE.read_text(encoding="utf-8"))
    except:return {"date":"","stocks":{}}

def save_cache(c): CACHE.write_text(json.dumps(c,ensure_ascii=False),encoding="utf-8")

def ensure_hist(cons):
    c=load_cache(); today=datetime.now(TZ).date().isoformat(); refresh=c.get("date")!=today; sc=c.setdefault("stocks",{})
    ok=0
    for s in cons:
        old=sc.get(s["code"]); need=refresh or not old or len(old.get("closes",[]))<250
        if not need: ok+=1; continue
        sym=("sh" if s["market"]=="SH" else "sz")+s["code"]
        try:
            h=qq_hist(sym); sc[s["code"]]={"name":s["name"],"market":s["market"],**h}; ok+=1
        except Exception as e: print("history fail",s["code"],e)
        time.sleep(.45)
    if ok>=45:c["date"]=today
    save_cache(c); return c

def index_hist():
    start=(datetime.now(TZ)-timedelta(days=650)).strftime("%Y%m%d"); end=datetime.now(TZ).strftime("%Y%m%d")
    def f():
        d=ak.stock_zh_index_hist_csindex(symbol=INDEX,start_date=start,end_date=end)
        if d is None or len(d)<250: raise RuntimeError("index history unavailable")
        return d
    d=retry(f,5).sort_values("日期")
    c=pd.to_numeric(d["收盘"],errors="coerce").dropna().tolist()
    h=pd.to_numeric(d["最高"],errors="coerce").dropna().tolist()
    return str(pd.to_datetime(d.iloc[-1]["日期"]).date()),c,h,float(d.iloc[-1]["收盘"])

def main():
    cons=constituents(); print("constituents",len(cons))
    cache=ensure_hist(cons); quotes=qq_quotes(cons); print("quotes",len(quotes))
    rows=[]
    for s in cons:
        h=cache.get("stocks",{}).get(s["code"]); key=("sh" if s["market"]=="SH" else "sz")+s["code"]; q=quotes.get(key)
        if not h or q is None: continue
        try:
            m=metrics(h["closes"],h["highs"],q); m.update(code=s["code"],name=s["name"],market=s["market"]); m["score"]=score(m); rows.append(m)
        except: pass
    if len(rows)<40: raise RuntimeError(f"too few valid stock rows: {len(rows)}")
    date,ic,ih,il=index_hist(); im=metrics(ic,ih,il)
    now=datetime.now(TZ)
    OUT.write_text(json.dumps({"status":"ok","updated_at":now.strftime("%Y-%m-%d %H:%M:%S"),"market_date":date,"index":im,"stocks":rows,"count":len(rows)},ensure_ascii=False,indent=2),encoding="utf-8")
    print("SUCCESS",len(rows))
if __name__=="__main__": main()
