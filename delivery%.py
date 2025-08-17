import pandas as pd
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date

# ========= STEP 1: READ TABLE =========
url = "https://www.moneycontrol.com/india/stockmarket/stock-deliverables/marketstatistics/indices/nifty-500-7.html"

try:
    df_list = pd.read_html(url)
    df = df_list[0]
    print("✅ Table successfully loaded.")
except Exception as e:
    raise RuntimeError(f"❌ Could not read Moneycontrol table: {e}")

# ========= STEP 2: CLEAN DATA =========
df.columns = [col.strip() for col in df.columns]  # Normalize column names
print("Columns:", df.columns.tolist())  # Debug: confirm column names

# Convert "Dely %" to numeric
df["Dely %"] = df["Dely %"].astype(str).str.replace("%", "").str.strip()
df["Dely %"] = pd.to_numeric(df["Dely %"], errors="coerce")

# ========= STEP 3: FILTER =========
high_delivery = df[df["Dely %"] > 85]

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
        {html_table}
        <p>— Automated by your script</p>
      </body>
    </html>
    """
    display_message = "\n".join(
        f"{row['Company Name']} | Last Price: {row['Last Price']} | Dely %: {row['Dely %']}%"
        for _, row in high_delivery.iterrows()
    )
else:
    message_body = """
    <html>
      <body>
        <h2>No Nifty 500 stock today has Delivery % &gt; 85.</h2>
        <p>— Automated by your script</p>
      </body>
    </html>
    """
    display_message = "No Nifty 500 stock today has Delivery % > 85."

print(display_message)

# ========= STEP 5: SEND EMAIL =========
sender = "deepshrivastava2493@gmail.com"
receivers = [
    "rockingdeep69@gmail.com",
    "akhileshekka@gmail.com"
]

app_password = "sjkynqkenfpfdvyo"  # Your valid 16-digit App Password (no spaces)

try:
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
    print("❌ Authentication failed:", auth_err)
except Exception as e:
    print("⚠️ Error sending email:", e)
