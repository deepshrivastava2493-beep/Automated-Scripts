import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date
import requests
from io import StringIO
import os
import time

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
    print(f"🔍 Fetching data from Moneycontrol...")
    
    # First get the webpage content
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    
    print(f"📊 Response status: {response.status_code}")
    print(f"📏 Page size: {len(response.text)} characters")
    
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

# Convert "Dely %" to numeric
df["Dely %"] = df["Dely %"].astype(str).str.replace("%", "").str.strip()
df["Dely %"] = pd.to_numeric(df["Dely %"], errors="coerce")

print(f"📊 Data processing complete. Found {len(df)} stocks.")

# ========= STEP 3: FILTER =========
high_delivery = df[df["Dely %"] > 85]
print(f"🎯 Found {len(high_delivery)} stocks with delivery > 85%")

# ========= STEP 4: BUILD EMAIL BODY =========
if not high_delivery.empty:
    html_table = high_delivery.to_html(
        index=False, columns=["Company Name", "Last Price", "Dely %"],
        justify="center", border=1
    )
    message_body = f"""
    <html>
      <body>
        <h2>Stocks with Delivery &gt; 85% (Nifty 500)</h2>
        <p>Date: {date.today()}</p>
        {html_table}
        <p>— Automated by GitHub Actions</p>
      </body>
    </html>
    """
    display_message = "\n".join(
        f"{row['Company Name']} | Last Price: {row['Last Price']} | Dely %: {row['Dely %']}%"
        for _, row in high_delivery.iterrows()
    )
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

# ========= STEP 5: SEND EMAIL =========
sender = "deepshrivastava2493@gmail.com"
receivers = [
    "rockingdeep69@gmail.com"
    #,"akhileshekka@gmail.com"
]

# Get app password from environment variable (GitHub Secret)
app_password = os.environ.get("GMAIL_APP_PASSWORD")
if not app_password:
    raise RuntimeError("❌ Gmail app password not found. Please set GMAIL_APP_PASSWORD secret in GitHub.")

try:
    print("📤 Sending email...")
    
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"High Delivery Alert - {date.today()}"
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
