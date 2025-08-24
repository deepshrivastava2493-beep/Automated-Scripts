# !pip install --upgrade openai pandas requests lxml

import pandas as pd
import requests
from io import StringIO
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
from datetime import datetime
import os

# ---- CONFIG ----
DELIVERY_THRESHOLD = 85
openai_api_key = os.getenv("OPENAI_API_KEY")  # ← replace (or read from env)
sender = "deepshrivastava2493@gmail.com"
receivers = ["rockingdeep69@gmail.com"]
app_password = os.getenv("GMAIL_APP_PASSWORD") # Gmail App password; never your main password

# ---- Step 1: Fetch & parse delivery data ----
url = "https://www.moneycontrol.com/india/stockmarket/stock-deliverables/marketstatistics/indices/nifty-500-7.html"
headers = {"User-Agent": "Mozilla/5.0"}
response = requests.get(url, headers=headers, timeout=30)
response.raise_for_status()

df = pd.read_html(StringIO(response.text))[0]
df.columns = [col.strip() for col in df.columns]

# clean % and price (handles commas)
if "Last Price" in df.columns:
    df["Last Price"] = pd.to_numeric(
        df["Last Price"].astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce"
    )
df["Dely %"] = pd.to_numeric(
    df["Dely %"].astype(str).str.replace("%", "", regex=False).str.strip(),
    errors="coerce"
)
df = df.dropna(subset=["Dely %", "Last Price"])

# ---- Step 2: Filter high delivery stocks ----
high_delivery_df = df[df["Dely %"] >= DELIVERY_THRESHOLD]
stock_list = high_delivery_df[["Company Name", "Last Price", "Dely %"]].reset_index(drop=True)

# ---- Step 3: Full JSON prompt ----
def build_prompt(stock_name: str, last_price: float, delivery_pct: float, date_iso: str) -> str:
    return f"""
You are a stock swing trading assistant.
Analyze the following NSE stock for a potential 10–14 day swing trade using a DELIVERY-based strategy and return ONLY a strict JSON object.

KPIs required:
1. CMP (Current Market Price)
2. Delivery %
3. Upside Target (price & % gain) → must be realistic, based on:
   - Market Cap category (Large Cap: 3–5%, Mid Cap: 4–8%, Small Cap: 7–15%)
   - ATR (use ~2× ATR as a cap for the swing target range)
   - Nearest resistance levels
4. Downside Stop Loss (price & % fall) → based on nearest support + ATR (3–8% typical swing risk cap)
5. Risk–Reward Ratio
6. Support / Resistance levels
7. ATR (Average True Range in ₹ and %)
8. Technical Setup (trend bias)
9. Chart Pattern (if any)
10. Volume Trend (rising/falling/flat)
11. Relative Strength vs Sector/Index
12. Fundamentals (1–2 line summary)
13. Key Driver (institutional flows, sector trend, etc.)
14. Trade Success Probability (TSP%) → a single % score combining all KPIs for the next 10–14 days.

Constraints:
- Keep all numbers within realistic 10–14 day swing ranges.
- Do NOT suggest upside targets > 15% in 14 days.

Return JSON in this exact shape (keys must match exactly):
{{
  "meta": {{
    "stock": "<ticker_or_name>",
    "exchange": "NSE",
    "date": "{date_iso}",
    "market_cap_category": "Large Cap | Mid Cap | Small Cap"
  }},
  "kpis": {{
    "cmp": {last_price:.2f},
    "delivery_pct": {delivery_pct:.2f},
    "upside_target": {{"price_min": 0, "price_max": 0, "pct_min": 0, "pct_max": 0, "basis": ""}},
    "downside_stoploss": {{"price_min": 0, "price_max": 0, "pct_min": -1, "pct_max": -1, "basis": ""}},
    "risk_reward": {{"min": 0, "max": 0}},
    "levels": {{"support": [0, 0], "resistance": [0, 0]}},
    "atr": {{"value": 0, "pct_of_price": 0}},
    "technical_setup": "",
    "chart_pattern": "None",
    "volume_trend": "",
    "relative_strength": "",
    "fundamentals": "",
    "key_driver": "",
    "tsp": {{
      "probability_pct": 0,
      "weights": {{
        "delivery": 25,
        "risk_reward": 20,
        "atr_sr_alignment": 15,
        "volume_trend": 15,
        "relative_strength": 10,
        "technical_pattern": 15
      }},
      "notes": "Capped to realistic 10–14 day ranges; targets limited to <=15%"
    }}
  }},
  "trade_plan": {{
    "entry_trigger": {{"type": "breakout", "above_price": 0, "confirmation": "Close above level with volume > 1.5x 20D avg"}},
    "targets": [0, 0, 0],
    "stop_loss": 0,
    "position_size_pct_of_capital": 2.0,
    "management": "Trail SL to first entry after T1; partial book at T2"
  }},
  "disclaimer": "Illustrative values. Replace live metrics before trading."
}}

Stock: {stock_name}
Current price (CMP): ₹{last_price:.2f}
Delivery %: {delivery_pct:.2f}
""".strip()

# ---- Step 4: OpenAI + JSON parse (strict JSON) ----
client = OpenAI(api_key=openai_api_key)

def get_json_analysis(stock_row):
    today_iso = datetime.now().strftime("%Y-%m-%d")
    prompt = build_prompt(
        stock_name=stock_row["Company Name"],
        last_price=float(stock_row["Last Price"]),
        delivery_pct=float(stock_row["Dely %"]),
        date_iso=today_iso
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        response_format={"type": "json_object"},  # ← guarantees valid JSON
    )
    return json.loads(response.choices[0].message.content)

results = []
for _, stock_row in stock_list.iterrows():
    try:
        analysis = get_json_analysis(stock_row)
        # fill stock name if model leaves it blank
        analysis.setdefault("meta", {})["stock"] = analysis.get("meta", {}).get("stock") or stock_row["Company Name"]
        results.append(analysis)
    except Exception as e:
        print(f"Error with {stock_row['Company Name']}: {e}")

# ---- Step 5: Emoji + two-column KPI rendering (per-stock card) ----
def render_vertical_html(results: list, date_str: str) -> str:
    def rng(vmin, vmax, pmin=None, pmax=None):
        a = f"₹{vmin}" if vmin not in (None, "") else ""
        b = f"₹{vmax}" if vmax not in (None, "") else ""
        line1 = " – ".join([x for x in (a, b) if x])
        p1 = f"{pmin}%" if pmin not in (None, "") else ""
        p2 = f"{pmax}%" if pmax not in (None, "") else ""
        line2 = f"({p1} – {p2})" if (p1 or p2) else ""
        return line1, line2

    def tsp_pill(p):
        try: p = float(p)
        except: return f"{p}%"
        if p >= 75:  color, bg = "#137333", "#e6f4ea"
        elif p >= 55: color, bg = "#8a6d3b", "#fff8e1"
        else:         color, bg = "#a50e0e", "#fce8e6"
        return f"<span style='background:{bg};color:{color};padding:2px 8px;border-radius:12px;font-weight:700'>{int(p)}%</span>"

    style = """
    <style>
      body{font-family:Arial,Helvetica,sans-serif;}
      .wrap{max-width:760px;margin:0 auto;}
      .title{font-weight:800;font-size:20px;color:#222;margin:0 0 6px}
      .hl{background:#fff3b0;padding:2px 6px;border-radius:6px}
      .muted{color:#666;font-size:12px;margin:0 0 12px 0}
      .card{border:2px solid #000;border-radius:10px;padding:14px 16px;margin:14px 0;background:#fff;box-shadow:2px 3px 8px #d1d9ee}
      .head{font-weight:700;color:#1f2937;font-size:15px;margin-bottom:6px}
      .cap{color:#777;font-size:12px;margin-left:6px}
      table.kpi{border-collapse:collapse;width:100%;border:1px solid #000}
      table.kpi td{border:1px solid #000;padding:8px 10px;vertical-align:top;font-size:14px;background:#fff}
      table.kpi td.l{width:230px;white-space:nowrap}
      .sml{color:#777;font-size:12px}
    </style>
    """

    header = f"""
    <h2>📈✨ High Delivery Stock Analysis (Nifty 500) ✨</h2>
    <div class='muted'>Date (IST): {date_str} • Filter: Delivery ≥ {DELIVERY_THRESHOLD}%</div><br>
    """
    
    cards = []
    for item in results:
        meta = item.get("meta", {})
        k = item.get("kpis", {})
        tp = item.get("trade_plan", {}) or {}

        stock = meta.get("stock", "")
        mcap = meta.get("market_cap_category", "")

        cmp_val = k.get("cmp", "")
        dely = k.get("delivery_pct", "")
        ut = k.get("upside_target", {}) or {}
        sl = k.get("downside_stoploss", {}) or {}
        rr = k.get("risk_reward", {}) or {}
        atr = k.get("atr", {}) or {}
        levels = k.get("levels", {}) or {}
        setup = k.get("technical_setup", "")
        patt = k.get("chart_pattern", "")
        vol = k.get("volume_trend", "")
        rs = k.get("relative_strength", "")
        funda = k.get("fundamentals", "")
        keyd = k.get("key_driver", "")
        tsp = (k.get("tsp", {}) or {}).get("probability_pct", "")

        ut1, ut2 = rng(ut.get("price_min"), ut.get("price_max"), ut.get("pct_min"), ut.get("pct_max"))
        sl1, sl2 = rng(sl.get("price_min"), sl.get("price_max"), sl.get("pct_min"), sl.get("pct_max"))
        supports = ", ".join(map(str, levels.get("support", []) or []))
        resist   = ", ".join(map(str, levels.get("resistance", []) or []))

        entry = tp.get("entry_trigger", {}) or {}
        targets = ", ".join("₹"+str(x) for x in (tp.get("targets") or []))
        plan_html = f"""Entry: {entry.get('type','')} above ₹{entry.get('above_price','')}<br>
        Confirm: {entry.get('confirmation','')}<br>
        Targets: {targets}<br>
        Stop Loss: ₹{tp.get('stop_loss','')}<br>
        Sizing: {tp.get('position_size_pct_of_capital','2.0')}%<br>
        Management: {tp.get('management','')}"""

        card = f"""
        <div class="card">
          <div class="head">🟢 {stock} <span class="cap">{mcap}</span></div>
          <table class="kpi" role="presentation">
            <tr><td class="l">🍏 <b>CMP</b></td><td>₹{cmp_val}</td></tr>
            <tr><td class="l">📒 <b>Delivery %</b></td><td>{dely}%</td></tr>
            <tr><td class="l">📌 <b>Upside Target</b></td><td>{ut1}<br><span class="sml">{ut2}</span><br><span class="sml">{ut.get('basis','')}</span></td></tr>
            <tr><td class="l">🛑 <b>Stop Loss</b></td><td>{sl1}<br><span class="sml">{sl2}</span><br><span class="sml">{sl.get('basis','')}</span></td></tr>
            <tr><td class="l">📏 <b>Risk/Reward</b></td><td>{rr.get('min','')} – {rr.get('max','')}</td></tr>
            <tr><td class="l">📶 <b>ATR</b></td><td>₹{atr.get('value','')} ({atr.get('pct_of_price','')}%)</td></tr>
            <tr><td class="l">📍 <b>Support / Resistance</b></td><td>S: {supports}<br>R: {resist}</td></tr>
            <tr><td class="l">⚡ <b>Setup</b></td><td>{setup}</td></tr>
            <tr><td class="l">📊 <b>Chart Pattern</b></td><td>{patt}</td></tr>
            <tr><td class="l">📈 <b>Volume Trend</b></td><td>{vol}</td></tr>
            <tr><td class="l">🧭 <b>Rel. Strength</b></td><td>{rs}</td></tr>
            <tr><td class="l">📚 <b>Fundamentals</b></td><td>{funda}</td></tr>
            <tr><td class="l">🎯 <b>Key Driver</b></td><td>{keyd}</td></tr>
            <tr><td class="l">🏁 <b>TSP%</b></td><td>{tsp_pill(tsp)}</td></tr>
            <tr><td class="l">🧭 <b>Trade Plan</b></td><td>{plan_html}</td></tr>
          </table>
        </div>
        """
        cards.append(card)

    footer = "<div class='muted'>Automated alert • Educational use only.</div></div>"
    return f"<html><body>{style}{header}{''.join(cards)}{footer}</body></html>"

# ---- Step 6: Compose message HTML ----
date_str = datetime.now().strftime("%Y-%m-%d %H:%M IST")
message_body = render_vertical_html(results, date_str)

# ---- Step 7: Send Email ----
msg = MIMEMultipart("alternative")
msg["Subject"] = f"✨ High Delivery & Analysis Alert - {datetime.now().date()} "
msg["From"] = sender
msg["To"] = ", ".join(receivers)
msg.attach(MIMEText(message_body, "html", "utf-8"))

with smtplib.SMTP("smtp.gmail.com", 587) as server:
    server.starttls()
    server.login(sender, app_password)
    server.sendmail(sender, receivers, msg.as_string())

print("✅ Email sent with emoji two-column KPI cards.")

