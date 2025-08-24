#!pip install --upgrade openai

import pandas as pd
import requests
from io import StringIO
import openai
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
from datetime import datetime

# ---- CONFIG ----
DELIVERY_THRESHOLD = 85
openai_api_key = "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"
sender = "deepshrivastava2493@gmail.com"
receivers = ["rockingdeep69@gmail.com"]
app_password = "sjkynqkenfpfdvyo"  # Gmail App password; never your main password

# ---- Step 1: Fetch & parse delivery data ----
url = "https://www.moneycontrol.com/india/stockmarket/stock-deliverables/marketstatistics/indices/nifty-500-7.html"
headers = { "User-Agent": "Mozilla/5.0" }
response = requests.get(url, headers=headers, timeout=30)
response.raise_for_status()
df = pd.read_html(StringIO(response.text))[0]
df.columns = [col.strip() for col in df.columns]
df["Dely %"] = pd.to_numeric(df["Dely %"].astype(str).str.replace("%", "").str.strip(), errors="coerce")
df = df.dropna(subset=["Dely %"])

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
    "upside_target": {{
      "price_min": <number>,
      "price_max": <number>,
      "pct_min": <number>,
      "pct_max": <number>,
      "basis": "<text>"
    }},
    "downside_stoploss": {{
      "price_min": <number>,
      "price_max": <number>,
      "pct_min": <number>,   // negative
      "pct_max": <number>,   // negative
      "basis": "<text>"
    }},
    "risk_reward": {{
      "min": <number>,
      "max": <number>
    }},
    "levels": {{
      "support": [<number>, <number>],
      "resistance": [<number>, <number>]
    }},
    "atr": {{
      "value": <number>,
      "pct_of_price": <number>
    }},
    "technical_setup": "<text>",
    "chart_pattern": "<text or 'None'>",
    "volume_trend": "<text>",
    "relative_strength": "<text>",
    "fundamentals": "<text>",
    "key_driver": "<text>",
    "tsp": {{
      "probability_pct": <integer_between_0_and_100>,
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
    "entry_trigger": {{
      "type": "breakout | pullback | range",
      "above_price": <number>,
      "confirmation": "Close above level with volume > 1.5x 20D avg"
    }},
    "targets": [<number>, <number>, <number>],
    "stop_loss": <number>,
    "position_size_pct_of_capital": 2.0,
    "management": "Trail SL to first entry after T1; partial book at T2"
  }},
  "disclaimer": "Illustrative values. Replace live metrics before trading."
}}

Stock: {stock_name}
Current price (CMP): ₹{last_price:.2f}
Delivery %: {delivery_pct:.2f}
""".strip()

# ---- Step 4: OpenAI + JSON parse ----
client = openai.OpenAI(api_key=openai_api_key)

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
        temperature=0.1
    )
    resp_txt = response.choices[0].message.content
    json_start = resp_txt.find('{')
    json_end = resp_txt.rfind('}')
    json_str = resp_txt[json_start:json_end+1]
    return json.loads(json_str)

results = []
for _, stock_row in stock_list.iterrows():
    try:
        analysis = get_json_analysis(stock_row)
        results.append(analysis)
    except Exception as e:
        print(f"Error with {stock_row['Company Name']}: {e}")

# ---- Step 5: Render VERTICAL HTML blocks with enhanced style ----
def render_vertical_html(results: list, date_str: str) -> str:
    style = """
    <style>
      .stock-block {
        margin-bottom: 36px;
        border: 2px solid #000000;  /* darker and thicker for better visibility */
        border-radius: 8px;
        padding: 18px 22px 14px 22px;
        background: #f7faff;
        box-shadow: 2px 3px 8px #d1d9ee;
      }
      .stock-title {
        font-size: 18px;
        font-weight: bold;
        color: #0b3d91;
        margin-bottom: 8px;
      }
      .muted {
        color: #666;
        font-size: 11px;
        margin-bottom: 12px;
      }
      table.kpi-table {
        border-collapse: collapse;
        width: 100%;
        margin-top: 16px;
        font-family: Arial, sans-serif;
        border: 1px solid #000000 !important; /* table border */
      }
      table.kpi-table td, table.kpi-table th {
        padding: 7px 10px;
        border: 1px solid #000000 !important; /* cell borders */
        font-size: 14px;
        background: #fff;
        vertical-align: top;
      }
      table.kpi-table tr:first-child td {
        background: #d9e0f7;
        font-weight: bold;
      }
      /* rest of your CSS */
    </style>
    """

    
    header = f"""
    <h2>📈✨ High Delivery Stock Analysis (Nifty 500) ✨</h2>
    <div class='muted'>Date (IST): {date_str} • Filter: Delivery ≥ {DELIVERY_THRESHOLD}%</div><br>
    """
    
    blocks = []
    for item in results:
        meta = item.get("meta", {})
        k = item.get("kpis", {})
        tp = item.get("trade_plan", {})

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
        tsp = (k.get("tsp", {}) or {}).get("probability_pct", "")

        css = "neutral"
        try:
            t = float(tsp)
            css = "bull" if t >= 75 else "neutral" if t >= 55 else "bear"
        except:
            pass

        plan_entry = tp.get("entry_trigger", {})
        plan_targets = tp.get("targets", [])
        plan_sl = tp.get("stop_loss", "")

        blocks.append(f"""
        <div class="stock-block">
          <div class="stock-title">✅ {stock} <span class="muted">{mcap}</span></div><br>
          <table class="kpi-table" role="presentation">
            <tr><td><span class="symbol">💰</span><strong>CMP</strong></td><td>₹{cmp_val}</td></tr>
            <tr><td><span class="symbol">📊</span><strong>Delivery %</strong></td><td>{dely}%</td></tr>
            <tr><td><span class="symbol">🚀</span><strong>Upside Target</strong></td><td>₹{ut.get('price_min','')} – ₹{ut.get('price_max','')}<br>({ut.get('pct_min','')}% – {ut.get('pct_max','')}%)<br><span class='muted'>{ut.get('basis','')}</span></td></tr>
            <tr><td><span class="symbol">🛑</span><strong>Stop Loss</strong></td><td>₹{sl.get('price_min','')} – ₹{sl.get('price_max','')}<br>({sl.get('pct_min','')}% – {sl.get('pct_max','')}%)<br><span class='muted'>{sl.get('basis','')}</span></td></tr>
            <tr><td><span class="symbol">⚖️</span><strong>Risk/Reward</strong></td><td>{rr.get('min','')} – {rr.get('max','')}</td></tr>
            <tr><td><span class="symbol">📉</span><strong>ATR</strong></td><td>₹{atr.get('value','')} ({atr.get('pct_of_price','')}%)</td></tr>
            <tr><td><span class="symbol">📈</span><strong>Support / Resistance</strong></td><td>S: {', '.join(map(str, levels.get('support', [])))}<br>R: {', '.join(map(str, levels.get('resistance', [])))}</td></tr>
            <tr><td><span class="symbol">⚡</span><strong>Setup</strong></td><td>{setup}</td></tr>
            <tr><td><span class="symbol">📊</span><strong>Chart Pattern</strong></td><td>{k.get('chart_pattern','')}</td></tr>
            <tr><td><span class="symbol">📈</span><strong>Volume Trend</strong></td><td>{k.get('volume_trend','')}</td></tr>
            <tr><td><span class="symbol">⭐</span><strong>Rel. Strength</strong></td><td>{k.get('relative_strength','')}</td></tr>
            <tr><td><span class="symbol">📚</span><strong>Fundamentals</strong></td><td>{k.get('fundamentals','')}</td></tr>
            <tr><td><span class="symbol">🚩</span><strong>Key Driver</strong></td><td>{k.get('key_driver','')}</td></tr>
            <tr><td><span class="symbol">🎯</span><strong>TSP%</strong></td><td><span class="pill {css}">{tsp}%</span></td></tr>
            <tr>
              <td valign="top"><span class="symbol">🗺️</span><strong>Trade Plan</strong></td>
              <td>
                Entry: {plan_entry.get('type','')} above ₹{plan_entry.get('above_price','')}<br>
                Confirm: {plan_entry.get('confirmation','')}<br>
                Targets: {', '.join('₹'+str(x) for x in plan_targets)}<br>
                Stop Loss: ₹{plan_sl}<br>
                Sizing: {tp.get('position_size_pct_of_capital', '2.0')}%<br>
                Management: {tp.get('management', '')}
              </td>
            </tr>
          </table>
        </div>
        """)

    return f"<html><body>{style}{header}{''.join(blocks)}<p class='muted'>Automated alert • Educational use only.</p></body></html>"

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

print("✅ Email sent with enhanced vertical JSON-based stock analysis.")
