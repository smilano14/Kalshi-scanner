import datetime as dt
import io
import sqlite3
import pandas as pd
import streamlit as st
import scanner

st.set_page_config(page_title='Kalshi Research Scanner', page_icon='📊', layout='wide')
st.title('📊 Kalshi Research Scanner')
st.caption('Read-only market research and simulated trades. No real orders are placed.')
st.warning('Prototype: scores measure liquidity, NOT a profitable trading edge. Cloud-local SQLite data may disappear when the app restarts. Export CSV backups regularly.')
with sqlite3.connect(scanner.DB) as db:
    scanner.init(db)

market_tab, paper_tab, about_tab = st.tabs(['🔎 Markets', '🧪 Paper trades', 'ℹ️ About'])
with market_tab:
    st.subheader('Scan current markets')
    c1,c2 = st.columns(2)
    with c1: limit = st.select_slider('Market records to sample', options=[200,500,1000,2000],value=1000)
    with c2: max_books = st.slider('Order books to inspect',10,100,40,10)
    keywords = st.text_input('Optional keywords (space-separated)', placeholder='Bitcoin Gold Silver')
    if st.button('Run scan now',type='primary',use_container_width=True):
        with st.spinner('Fetching live Kalshi quotes…'):
            try:
                with sqlite3.connect(scanner.DB) as db:
                    scanner.init(db)
                    scanner.scan(db,limit,max_books,keywords.split())
                st.success('Scan completed. Results below.')
            except Exception as exc: st.error(f'Scan failed: {exc}')
    with sqlite3.connect(scanner.DB) as db:
        df = pd.read_sql_query('SELECT * FROM snapshots WHERE ts=(SELECT MAX(ts) FROM snapshots) ORDER BY score DESC LIMIT 100',db)
    if not df.empty:
        st.caption(f'Last scan: {df.ts.iloc[0]} (UTC) · {len(df)} qualifying markets')
        st.dataframe(df[['ticker','title','yes_bid','yes_ask','spread','bid_qty','ask_qty','score']],hide_index=True,use_container_width=True)
        st.download_button('Download scan CSV',df.to_csv(index=False),'kalshi_scan.csv','text/csv')
    else: st.info('No scan data yet. Tap Run scan now. A scan may return no matches.')
with paper_tab:
    st.subheader('Manual simulated trades')
    st.caption('Quotes are fetched live. These simulated fills assume displayed top-of-book liquidity and are not guaranteed executable.')
    with st.form('buy'):
        ticker=st.text_input('Exact Kalshi market ticker').strip().upper()
        side=st.selectbox('Side',['yes','no'])
        qty=st.number_input('Contracts',min_value=1,max_value=1000,value=3)
        submitted=st.form_submit_button('Paper buy (no real money)')
    if submitted:
        try:
            with sqlite3.connect(scanner.DB) as db:
                scanner.init(db);scanner.paper_buy(db,ticker,side,int(qty))
            st.success('Paper position recorded.')
        except Exception as exc: st.error(str(exc))
    with sqlite3.connect(scanner.DB) as db:
        df=pd.read_sql_query('SELECT * FROM paper ORDER BY id DESC',db)
    if not df.empty:
        st.dataframe(df,hide_index=True,use_container_width=True)
        st.download_button('Download paper ledger CSV',df.to_csv(index=False),'kalshi_paper_ledger.csv','text/csv')
        open_ids=df.loc[df.status=='OPEN','id'].astype(int).tolist()
        if open_ids:
            trade_id=st.selectbox('Open position to paper-sell',open_ids)
            if st.button('Paper sell selected position'):
                try:
                    with sqlite3.connect(scanner.DB) as db:scanner.paper_sell(db,int(trade_id))
                    st.success('Simulated exit recorded. Refresh to see the updated ledger.')
                except Exception as exc:st.error(str(exc))
        closed=df[df.status=='CLOSED'].copy()
        if not closed.empty:
            closed['pnl']=closed.qty*(closed.exit-closed.entry)-closed.entry_fee-closed.exit_fee
            c1,c2,c3=st.columns(3)
            c1.metric('Closed paper trades',len(closed))
            c2.metric('Estimated net P/L',f'${closed.pnl.sum():.2f}')
            c3.metric('Win rate',f'{(closed.pnl>0).mean():.0%}')
    else:st.info('No paper trades yet.')
with about_tab:
    st.markdown('''**Scope:** The scanner samples public open markets, filters for expiration within two hours, then ranks order books by spread, depth and time remaining. It does not predict outcomes.\n\n**Important limitations:** The API order book is a snapshot; fills may slip or fail. Fees are estimates and may differ by market. No automatic settlement, background scheduling, independent commodity feed, or validated predictive model. Cloud-local SQLite data is not durable.\n\n**Safety:** No Kalshi credentials or deposits are needed. This application never submits a real trade.''')
