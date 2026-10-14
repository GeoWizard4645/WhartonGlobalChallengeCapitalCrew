# Downloads daily adjusted closes from Yahoo into data/TICKER.csv (plus the T-bill rate for cash)
# Run: python3 fetch_data.py
import csv
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import config

# period1/period2 (not range=max) so Yahoo returns DAILY bars; range=max quietly hands back monthly ones
URL = "https://query1.finance.yahoo.com/v8/finance/chart/{}?period1=315532800&period2={}&interval=1d"
NOW = int(time.time())

os.makedirs(config.DATA_DIR, exist_ok=True)

for ticker in config.ALL_TICKERS + [config.CASH_TICKER]:
    try:
        req = urllib.request.Request(URL.format(urllib.parse.quote(ticker), NOW), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            result = json.load(resp)["chart"]["result"][0]
        times = result["timestamp"]
        ind = result["indicators"]
        # funds/ETFs have adjusted close (dividends reinvested); the T-bill index only has plain close
        closes = ind["adjclose"][0]["adjclose"] if "adjclose" in ind else ind["quote"][0]["close"]
    except Exception as e:
        print("FAILED", ticker, "-", e, "(swap this ticker in config.py)")
        continue

    path = os.path.join(config.DATA_DIR, ticker.lstrip("^") + ".csv")
    rows = []
    for t, c in zip(times, closes):
        if c is not None:
            rows.append([datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d"), c])
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        w.writerows(rows)
    years = (int(rows[-1][0][:4]) - int(rows[0][0][:4])) or 1
    note = "" if len(rows) / years > 150 else "   <-- NOT DAILY, model needs daily data"
    print(f"{ticker:8}{len(rows):7} rows  {rows[0][0]} to {rows[-1][0]}{note}")

print("\nThe history the model can use starts at the LATEST first date above (the youngest ticker).")
