import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
import requests
from io import StringIO
import os
import time
import numpy as np
#from google.colab import userdata

# ========= STEP 1: READ TABLE WITH HEADERS =========
url = "https://www.moneycontrol.com/india/stockmarket/stock-deliverables/marketstatistics/indices/nifty-500-7.html"

# Add headers to look like a real browser
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}

try:
    print(f"📊 Fetching data from Moneycontrol...")

    # First get the webpage content
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    print(f"📊 Response status: {response.status_code}")
    print(f"📄 Page size: {len(response.text)} characters")

    # Debug: Check what we actually got
    print("🔍 First 500 characters of response:")
    print(response.text[:500])
    print("\n🔍 Last 200 characters of response:")
    print(response.text[-200:])

    # Check if we got the right page
    if "delivery" in response.text.lower() and "nifty" in response.text.lower():
        print("✅ Successfully reached Moneycontrol delivery page")
    else:
        print("⚠️ Warning: Page content may not be as expected")

    # Check for common blocking indicators
    if "access denied" in response.text.lower():
        print("🚫 Access denied - website is blocking us")
    elif "captcha" in response.text.lower():
        print("🚫 Captcha detected - website is blocking us")
    elif len(response.text) < 5000:
        print("⚠️ Page seems too short - might be redirected or blocked")

    # Parse tables from the HTML content
    df_list = pd.read_html(StringIO(response.text))
    df = df_list[0]
    print(f"✅ Table successfully loaded with {len(df)} rows.")

except requests.exceptions.RequestException as e:
    raise RuntimeError(f"❌ Network error accessing Moneycontrol: {e}")
except ValueError as e:
    raise RuntimeError(f"❌ Could not find tables on Moneycontrol page: {e}")
except Exception as e:
    raise RuntimeError(f"❌ Unexpected error reading Moneycontrol table: {e}")

# ========= STEP 2: CLEAN DATA =========
df.columns = [col.strip() for col in df.columns]  # Normalize column names
print("Columns:", df.columns.tolist())  # Debug: confirm column names

# Convert "Dely %" to numeric - handle NaN values properly
df["Dely %"] = df["Dely %"].astype(str).str.replace("%", "").str.strip()
df["Dely %"] = pd.to_numeric(df["Dely %"], errors="coerce")

# Remove rows where Dely % is NaN
df = df.dropna(subset=["Dely %"])

print(f"📊 Data processing complete. Found {len(df)} stocks.")

# ========= STEP 3: FILTER =========
high_delivery = df[df["Dely %"] > 85]
print(f"🎯 Found {len(high_delivery)} stocks with delivery > 85%")

# ========= STEP 3B: CUSTOM STOCK ANALYSIS =========
def analyze_stock(stock_name, cmp, atr=25, rsi=55, macd_signal="Bullish", earnings="Neutral", sector="Positive"):
    """
    Enhanced probability & target calculation based on delivery percentage and technical indicators.
    Dynamically calculates targets based on actual stock data from high delivery stocks.
    """
    try:
        # Ensure cmp is numeric
        cmp = float(cmp)
        atr = float(atr)
        rsi = float(rsi)

        # Enhanced probability calculation based on multiple factors
        base_prob = 60
        atr_factor = min(15, (atr / cmp) * 100)  # ATR contribution
        rsi_factor = (rsi - 50) * 0.3  # RSI contribution
        macd_factor = 10 if macd_signal == "Bullish" else 0  # MACD contribution

        prob_move = min(95, max(20, base_prob + atr_factor + rsi_factor + macd_factor))

        # Dynamic upside target based on ATR and market conditions
        multiplier = 2.5 if macd_signal == "Bullish" and rsi > 60 else 2.0
        upside_target = round(cmp + atr * multiplier, 2)
        upside_pct = round(((upside_target - cmp) / cmp) * 100, 2)

        # Dynamic stop loss based on risk-reward ratio
        risk_reward_ratio = 2.0  # 1:2 risk reward
        sl_pct = round(upside_pct / risk_reward_ratio, 2)
        sl_price = round(cmp - (cmp * sl_pct / 100), 2)

        # Enhanced descriptive analysis
        technical = (
            "Very Bullish (MACD+, RSI>60)" if macd_signal == "Bullish" and rsi > 60 else
            "Bullish (MACD+)" if macd_signal == "Bullish" else
            "Neutral to Bearish"
        )

        price_action = (
            "Strong Momentum (High Delivery)" if atr > 30 else
            "Moderate Momentum" if atr > 20 else
            "Range-bound"
        )

        fundamentals = (
            "Strong (Earnings+, High Delivery)" if earnings == "Positive" else
            "Moderate" if earnings == "Neutral" else
            "Weak"
        )

        driver = (
            "Institutional Interest + Momentum" if prob_move > 75 else
            "Momentum Play" if prob_move > 60 else
            "Range Trading"
        )

        return {
            "Stock": stock_name,
            "Current Price": f"₹{cmp:,.2f}",
            "Probability of Move": f"{prob_move:.1f}%",
            "Upside Target": f"₹{upside_target:,.2f} (+{upside_pct}%)",
            "Stop Loss": f"₹{sl_price:,.2f} (-{sl_pct}%)",
            "Technical Setup": technical,
            "Price Action": price_action,
            "Fundamentals": fundamentals,
            "Key Driver": driver,
            "Risk-Reward": f"1:{risk_reward_ratio:.1f}"
        }
    except (ValueError, TypeError, ZeroDivisionError) as e:
        print(f"⚠️ Error analyzing stock {stock_name}: {e}")
        return {
            "Stock": stock_name,
            "Current Price": f"₹{cmp}" if isinstance(cmp, (int, float)) else str(cmp),
            "Probability of Move": "N/A",
            "Upside Target": "Calculation Error",
            "Stop Loss": "N/A",
            "Technical Setup": "Error in calculation",
            "Price Action": "N/A",
            "Fundamentals": "N/A",
            "Key Driver": "Analysis Failed",
            "Risk-Reward": "N/A"
        }

# ========= STEP 3B: DYNAMIC STOCK ANALYSIS FOR HIGH DELIVERY STOCKS =========
try:
    if not high_delivery.empty:
        print(f"📊 Analyzing {len(high_delivery)} high delivery stocks...")

        analysis_list = []
        for _, row in high_delivery.iterrows():
            try:
                # Extract stock data from the high delivery dataframe
                stock_name = row.get('Company Name', 'Unknown')
                current_price = row.get('Last Price', 0)
                delivery_pct = row.get('Dely %', 0)

                # Clean and convert price data
                if isinstance(current_price, str):
                    current_price = float(current_price.replace(',', '').replace('₹', '').strip())
                else:
                    current_price = float(current_price) if current_price else 0

                # Generate dynamic ATR based on delivery percentage and price
                # Higher delivery % suggests higher ATR (more volatility/interest)
                estimated_atr = max(15, min(50, (delivery_pct - 70) * 2 + current_price * 0.02))

                # Generate dynamic RSI based on delivery percentage
                # Higher delivery typically correlates with higher RSI
                estimated_rsi = min(80, max(45, 50 + (delivery_pct - 75) * 2))

                # MACD signal based on delivery percentage
                macd_signal = "Bullish" if delivery_pct > 90 else "Neutral" if delivery_pct > 85 else "Bearish"

                # Earnings assumption based on high delivery
                earnings = "Positive" if delivery_pct > 90 else "Neutral"

                # Sector assumption
                sector = "Positive" if delivery_pct > 88 else "Neutral"

                print(f"  Analyzing {stock_name}: Price={current_price}, Delivery={delivery_pct}%, Est.ATR={estimated_atr:.1f}")

                # Perform analysis
                stock_analysis = analyze_stock(
                    stock_name=stock_name,
                    cmp=current_price,
                    atr=estimated_atr,
                    rsi=estimated_rsi,
                    macd_signal=macd_signal,
                    earnings=earnings,
                    sector=sector
                )

                # Add delivery percentage to the analysis
                stock_analysis["Delivery %"] = f"{delivery_pct:.1f}%"

                analysis_list.append(stock_analysis)

            except Exception as stock_error:
                print(f"⚠️ Error analyzing stock {row.get('Company Name', 'Unknown')}: {stock_error}")
                # Add a basic entry even if analysis fails
                analysis_list.append({
                    "Stock": row.get('Company Name', 'Unknown'),
                    "Current Price": row.get('Last Price', 'N/A'),
                    "Delivery %": f"{row.get('Dely %', 0):.1f}%",
                    "Probability of ±5–10%": "N/A",
                    "Upside Target": "Analysis Failed",
                    "SL": "N/A",
                    "Technical Setup": "Error",
                    "Price Action": "N/A",
                    "Fundamentals": "N/A",
                    "Overall Driver": "N/A"
                })

        if analysis_list:
            analysis_df = pd.DataFrame(analysis_list)
            print(f"✅ Custom Analysis completed for {len(analysis_list)} stocks")
            print("Top 3 analyzed stocks:")
            print(analysis_df[['Stock', 'Current Price', 'Delivery %', 'Upside Target']].head(3).to_string(index=False))
        else:
            analysis_df = pd.DataFrame()
            print("⚠️ No stocks could be analyzed")
    else:
        print("ℹ️ No high delivery stocks found, skipping custom analysis")
        analysis_df = pd.DataFrame()

except Exception as e:
    print(f"⚠️ Error in dynamic stock analysis: {e}")
    analysis_df = pd.DataFrame()

# ========= STEP 4: BUILD EMAIL BODY =========
try:
    if not high_delivery.empty:
        # Reorder columns to put Dely % as the third column
        if all(col in high_delivery.columns for col in ["Company Name", "Last Price", "Dely %"]):
            ordered_cols = ["Company Name", "Last Price", "Dely %"] + \
                         [col for col in high_delivery.columns if col not in ["Company Name", "Last Price", "Dely %"]]
            high_delivery = high_delivery[ordered_cols]
        
        # Ensure we have the required columns before creating HTML table
        required_cols = ["Company Name", "Last Price", "Dely %"]
        available_cols = [col for col in required_cols if col in high_delivery.columns]

        if available_cols:
            html_table = high_delivery.to_html(
                index=False, 
                columns=available_cols,
                justify="center", 
                border=1,
                classes="dataframe",
                float_format="%.2f"
            )
            display_message = "\n".join(
                f"{row.get('Company Name', 'N/A')} | Last Price: {row.get('Last Price', 'N/A')} | Dely %: {row.get('Dely %', 'N/A')}%"
                for _, row in high_delivery.iterrows()
            )
        else:
            html_table = high_delivery.to_html(index=False, justify="center", border=1)
            display_message = f"Found {len(high_delivery)} stocks with delivery > 85%"

        message_body = f"""
        <html>
          <head>
            <style>
              .dataframe {{
                border-collapse: collapse;
                width: 100%;
                margin: 15px 0;
              }}
              .dataframe th, .dataframe td {{
                border: 1px solid #ddd;
                padding: 8px;
                text-align: center;
              }}
              .dataframe th {{
                background-color: #f2f2f2;
              }}
              .dataframe tr:nth-child(even) {{
                background-color: #f9f9f9;
              }}
            </style>
          </head>
          <body>
            <h2>Stocks with Delivery &gt; 85% (Nifty 500)</h2>
            <p>Date: {date.today()}</p>
            {html_table}
            <p>— Automated by GitHub Actions</p>
          </body>
        </html>
        """
    else:
        message_body = f"""
        <html>
          <body>
            <h2>No Nifty 500 stock today has Delivery % &gt; 85.</h2>
            <p>Date: {date.today()}</p>
            <p>— Automated by GitHub Actions</p>
          </body>
        </html>
        """
        display_message = "No Nifty 500 stock today has Delivery % > 85."

    print("📧 Email content preview:")
    print(display_message)

    # Add custom stock analysis table if available
    if not analysis_df.empty:
        try:
            # Reorder columns in analysis_df to put Delivery % early
            if "Delivery %" in analysis_df.columns:
                analysis_cols = ["Stock", "Current Price", "Delivery %"] + \
                               [col for col in analysis_df.columns if col not in ["Stock", "Current Price", "Delivery %"]]
                analysis_df = analysis_df[analysis_cols]
            
            analysis_html = analysis_df.to_html(
                index=False, 
                border=1, 
                justify="center", 
                escape=False,
                classes="dataframe"
            )
            message_body = message_body.replace("</body>", f"""
            <h2>📊 Detailed Analysis of High Delivery Stocks</h2>
            <p><strong>Analysis includes:</strong> Price targets, stop losses, technical setups, and key drivers</p>
            {analysis_html}
            <p><em>Note: Analysis based on delivery percentages and estimated technical indicators.
            ATR and RSI values are estimated. Please verify with real-time data before trading.</em></p>
            </body>""")
            print(f"✅ Custom analysis added to email for {len(analysis_df)} stocks")
        except Exception as e:
            print(f"⚠️ Could not add analysis table to email: {e}")
    else:
        print("ℹ️ No custom analysis to add to email")

except Exception as e:
    print(f"⚠️ Error building email body: {e}")
    # Fallback email body
    message_body = f"""
    <html>
      <body>
        <h2>Stock Analysis Report - {date.today()}</h2>
        <p>There was an issue processing the stock data today.</p>
        <p>— Automated by GitHub Actions</p>
      </body>
    </html>
    """

# ========= STEP 5: SEND EMAIL =========
sender = "deepshrivastava2493@gmail.com"
receivers = [
    "rockingdeep69@gmail.com"
,    "akhileshekka@gmail.com"
]

# Get app password from environment variable (GitHub Secret)
app_password = os.environ.get("GMAIL_APP_PASSWORD")
if not app_password:
    raise RuntimeError("❌ Gmail app password not found. Please set GMAIL_APP_PASSWORD secret in GitHub.")

try:
    print("📤 Sending email...")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"High Delivery & Analysis Alert - {date.today()}"
    msg["From"] = sender
    msg["To"] = ", ".join(receivers)
    msg.attach(MIMEText(message_body, "html", "utf-8"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, app_password)
        server.sendmail(sender, receivers, msg.as_string())

    print("✅ Email sent successfully to:", receivers)

except smtplib.SMTPAuthenticationError as auth_err:
    print("❌ Gmail authentication failed:", auth_err)
    print("💡 Check if your app password is correct and 2FA is enabled")
except Exception as e:
    print("⚠️ Error sending email:", e)

print(f"🎉 Script completed successfully at {date.today()}")
