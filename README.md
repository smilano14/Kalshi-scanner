# Kalshi Cloud Scanner v0.2

A read-only, on-demand Streamlit dashboard using Kalshi public API market data. No real trading.

## Deploy on Streamlit Community Cloud

1. Create a **private** GitHub repository, e.g. `kalshi-research-scanner`.
2. Upload `app.py`, `scanner.py`, and `requirements.txt` to the repository root. Do not upload credentials or local database files.
3. Visit https://share.streamlit.io/ and sign in with GitHub.
4. Choose **Create app** / **Deploy**, select your repository and branch, and set the entrypoint to `app.py`.
5. Deploy and open the resulting URL on your phone; use **Add to Home screen** in your browser.
6. Use **Run scan now**. Paper trades are manual simulations only.

## Important

- Streamlit Community Cloud apps may sleep and restart. The included SQLite database is **not durable**. Download CSVs frequently; this is not suitable for reliable long-term performance tracking without external storage.
- This version does not scan in the background or generate notifications.
- Rankings are **liquidity scores**, not predicted profits or probability edges.
- Scanner currently samples the first N open markets and may miss the desired 15-minute gold/silver/BTC markets.
- Order-book snapshots and estimated fees are not guaranteed execution prices.
- Use paper trading only until data capture, independent pricing, market coverage, storage, and out-of-sample evaluation are improved.
- This prototype has passed syntax checks but has not been deployed or live-tested against the Kalshi API.

Local test: `pip install -r requirements.txt && streamlit run app.py`
