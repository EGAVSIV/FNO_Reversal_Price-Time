import streamlit as st
import json
import pathlib
import pandas as pd
import numpy as np
import talib as ta
from datetime import datetime, time
import datetime as dt
import swisseph as swe
from tvDatafeed import TvDatafeed, Interval
import streamlit.components.v1 as components

# ---------------- STREAMLIT INIT ----------------
st.set_page_config(page_title="FNO Reversal Dashboard", layout="wide", page_icon="🔮")

# TVDatafeed Initialization
@st.cache_resource
def get_tv_connection():
    return TvDatafeed()

tv = get_tv_connection()

# ---------------- SYMBOL UNIVERSE ----------------
SYMBOLS = ['NIFTY','BANKNIFTY','CNXFINANCE','CNXMIDCAP','NIFTYJR','RELIANCE','TCS','INFY','HDFCBANK','ICICIBANK']

# ---------------- ASTRO CONFIG ----------------
swe.set_sid_mode(swe.SIDM_LAHIRI)
LAT, LON = 19.07598, 72.87766
FLAGS = swe.FLG_SWIEPH | swe.FLG_SIDEREAL
START, END = (9, 15), (15, 30)

NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra","Punarvasu","Pushya","Ashlesha","Magha",
    "Purva Phalguni","Uttara Phalguni","Hasta","Chitra","Swati","Vishakha","Anuradha","Jyeshtha","Mula",
    "Purva Ashadha","Uttara Ashadha","Shravana","Dhanishtha","Shatabhisha","Purva Bhadrapada","Uttara Bhadrapada","Revati"
]
ZODIAC_SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
NAK_BIAS = {
    "Rohini":"Bullish / accumulation", "Mrigashira":"Trend friendly", "Punarvasu":"Recovery bounce",
    "Pushya":"Institutional strength", "Ardra":"Panic / crash risk", "Ashlesha":"Fake breakout"
}
PLANETS = {"Mars": swe.MARS, "Saturn": swe.SATURN, "Rahu": swe.MEAN_NODE, "Mercury": swe.MERCURY, "Venus": swe.VENUS}
ASPECTS = [0, 45, 60, 90, 120, 180]
ORB_DEG = 1.0
NAK_SIZE = 360/27
PADA_SIZE = NAK_SIZE/4

def jd_from_ist(d):
    d_utc = d - dt.timedelta(hours=5, minutes=30)
    return swe.julday(d_utc.year, d_utc.month, d_utc.day, d_utc.hour + d_utc.minute/60)

def lon(jd, planet):
    return swe.calc_ut(jd, planet, FLAGS)[0][0] % 360

def get_nak_pada(l):
    i = int(l // NAK_SIZE)
    pada = int(((l - i*NAK_SIZE) // PADA_SIZE) + 1)
    return NAKSHATRAS[i], pada

def angle(a, b):
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d

def get_ascendant(jd):
    ascmc, _ = swe.houses_ex(jd, LAT, LON, b'P', FLAGS)
    asc = ascmc[0] % 360
    return ZODIAC_SIGNS[int(asc // 30)]

def scan_astro(date, step=5):
    rows = []
    last_nak, last_pada, last_asc = None, None, None
    t = dt.datetime(date.year, date.month, date.day, START[0], START[1])
    end = dt.datetime(date.year, date.month, date.day, END[0], END[1])

    while t <= end:
        jd = jd_from_ist(t)
        m = lon(jd, swe.MOON)
        nak, pada = get_nak_pada(m)
        asc = get_ascendant(jd)

        if last_asc and asc != last_asc:
            rows.append({"Time": t.strftime("%H:%M"), "Event": "Ascendant Change", "Detail": f"{last_asc} -> {asc}"})
        if last_nak and nak != last_nak:
            rows.append({"Time": t.strftime("%H:%M"), "Event": "Nakshatra Change", "Detail": f"{last_nak} -> {nak}"})

        for pname, pid in PLANETS.items():
            p = lon(jd, pid)
            for asp in ASPECTS:
                if angle(m, (p - asp) % 360) <= ORB_DEG:
                    rows.append({"Time": t.strftime("%H:%M"), "Event": f"Moon-{pname}", "Detail": f"{asp}°"})

        last_asc, last_nak, last_pada = asc, nak, pada
        t += dt.timedelta(minutes=step)

    return nak, NAK_BIAS.get(nak, "Neutral"), rows

# ---------------- PRICE FUNCTIONS ----------------
def get_stock_data(symbol):
    df_w = tv.get_hist(symbol=symbol, exchange="NSE", interval=Interval.in_weekly, n_bars=2)
    df_d = tv.get_hist(symbol=symbol, exchange="NSE", interval=Interval.in_daily, n_bars=60)
    
    if df_w is None or df_d is None:
        return None
    
    w_close = float(df_w["close"].iloc[-1])
    d_close = float(df_d["close"].iloc[-1])
    
    atr_arr = ta.ATR(df_d["high"], df_d["low"], df_d["close"], timeperiod=10)
    atr_val = float(atr_arr.iloc[-1])
    
    return w_close, d_close, atr_val

def price_cycles(close_price, steps=[30, 60, 90, 120, 150]):
    res, sup = [], []
    up = down = close_price
    for s in steps:
        up += s
        down -= s
        res.append(up)
        sup.append(down)
    return res, sup

# ---------------- STREAMLIT SIDEBAR CONTROLS ----------------
st.sidebar.header("🕹️ Dashboard Controls")
selected_date = st.sidebar.date_input("Select Astro Date", dt.date.today())
selected_symbol = st.sidebar.selectbox("Select Stock Symbol", SYMBOLS)
preset_steps = st.sidebar.selectbox("Steps Preset", [[30,60,90,120,150], [3,6,9,12,15], [0.3,0.6,0.9,1.2,1.5]])

# ---------------- RUN PYTHON CALCULATIONS ----------------
# 1. Astro Calculations
nak_name, nak_bias, astro_events = scan_astro(selected_date)

# 2. Stock Price Calculations
stock_info = get_stock_data(selected_symbol)

if stock_info:
    w_close, d_close, atr_val = stock_info
    atr_pct = (atr_val / d_close) * 100
    r_raw, s_raw = price_cycles(w_close, steps=preset_steps)
    
    # Reclassification logic
    new_r = [val for val in r_raw if val > d_close]
    new_s = [val for val in r_raw if val <= d_close] + s_raw
    
    # Fill to 5 elements
    new_r = (new_r + [None]*5)[:5]
    new_s = (new_s + [None]*5)[:5]

    # 3. Assemble JSON Payload for JS Dashboard UI
    dashboard_payload = {
        "astro": {
            "nakshatra": nak_name,
            "bias": nak_bias,
            "events": astro_events
        },
        "sr": {
            "symbol": selected_symbol,
            "weekly_close": w_close,
            "last_close": d_close,
            "atr": atr_val,
            "atr_pct": atr_pct,
            "resistance": new_r,
            "support": new_s
        }
    }

    # 4. Inject JSON Payload into HTML Template
    html_file = pathlib.Path(__file__).parent / "dashboard.html"
    with open(html_file, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Inject calculated data directly into window.DASHBOARD_DATA global scope
    injected_js = f"<script>window.DASHBOARD_DATA = {json.dumps(dashboard_payload)};</script>"
    final_html = injected_js + html_content

    # Render inside Streamlit page layout
    components.html(final_html, height=800, scrolling=True)

else:
    st.error("Failed to fetch market data for selected symbol.")
