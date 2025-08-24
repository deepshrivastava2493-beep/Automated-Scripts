#!/usr/bin/env python3
# High-Delivery Swing Mailer (GitHub-friendly)
# - Scrapes Moneycontrol (Nifty 500 deliverables)
# - Filters high-delivery stocks
# - Calls OpenAI (gpt-4o-mini) to produce strict JSON analysis
# - Renders HTML email; optional email send via Gmail SMTP

import os, sys, time, json
from datetime import datetime
from io import StringIO

import requests
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from openai import OpenAI
from dotenv import load_dotenv

# -----------------------------
# Load .env (if present)
# -----------------------------
load_dotenv()

# -----------------------------
# Config (from ENV with defaults)
# -----------------------------
URL = os.getenv("MC_URL", "https://www.moneycontrol.com/india/stockmarket/stock-deliverables/marketstatistics/indices/nifty-500-7.html")
DELIVERY_THRESHOLD = float(os.getenv("DELIVERY_THRESHOLD", "85"))
MAX_STOCKS = int(os.getenv("MAX_STOCKS", "6"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.15"))
API_RETRY = int(os.getenv("API_RETRY", "3"))
API_RETRY_SLEEP = float(os.getenv("API_RETRY_SLEEP", "2.0"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "40"))
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

SENDER_EMAIL = os.getenv("SENDER_EMAIL", "")
RECEIVER_EMAILS = [e.strip() for e in os.getenv("RECEIVER_EMAILS", "").split(",") if e.strip()]
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

HEADERS = {
    "User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.moneycontrol.com/",
    "Connection": "keep-alive",
}

# -----------------------------
# Helpers
# -----------------------------
def log(msg: str):
    print(msg, flush=True)

def ensure_secrets():
    if not OPENAI_API_KEY:
        raise RuntimeError("Missing OPENAI_API_KEY (set it in your environment or .env)")
    if not DRY_RUN:
        if not SENDER_EMAIL:
            raise RuntimeError("Missing SENDER_EMAIL (required when DRY_RUN=false)")
        if not RECEIVER_EMAILS:
            raise RuntimeError("Missing RECEIVER_EMAILS (comma-separated) when DRY_RUN=false")
        if not GMAIL_APP_PASSWORD or len(GMAIL_APP_PASSWORD) < 16:
            raise RuntimeError("Missing/invalid GMAIL_APP_PASSWORD (use Gmail App Password)")

def _pick_table(tables):
    # choose the table with both "company name" and "dely %" semantics
    for t in tables:
        cols = [str(c).strip() for c in t.columns]
        lc = [c.lower() for c in cols]
        has_company = any(("company" in c and "name" in c) for c in lc)
        has_delivery = any(("dely" in c) or ("delivery" in c) for c in lc)
        if has_company and has_delivery:
            t.columns = cols
            return t
    # fallback: widest table
    return max(tables, key=lambda x: x.shape[1])

def fetch_delivery_table() -> pd.DataFrame:
    last_err = None
    for _ in range(3):
        try:
            resp = requests.get(URL, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            tables = pd.read_html(StringIO(resp.text))
            if not tables:
                raise ValueError("No tables found on the page.")
            base = _pick_table(tables).copy()
            break
        except Exception as e:
            last_err = e
            time.sleep(1.5)
    else:
        raise RuntimeError(f"Failed to fetch/parse Moneycontrol tables: {last_err}")

    base.columns = [str(c).strip() for c in base.columns]

    def find_col(candidates):
        for c in base.columns:
            cl = c.lower()
            if any(k in cl for k in candidates):
                return c
        return None

    name_col  = find_col(["company", "name"]) or base.columns[0]
    price_col = find_col(["last price", "ltp", "price", "close"]) or base.columns[1]
    dely_col  = find_col(["dely", "delivery"]) or ("Dely %" if "Dely %" in base.columns else None)
    if dely_col is None:
        raise ValueError(f"Couldn't locate Delivery column. Headers: {list(base.columns)}")

    df = base[[name_col, price_col, dely_col]].copy()
    df.columns = ["Company Name", "Last Price", "Dely %"]

    df["Last Price"] = df["Last Price"].astype(str).str.replace(",", "", regex=False).str.strip()
    df["Dely %"] = df["Dely %"].astype(str).str.replace("%", "", regex=False).str.strip()
    df["Last Price"] = pd.to_numeric(df["Last Price"], errors="coerce")
    df["Dely %"] = pd.to_numeric(df["Dely %"], errors="coerce")

    df = df.dropna(subset=["Last Price", "Dely %"]).reset_index(drop=True)
    return df

def select_high_delivery(df: pd.DataFrame) -> pd.DataFrame:
    out = df[df["Dely %"] >= DELIVERY_THRESHOLD].sort_values("Dely %", ascending=False)
    return out.head(MAX_STOCKS).reset_index(drop=True)

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
      "price_min": 0,
      "price_max": 0,
      "pct_min": 0,
      "pct_max": 0,
      "basis": ""
    }},
    "downside_stoploss": {{
      "price_min": 0,
      "price_max": 0,
      "pct_min": -1,
      "pct_max": -1,
      "basis": ""
    }},
    "risk_reward": {{
      "min": 0,
      "max": 0
    }},
    "levels": {{
      "support": [0, 0],
      "resistance": [0, 0]
    }},
    "atr": {{
      "value": 0,
      "pct_of_price": 0
    }},
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
    "entry_trigger": {{
      "type": "breakout",
      "above_price": 0,
      "confirmation": "Close above level with volume > 1.5x 20D avg"
    }},
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

def openai_client() -> OpenAI:
    return OpenAI(api_key=OPENAI_API_KEY)

def analyze_via_openai(client: OpenAI, prompt: str) -> dict:
    last_err = None
    for _ in range(API_RETRY):
        try:
            resp = client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=OPENAI_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if "429" in msg or "insufficient_quota" in msg:
                raise RuntimeError("OpenAI quota/limits error (429 insufficient_quota). Add billing or lower usage.") from e
            time.sleep(API_RETRY_SLEEP)
    raise RuntimeError(f"OpenAI call failed after retries: {last_err}")

def render_html(results: list[dict], date_str: str) -> str:
    style = """
    <style>
      table { border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; }
      thead tr { background-color: #0b3d91; color: #fff; text-align: left; }
      th, td { border: 1px solid #ddd; padding: 8px; font-size: 13px; vertical-align: top; }
      tbody tr:nth-child(even) { background: #f7faff; }
      .pill { padding: 2px 8px; border-radius: 12px; font-size: 12px; }
      .bull { background:#e6f4ea; color:#137333; }
      .bear { background:#fce8e6; color:#a50e0e; }
      .neutral { background:#fff8e1; color:#8a6d3b; }
      .muted { color:#666; font-size:11px; }
    </style>
    """
    header = f"""
    <h2>High Delivery Stock Analysis (Nifty 500)</h2>
    <div class="muted">Date (IST): {date_str} • Filter: Delivery ≥ {DELIVERY_THRESHOLD}% • Count: {len(results)}</div>
    <table>
      <thead>
        <tr>
          <th>Stock</th>
          <th>CMP</th>
          <th>Delivery %</th>
          <th>Upside Target (₹ / %)</th>
          <th>Stop Loss (₹ / %)</th>
          <th>R:R</th>
          <th>ATR (₹ / %)</th>
          <th>Support / Resistance</th>
          <th>Setup</th>
          <th>TSP%</th>
          <th>Trade Plan</th>
        </tr>
      </thead>
      <tbody>
    """
    rows = []
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

        rows.append(f"""
        <tr>
          <td><strong>{stock}</strong><br><span class="muted">{mcap}</span></td>
          <td>₹{cmp_val}</td>
          <td>{dely}%</td>
          <td>₹{ut.get('price_min','')}–₹{ut.get('price_max','')}<br>({ut.get('pct_min','')}%–{ut.get('pct_max','')}%)</td>
          <td>₹{sl.get('price_min','')}–₹{sl.get('price_max','')}<br>({sl.get('pct_min','')}%–{sl.get('pct_max','')}%)</td>
          <td>{rr.get('min','')}–{rr.get('max','')}</td>
          <td>₹{atr.get('value','')} / {atr.get('pct_of_price','')}%</td>
          <td>S: {', '.join(map(str, levels.get('support', [])))}<br>R: {', '.join(map(str, levels.get('resistance', [])))}</td>
          <td>{setup}</td>
          <td><span class="pill {css}">{tsp}%</span></td>
          <td>Entry: {plan_entry.get('type','')} above ₹{plan_entry.get('above_price','')}<br>Targets: {', '.join('₹'+str(x) for x in plan_targets)}<br>SL: ₹{plan_sl}</td>
        </tr>
        """)

    footer = "</tbody></table>"
    return f"<html><body>{style}{header}{''.join(rows)}{footer}<p class='muted'>Automated alert • Educational use only.</p></body></html>"

def send_email_html(subject: str, html_body: str):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(RECEIVER_EMAILS)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER_EMAIL, GMAIL_APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAILS, msg.as_string())

def main():
    ensure_secrets()
    date_str = datetime.now().strftime("%Y-%m-%d")

    log("Fetching Moneycontrol deliverables…")
    df = fetch_delivery_table()
    log(f"Parsed rows: {len(df)}")

    picks = select_high_delivery(df)
    log(f"High-delivery picks (≥{DELIVERY_THRESHOLD}%): {len(picks)}")
    if picks.empty:
        html = f"<html><body><h3>No high-delivery stocks today (≥{DELIVERY_THRESHOLD}%).</h3></body></html>"
        subject = f"High Delivery & Swing Analysis – {date_str}"
        if DRY_RUN:
            print(subject)
            print(html)
            return
        send_email_html(subject, html)
        log("Email sent (empty report).")
        return

    client = openai_client()
    results = []
    for _, row in picks.iterrows():
        stock = str(row["Company Name"]).strip()
        last_price = float(row["Last Price"])
        dely = float(row["Dely %"])
        prompt = build_prompt(stock, last_price, dely, date_str)
        log(f"OpenAI → {stock} (CMP ₹{last_price}, Dely {dely}%)")
        try:
            res = analyze_via_openai(client, prompt)
            # Ensure stock name present
            res.setdefault("meta", {})["stock"] = res.get("meta", {}).get("stock") or stock
            results.append(res)
            time.sleep(0.7)
        except Exception as e:
            log(f"OpenAI error for {stock}: {e}")
            results.append({
                "meta": {"stock": stock, "exchange":"NSE", "date": date_str, "market_cap_category": ""},
                "kpis": {"cmp": last_price, "delivery_pct": dely, "technical_setup": f"OpenAI error: {e}",
                         "tsp": {"probability_pct": 0}},
                "trade_plan": {"entry_trigger": {"type":"", "above_price": ""}, "targets": [], "stop_loss": ""},
                "disclaimer": "OpenAI failure for this row."
            })

    html = render_html(results, date_str)
    subject = f"High Delivery & Swing Analysis – {date_str}"

    if DRY_RUN:
        print(subject)
        print(html)
    else:
        send_email_html(subject, html)
        log("✅ Email sent.")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"❌ Fatal error: {exc}", file=sys.stderr)
        sys.exit(1)
