#!/usr/bin/env python3
"""Read-only Kalshi market scanner and conservative manual paper-trading ledger."""
import argparse, datetime as dt, json, math, sqlite3, time, urllib.parse, urllib.request
from pathlib import Path

BASE='https://external-api.kalshi.com/trade-api/v2'
DB=Path(__file__).with_name('scanner.sqlite3')

def get(path, params=None):
    url=BASE+path+('?' + urllib.parse.urlencode(params) if params else '')
    req=urllib.request.Request(url,headers={'User-Agent':'KalshiResearchScanner/0.1'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=15) as r: return json.load(r)
        except Exception:
            if attempt==2: raise
            time.sleep(1+attempt)

def init(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS snapshots (ts TEXT, ticker TEXT, title TEXT, close_time TEXT, yes_bid REAL, yes_ask REAL, bid_qty REAL, ask_qty REAL, spread REAL, score REAL, PRIMARY KEY(ts,ticker));
    CREATE TABLE IF NOT EXISTS paper (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT, side TEXT, qty INTEGER, entry REAL, entry_fee REAL, entry_ts TEXT, exit REAL, exit_fee REAL, exit_ts TEXT, status TEXT DEFAULT 'OPEN');''')

def number(x):
    try: return float(x)
    except (ValueError,TypeError): return None

def orderbook(ticker):
    d=get('/markets/'+urllib.parse.quote(ticker,safe='')+'/orderbook')
    book=d.get('orderbook_fp',{})
    def levels(key, legacy):
        if key in book:
            return sorted([(float(p),float(q)) for p,q in book[key]],reverse=True)
        old=d.get('orderbook',{}).get(legacy,[])
        return sorted([(float(p)/100,float(q)) for p,q in old],reverse=True)
    yes=levels('yes_dollars','yes'); no=levels('no_dollars','no')
    # Binary YES ask is 1 - best NO bid. A quote is unavailable if the opposing bid is absent.
    return {'yes_bid':yes[0][0] if yes else None,'yes_ask':round(1-no[0][0],4) if no else None,
            'bid_qty':yes[0][1] if yes else 0,'ask_qty':no[0][1] if no else 0}

def fee(price, qty, multiplier=1):
    # July 2026 standard taker formula; excludes market-specific overrides.
    return math.ceil((0.07*multiplier*qty*price*(1-price))*10000-1e-10)/10000

def score(q, minutes):
    if q['yes_bid'] is None or q['yes_ask'] is None: return None
    spread=q['yes_ask']-q['yes_bid']
    if spread<0 or spread>0.20: return None
    depth=min(q['bid_qty'],q['ask_qty'])
    # Liquidity and spread ranking only: NOT a predicted edge or profit probability.
    return round(max(0,100-600*spread)+min(20,math.log1p(depth)*3)+(10 if 2<=minutes<=30 else 0),1)

def parse_time(s):
    if not s:return None
    return dt.datetime.fromisoformat(s.replace('Z','+00:00'))

def scan(db, limit, max_books, filter_text):
    now=dt.datetime.now(dt.timezone.utc)
    markets=[]; cursor=None
    while len(markets)<limit:
        params={'status':'open','limit':min(200,limit-len(markets))}
        if cursor: params['cursor']=cursor
        d=get('/markets',params)
        markets.extend(d.get('markets',[]));cursor=d.get('cursor')
        if not cursor or not d.get('markets'):break
    filtered=[]
    for m in markets:
        title=(m.get('title') or '')+' '+(m.get('subtitle') or '')+' '+m.get('ticker','')
        if filter_text and not any(word.lower() in title.lower() for word in filter_text):continue
        close=parse_time(m.get('close_time') or m.get('expected_expiration_time'))
        if close is None:continue
        minutes=(close-now).total_seconds()/60
        if minutes<=0 or minutes>120:continue
        filtered.append((minutes,m))
    filtered.sort(key=lambda x:x[0])
    stamp=now.isoformat(); rows=[]
    for minutes,m in filtered[:max_books]:
        ticker=m['ticker']
        try:q=orderbook(ticker)
        except Exception as exc:
            print('Skipping',ticker, str(exc)[:100]);continue
        s=score(q,minutes)
        if s is None:continue
        spread=round(q['yes_ask']-q['yes_bid'],4)
        db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?)',
            (stamp,ticker,m.get('title',''),m.get('close_time'),q['yes_bid'],q['yes_ask'],q['bid_qty'],q['ask_qty'],spread,s))
        rows.append((s,minutes,ticker,q['yes_bid'],q['yes_ask'],spread,min(q['bid_qty'],q['ask_qty'])))
        time.sleep(.12)
    db.commit();rows.sort(reverse=True)
    print('Scanned',len(markets),'market records;',len(rows),'qualified orderbooks. Scores measure liquidity, not edge.')
    print(' SCORE  MIN LEFT  TICKER                                      BID     ASK   SPREAD   DEPTH')
    for s,mins,t,b,a,sp,depth in rows[:20]:
        print(f'{s:6.1f} {mins:8.1f}  {t[:43]:43} {b:6.3f}  {a:6.3f}  {sp:6.3f}  {depth:6.0f}')
    if not rows:print('No matches in this sample. Increase --limit or remove --keywords.')

def quote(db,ticker):
    q=orderbook(ticker)
    if q['yes_bid'] is None or q['yes_ask'] is None:raise ValueError('No two-sided quote available')
    return q

def paper_buy(db,ticker,side,qty):
    q=quote(db,ticker)
    price=q['yes_ask'] if side=='yes' else round(1-q['yes_bid'],4)
    depth=q['ask_qty'] if side=='yes' else q['bid_qty']
    if qty>depth:raise ValueError(f'Insufficient displayed top-of-book depth ({depth})')
    if not 0<price<1:raise ValueError('Invalid entry price')
    f=fee(price,qty)
    db.execute('INSERT INTO paper(ticker,side,qty,entry,entry_fee,entry_ts,status) VALUES(?,?,?,?,?,?,?)',
               (ticker,side,qty,price,f,dt.datetime.now(dt.timezone.utc).isoformat(),'OPEN'))
    db.commit();print(f'PAPER BUY {qty} {side.upper()} {ticker} at ${price:.4f}; fee estimate ${f:.4f}; debit ${price*qty+f:.4f}')

def paper_sell(db,id):
    row=db.execute('SELECT ticker,side,qty,entry,entry_fee,status FROM paper WHERE id=?',(id,)).fetchone()
    if not row or row[5]!='OPEN':raise ValueError('Paper trade not found or already closed')
    ticker,side,qty,entry,entry_fee,_=row;q=quote(db,ticker)
    price=q['yes_bid'] if side=='yes' else round(1-q['yes_ask'],4)
    depth=q['bid_qty'] if side=='yes' else q['ask_qty']
    if qty>depth:raise ValueError('Insufficient displayed top-of-book depth to close')
    f=fee(price,qty); pnl=qty*(price-entry)-entry_fee-f
    db.execute('UPDATE paper SET exit=?,exit_fee=?,exit_ts=?,status=? WHERE id=?',
               (price,f,dt.datetime.now(dt.timezone.utc).isoformat(),'CLOSED',id));db.commit()
    print(f'PAPER SELL #{id} at ${price:.4f}; estimated net P/L ${pnl:+.4f}')

def report(db):
    rows=db.execute('SELECT id,ticker,side,qty,entry,entry_fee,exit,exit_fee,status FROM paper ORDER BY id').fetchall()
    pnl=0;closed=0;wins=0
    for id,ticker,side,qty,entry,ef,exit,xf,status in rows:
        realized=qty*(exit-entry)-ef-xf if status=='CLOSED' else None
        if realized is not None:pnl+=realized;closed+=1;wins+=realized>0
        print(f'#{id} {status:6} {side.upper():3} {qty:3} {ticker[:38]:38} P/L {realized if realized is not None else "unrealized":}')
    print(f'Closed: {closed}; wins: {wins}; net estimated P/L: ${pnl:+.4f}')
    print('WARNING: quotes are snapshots; paper fills are optimistic and exclude slippage, latency, and market-specific fees.')

def main():
    p=argparse.ArgumentParser(description='Read-only Kalshi scanner with manual paper trades')
    sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('scan');a.add_argument('--limit',type=int,default=1000);a.add_argument('--max-books',type=int,default=60);a.add_argument('--keywords',nargs='*',default=[])
    a=sub.add_parser('buy');a.add_argument('ticker');a.add_argument('side',choices=['yes','no']);a.add_argument('qty',type=int)
    a=sub.add_parser('sell');a.add_argument('id',type=int)
    sub.add_parser('report')
    args=p.parse_args()
    with sqlite3.connect(DB) as db:
        init(db)
        if args.cmd=='scan':scan(db,args.limit,args.max_books,args.keywords)
        elif args.cmd=='buy':
            if args.qty<=0:raise ValueError('Quantity must be positive')
            paper_buy(db,args.ticker,args.side,args.qty)
        elif args.cmd=='sell':paper_sell(db,args.id)
        else:report(db)
if __name__=='__main__':main()
