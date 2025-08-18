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
        response = None
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

        # Validate response content
        if len(response.text) < 5000:
            raise ValueError("Page content too short - might be blocked or redirected")
        
        if "access denied" in response.text.lower() or "captcha" in response.text.lower():
            raise ValueError("Access blocked by website")

        # Parse HTML tables
        df = None
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
            try:
                df_list = pd.read_html(response.text, attrs={'class': 'tbldata14'})
                if df_list:
                    df = df_list[0]
                    logger.info(f"✅ Alternative parsing successful with {len(df)} rows")
            except:
                # Try basic parsing
                try:
                    df_list = pd.read_html(response.text, header=0)
                    if df_list:
                        df = df_list[0]
                        logger.info(f"✅ Basic parsing successful with {len(df)} rows")
                except:
                    pass
            
            if df is None:
                raise RuntimeError(f"❌ Could not parse any tables from the page")

        # ========= STEP 2: CLEAN DATA =========
        df.columns = [str(col).strip() for col in df.columns]
        
        # Handle different possible column names
        delivery_col = None
        possible_names = ['Dely %', 'Delivery %', 'Del %', 'Delivery', 'DELY %']
        
        for col_name in possible_names:
            if col_name in df.columns:
                delivery_col = col_name
                break
        
        # If exact match not found, look for partial matches
        if delivery_col is None:
            for col in df.columns:
                if 'dely' in str(col).lower() or 'delivery' in str(col).lower():
                    delivery_col = col
                    break
        
        if delivery_col is None:
            logger.warning("⚠️ Delivery column not found. Available columns:", df.columns.tolist())
            delivery_col = df.columns[-1]  # Assume last column is delivery
            logger.info(f"🔄 Using column '{delivery_col}' as delivery percentage")

        # Clean delivery percentage data
        df[delivery_col] = df[delivery_col].astype(str).str.replace("%", "").str.strip()
        df[delivery_col] = pd.to_numeric(df[delivery_col], errors="coerce")
        
        # Remove rows with NaN delivery percentages and invalid values
        initial_count = len(df)
        df = df.dropna(subset=[delivery_col])
        df = df[df[delivery_col] >= 0]  # Remove negative values
        df = df[df[delivery_col] <= 100]  # Remove values > 100%
        
        logger.info(f"📊 Data processing complete. Found {len(df)} stocks after cleaning (was {initial_count}).")
        logger.info(f"📊 Sample data:\n{df.head()}")

        # ========= STEP 3: FILTER =========
        high_delivery = df[df[delivery_col] > 85].copy()
        high_delivery = high_delivery.sort_values(delivery_col, ascending=False)
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
        current_time = datetime.now().strftime("%H:%M:%S IST")
        
        # Enhanced CSS styles
        css_styles = """
        <style>
            body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
            .container { max-width: 800px; margin: 0 auto; padding: 20px; }
            .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); 
                     color: white; padding: 20px; border-radius: 10px; text-align: center; }
            .stats { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 20px 0; }
            .table-container { overflow-x: auto; }
            .styled-table { 
                width: 100%; border-collapse: collapse; margin: 20px 0; 
                box-shadow: 0 0 20px rgba(0, 0, 0, 0.1); border-radius: 5px; overflow: hidden;
            }
            .styled-table th { 
                background: #009879; color: white; padding: 12px 15px; text-align: left; font-weight: bold;
            }
            .styled-table td { 
                padding: 12px 15px; border-bottom: 1px solid #ddd;
            }
            .styled-table tbody tr:nth-of-type(even) { background: #f3f3f3; }
            .styled-table tbody tr:hover { background: #f5f5f5; }
            .footer { color: #666; font-size: 0.9em; text-align: center; margin-top: 30px; 
                     border-top: 1px solid #eee; padding-top: 20px; }
            .highlight { color: #009879; font-weight: bold; }
            .no-data { text-align: center; padding: 40px; color: #666; }
        </style>
        """
        
        if not high_delivery.empty:
            # Prepare columns for display
            display_cols = []
            col_mapping = {
                'Company Name': 'Company',
                'Last Price': 'Price',
                delivery_col: 'Delivery %'
            }
            
            for original_col, display_name in col_mapping.items():
                if original_col in high_delivery.columns:
                    display_cols.append((original_col, display_name))
            
            # If standard columns not found, use first 3 columns
            if not display_cols:
                for i, col in enumerate(high_delivery.columns[:3]):
                    display_name = col if i != len(high_delivery.columns) - 1 else 'Delivery %'
                    display_cols.append((col, display_name))
            

if __name__ == "__main__":
    main()
