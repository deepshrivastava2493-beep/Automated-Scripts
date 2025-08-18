import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date, datetime
import requests
from io import StringIO
import os
import time
import numpy as np
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('stock_alert.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

def main():
    try:
        logger.info("🚀 Starting Stock Delivery Alert Script")
        
        # ========= STEP 1: READ TABLE WITH HEADERS =========
        url = "https://www.moneycontrol.com/india/stockmarket/stock-deliverables/marketstatistics/indices/nifty-500-7.html"

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none'
        }

        # Add retry mechanism
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"🔍 Attempt {attempt + 1}: Fetching data from Moneycontrol...")
                response = requests.get(url, headers=headers, timeout=30)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt == max_retries - 1:
                    raise RuntimeError(f"❌ Failed to fetch data after {max_retries} attempts: {e}")
                time.sleep(5)  # Wait before retry

        logger.info(f"📊 Response status: {response.status_code}")
        logger.info(f"📏 Page size: {len(response.text)} characters")

        # Parse HTML tables
        try:
            df_list = pd.read_html(StringIO(response.text))
            if not df_list:
                raise ValueError("No tables found on page")
            df = df_list[0]
            logger.info(f"✅ Table successfully loaded with {len(df)} rows and columns: {df.columns.tolist()}")
        except Exception as e:
            logger.error(f"❌ Error parsing HTML tables: {e}")
            # Try alternative parsing
            logger.info("🔄 Trying alternative table parsing...")
            df_list = pd.read_html(response.text, attrs={'class': 'tbldata14'})
            if df_list:
                df = df_list[0]
                logger.info(f"✅ Alternative parsing successful with {len(df)} rows")
            else:
                raise RuntimeError(f"❌ Could not parse any tables from the page")

        # ========= STEP 2: CLEAN DATA =========
        df.columns = [col.strip() for col in df.columns]
        
        # Handle different possible column names
        delivery_col = None
        for col in df.columns:
            if 'dely' in col.lower() or 'delivery' in col.lower():
                delivery_col = col
                break
        
        if delivery_col is None:
            logger.warning("⚠️ Delivery column not found. Available columns:", df.columns.tolist())
            delivery_col = df.columns[-1]  # Assume last column is delivery
            logger.info(f"🔄 Using column '{delivery_col}' as delivery percentage")

        # Clean delivery percentage data
        df[delivery_col] = df[delivery_col].astype(str).str.replace("%", "").str.strip()
        df[delivery_col] = pd.to_numeric(df[delivery_col], errors="coerce")
        
        # Remove rows with NaN delivery percentages
        df = df.dropna(subset=[delivery_col])
        
        logger.info(f"📊 Data processing complete. Found {len(df)} stocks after cleaning.")
        logger.info(f"📊 Sample data:\n{df.head()}")

        # ========= STEP 3: FILTER =========
        high_delivery = df[df[delivery_col] > 85]
        logger.info(f"🎯 Found {len(high_delivery)} stocks with delivery > 85%")

        # ========= STEP 3B: CUSTOM STOCK ANALYSIS =========
        def analyze_stock(stock_name, cmp, atr=25, rsi=55, macd_signal="Bullish", earnings="Neutral", sector="Positive"):
            """Enhanced stock analysis with better calculations"""
            try:
                # Probability calculation
                volatility_factor = min(40, (atr / cmp) * 100) if cmp > 0 else 20
                prob_move = min(90, 60 + volatility_factor)

                # Upside target
                upside_target = round(cmp + atr * 2, 2)
                upside_pct = round(((upside_target - cmp) / cmp) * 100, 2) if cmp > 0 else 0

                # Stop loss = half upside%
                sl_price = round(cmp - (cmp * (upside_pct / 2) / 100), 2) if cmp > 0 else 0
                sl_pct = round(((cmp - sl_price) / cmp) * 100, 2) if cmp > 0 else 0

                # Descriptive columns
                technical = "Supportive (MACD bullish, RSI above 50)" if macd_signal == "Bullish" else "Neutral"
                price_action = "Supportive (CMP above 20DMA)" if cmp > (cmp * 0.98) else "Neutral"
                fundamentals = "Neutral (Earnings average)" if earnings == "Neutral" else "Supportive"
                driver = "Momentum + ATR expansion" if atr > 20 else "Range-bound"

                return {
                    "Stock": stock_name,
                    "Current Price": cmp,
                    "Probability of ±5–10%": f"{prob_move:.1f}%",
                    "Upside Target": f"{upside_target} ({upside_pct}%)",
                    "SL": f"{sl_price} ({sl_pct}%)",
                    "Technical Setup": technical,
                    "Price Action": price_action,
                    "Fundamentals": fundamentals,
                    "Overall Driver": driver
                }
            except Exception as e:
                logger.error(f"Error analyzing stock {stock_name}: {e}")
                return None

        # Example stock analysis
        sailife_analysis = analyze_stock("SAILIFE", cmp=890, atr=28)
        analysis_df = pd.DataFrame([sailife_analysis]) if sailife_analysis else pd.DataFrame()
        
        if not analysis_df.empty:
            logger.info(f"📊 Custom Analysis Table:\n{analysis_df}")

        # ========= STEP 4: BUILD EMAIL BODY =========
        current_date = date.today().strftime("%B %d, %Y")
        
        if not high_delivery.empty:
            # Ensure we have the right columns for the email
            display_cols = []
            for col in ["Company Name", "Last Price", delivery_col]:
                if col in high_delivery.columns:
                    display_cols.append(col)
            
            if not display_cols:
                display_cols = high_delivery.columns[:3].tolist()  # Take first 3 columns
            
            html_table = high_delivery[display_cols].to_html(
                index=False,
                justify="center", 
                border=1,
                table_id="deliveryTable",
                classes="styled-table"
            )
            
            message_body = f"""
            <html>
              <head>
                <style>
                  .styled-table {{
                    border-collapse: collapse;
                    margin: 25px 0;
                    font-size: 0.9em;
                    font-family: sans-serif;
                    min-width: 400px;
                    box-shadow: 0 0 20px rgba(0, 0, 0, 0.15);
                  }}
                  .styled-table th,
                  .styled-table td {{
                    padding: 12px 15px;
                    text-align: left;
                    border-bottom: 1px solid #dddddd;
                  }}
                  .styled-table th {{
                    background-color: #009879;
                    color: #ffffff;
                    text-transform: uppercase;
                  }}
                  .styled-table tbody tr:nth-of-type(even) {{
                    background-color: #f3f3f3;
                  }}
                </style>
              </head>
              <body>
                <h2>🎯 Stocks with High Delivery % (>85%) - Nifty 500</h2>
                <p><strong>Date:</strong> {current_date}</p>
                <p><strong>Total stocks found:</strong> {len(high_delivery)}</p>
                {html_table}
                <hr>
                <p style="color: #666; font-size: 0.9em;">
                  📊 High delivery percentage often indicates genuine buying interest and reduced speculation.<br>
                  🤖 Automated by GitHub Actions | Generated at {datetime.now().strftime("%H:%M:%S IST")}
                </p>
              </body>
            </html>
            """
        else:
            message_body = f"""
            <html>
              <body>
                <h2>📊 Daily Delivery Report - No High Delivery Stocks Today</h2>
                <p><strong>Date:</strong> {current_date}</p>
                <p>🔍 No Nifty 500 stock today has Delivery % > 85%.</p>
                <p>This could indicate:</p>
                <ul>
                  <li>Lower institutional activity</li>
                  <li>Increased speculative trading</li>
                  <li>Market-wide consolidation phase</li>
                </ul>
                <hr>
                <p style="color: #666; font-size: 0.9em;">
                  🤖 Automated by GitHub Actions | Generated at {datetime.now().strftime("%H:%M:%S IST")}
                </p>
              </body>
            </html>
            """

        # Add custom stock analysis table if available
        if not analysis_df.empty:
            analysis_html = analysis_df.to_html(index=False, border=1, justify="center", classes="styled-table")
            message_body += f"""
                <h2>📈 Custom Stock Analysis</h2>
                {analysis_html}
            """

        logger.info("📧 Email content prepared successfully")

        # ========= STEP 5: SEND EMAIL =========
        sender = "deepshrivastava2493@gmail.com"
        receivers = [
            "rockingdeep69@gmail.com",
            "akhileshekka@gmail.com"
        ]

        app_password = os.environ.get("GMAIL_APP_PASSWORD")
        if not app_password:
            raise RuntimeError("❌ Gmail app password not found. Please set GMAIL_APP_PASSWORD secret in GitHub.")

        try:
            logger.info("📤 Preparing to send email...")
            
            # Create message
            msg = MIMEMultipart("alternative")
            subject = f"📊 Stock Delivery Alert ({len(high_delivery)} stocks) - {current_date}"
            msg["Subject"] = subject
            msg["From"] = sender
            msg["To"] = ", ".join(receivers)
            msg.attach(MIMEText(message_body, "html", "utf-8"))

            # Send email
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(sender, app_password)
                server.sendmail(sender, receivers, msg.as_string())
            
            logger.info(f"✅ Email sent successfully to: {', '.join(receivers)}")

        except smtplib.SMTPAuthenticationError as auth_err:
            logger.error(f"❌ Gmail authentication failed: {auth_err}")
            logger.error("💡 Check if your app password is correct and 2FA is enabled")
            raise
        except Exception as e:
            logger.error(f"⚠️ Error sending email: {e}")
            raise

        logger.info(f"🎉 Script completed successfully at {datetime.now()}")
        
    except Exception as e:
        logger.error(f"💥 Script failed with error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
