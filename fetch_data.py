# Downloads daily adjusted closes into data/TICKER.csv (plus the T-bill rate for cash)
# Needs the yfinance library (the only thing in this project that isn't standard library):
#   pip3 install yfinance
# Run: python3 fetch_data.py
import csv
import os

import yfinance as yf

import config

os.makedirs(config.DATA_DIR, exist_ok=True)

for ticker in config.ALL_TICKERS + [config.CASH_TICKER]:
    try:
        # auto_adjust=True = prices with dividends reinvested (total return); the T-bill index has no adjustment
        history = yf.Ticker(ticker).history(period="max", interval="1d", auto_adjust=True)
        closes = history["Close"].dropna()
        if len(closes) == 0:
            raise ValueError("no data came back")
    except Exception as e:
        print("FAILED", ticker, "-", e, "(swap this ticker in config.py)")
        continue

    path = os.path.join(config.DATA_DIR, ticker.lstrip("^") + ".csv")
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        for day, c in closes.items():
            w.writerow([day.strftime("%Y-%m-%d"), c])

    first, last = closes.index[0].strftime("%Y-%m-%d"), closes.index[-1].strftime("%Y-%m-%d")
    years = (int(last[:4]) - int(first[:4])) or 1
    note = "" if len(closes) / years > 150 else "   <-- NOT DAILY, model needs daily data"
    print(f"{ticker:8}{len(closes):7} rows  {first} to {last}{note}")

print("\nThe history the model can use starts at the LATEST first date above (the youngest ticker).")
