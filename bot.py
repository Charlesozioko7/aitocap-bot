import sqlite3
import requests
import threading
import time
import io
import random
import matplotlib.pyplot as plt
from flask import Flask
import telebot
from flask import Flask,request
import threading,time,sqlite3 

# ===== CONFIG =====
BOT_TOKEN = "8324820648:AAFnnA65MrpHjymTol3vBRy4iwP8DFyGxx8"
bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
RENDER_URL = "https://aitocap-bot.onrender.com/"
ADMIN_IDS = [7623720521]  # Replace with your Telegram ID(s)

# ===== DATABASE SETUP =====
conn = sqlite3.connect("trading_app.db", check_same_thread=False)
c = conn.cursor()

# Users table
c.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    balance REAL DEFAULT 0
)
''')

# Profiles table (mandatory KYC)
c.execute('''
CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY,
    name TEXT,
    email TEXT,
    kyc_verified BOOLEAN DEFAULT 0,
    kyc_file TEXT
)
''')

# Transactions table
c.execute('''
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    type TEXT,
    amount REAL,
    wallet TEXT,
    status TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Orders table
c.execute('''
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    pair TEXT,
    order_type TEXT,
    price REAL,
    amount REAL,
    status TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

# Portfolio table
c.execute('''
CREATE TABLE IF NOT EXISTS portfolio (
    user_id INTEGER,
    pair TEXT,
    amount REAL,
    avg_price REAL,
    PRIMARY KEY (user_id, pair)
)
''')

# Alerts table
c.execute('''
CREATE TABLE IF NOT EXISTS alerts (
    user_id INTEGER,
    pair TEXT,
    target_price REAL,
    direction TEXT
)
''')

# Referrals table
c.execute('''
CREATE TABLE IF NOT EXISTS referrals (
    referrer_id INTEGER,
    referee_id INTEGER,
    reward REAL DEFAULT 0
)
''')

# Support tickets
c.execute('''
CREATE TABLE IF NOT EXISTS support_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    message TEXT,
    status TEXT DEFAULT 'Open',
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

conn.commit()

# ===== FLASK KEEP-ALIVE =====
@app.route('/')
def home():
    return "Trading App Bot is running! 🤖"

def keep_alive(url, interval=300):
    while True:
        try:
            requests.get(url)
        except:
            pass
        time.sleep(interval)

threading.Thread(target=lambda: app.run(host="0.0.0.0", port=5000)).start()
threading.Thread(target=lambda: keep_alive(RENDER_URL)).start()

# ===== HELPERS =====
otp_store = {}

def fetch_price(pair):
    try:
        symbol = pair.replace("/", "")
        r = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}USDT")
        return float(r.json()['price'])
    except:
        return None

def send_otp(user_id):
    otp = random.randint(100000,999999)
    otp_store[user_id] = otp
    bot.send_message(user_id, f"Your 2FA code is: {otp}")
    return otp

def verify_otp(user_id, entered_otp):
    return otp_store.get(user_id) == entered_otp

def generate_chart(prices, pair):
    plt.plot(prices)
    plt.title(f"{pair} Price Chart")
    plt.xlabel("Time")
    plt.ylabel("Price USD")
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    return buf

def check_kyc(user_id):
    c.execute("SELECT kyc_verified FROM profiles WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return row and row[0] == 1

# ===== USER REGISTRATION & KYC =====
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    c.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,))
    if not c.fetchone():
        msg = bot.send_message(user_id, "Welcome! Please enter your full name:")
        bot.register_next_step_handler(msg, get_name)
    elif not check_kyc(user_id):
        bot.send_message(user_id, "Your account is pending KYC verification. Please upload required documents.")
        request_kyc(user_id)
    else:
        show_main_menu(user_id)

def get_name(message):
    user_id = message.chat.id
    name = message.text
    c.execute("INSERT OR REPLACE INTO profiles (user_id, name) VALUES (?,?)", (user_id, name))
    conn.commit()
    msg = bot.send_message(user_id, "Enter your email address:")
    bot.register_next_step_handler(msg, get_email)

def get_email(message):
    user_id = message.chat.id
    email = message.text
    c.execute("UPDATE profiles SET email=? WHERE user_id=?", (email, user_id))
    conn.commit()
    request_kyc(user_id)

def request_kyc(user_id):
    msg = bot.send_message(user_id, "Upload your KYC document (photo/pdf). KYC is mandatory to access trading and wallet features.")
    bot.register_next_step_handler(msg, save_kyc)

def save_kyc(message):
    user_id = message.chat.id
    if message.content_type in ["photo", "document"]:
        file_id = message.photo[-1].file_id if message.content_type=="photo" else message.document.file_id
        c.execute("UPDATE profiles SET kyc_file=? WHERE user_id=?", (file_id, user_id))
        conn.commit()
        bot.send_message(user_id, "KYC uploaded ✅ Awaiting admin approval.")
        for admin in ADMIN_IDS:
            bot.send_message(admin, f"New KYC submitted by user {user_id}. Use /approve_kyc {user_id} to approve.")
    else:
        bot.send_message(user_id, "Invalid file. Please upload a photo or PDF.")
        request_kyc(user_id)

# ===== ADMIN COMMANDS =====
@bot.message_handler(commands=['approve_kyc'])
def approve_kyc(message):
    if message.chat.id not in ADMIN_IDS:
        bot.reply_to(message, "Unauthorized")
        return
    try:
        _, user_id = message.text.split()
        user_id = int(user_id)
        c.execute("UPDATE profiles SET kyc_verified=1 WHERE user_id=?", (user_id,))
        conn.commit()
        bot.send_message(user_id, "✅ Your KYC has been approved! You can now access all features.")
        bot.reply_to(message, f"User {user_id} KYC approved.")
    except:
        bot.reply_to(message, "Error. Usage: /approve_kyc <user_id>")

# ===== DEPOSITS & WITHDRAWALS =====
def add_transaction(user_id, tx_type, amount, wallet=None):
    c.execute("INSERT INTO transactions (user_id,type,amount,wallet,status) VALUES (?,?,?,?,?)",
              (user_id, tx_type, amount, wallet, "Pending"))
    conn.commit()

def deposit_flow(message):
    user_id = message.chat.id
    if not check_kyc(user_id):
        bot.send_message(user_id, "⚠️ You must complete KYC first.")
        return
    amount = message.text
    if not amount.replace(".", "", 1).isdigit():
        bot.send_message(user_id, "Invalid amount.")
        return
    add_transaction(user_id, "Deposit", float(amount))
    bot.send_message(user_id, f"Deposit of ${amount} recorded. Awaiting admin approval ✅")

def withdraw_flow(message):
    user_id = message.chat.id
    if not check_kyc(user_id):
        bot.send_message(user_id, "⚠️ You must complete KYC first.")
        return
    amount = message.text
    if not amount.replace(".", "", 1).isdigit():
        bot.send_message(user_id, "Invalid amount.")
        return
    # 2FA verification
    send_otp(user_id)
    msg = bot.send_message(user_id, "Enter the 2FA code sent to you:")
    bot.register_next_step_handler(msg, lambda m: finalize_withdrawal_otp(user_id, float(amount), m.text))

def finalize_withdrawal_otp(user_id, amount, entered_otp):
    if not verify_otp(user_id, int(entered_otp)):
        bot.send_message(user_id, "Invalid 2FA code. Withdrawal cancelled.")
        return
    msg = bot.send_message(user_id, "Enter wallet address:")
    bot.register_next_step_handler(msg, lambda m: finalize_withdrawal(user_id, amount, m.text))

def finalize_withdrawal(user_id, amount, wallet):
    add_transaction(user_id, "Withdrawal", amount, wallet)
    bot.send_message(user_id, f"Withdrawal of ${amount} to {wallet} recorded. Awaiting admin approval ✅")

# ===== ORDERS & TRADING =====
def add_order(user_id, pair, order_type, price, amount):
    c.execute("INSERT INTO orders (user_id,pair,order_type,price,amount,status) VALUES (?,?,?,?,?,?)",
              (user_id, pair, order_type, price, amount, "Pending"))
    conn.commit()

def execute_order(user_id, pair, order_type, price, amount):
    c.execute("SELECT amount, avg_price FROM portfolio WHERE user_id=? AND pair=?", (user_id, pair))
    row = c.fetchone()
    if "Buy" in order_type:
        if row:
            old_amount, old_avg = row
            new_amount = old_amount + amount
            new_amount = old_amount + amount
            new_avg = ((old_avg * old_amount) + (price * amount)) / new_amount
            c.execute("UPDATE portfolio SET amount=?, avg_price=? WHERE user_id=? AND pair=?",
                      (new_amount, new_avg, user_id, pair))
        else:
            c.execute("INSERT INTO portfolio (user_id,pair,amount,avg_price) VALUES (?,?,?,?)",
                      (user_id, pair, amount, price))
    elif "Sell" in order_type:
        if row and row[0] >= amount:
            remaining = row[0] - amount
            if remaining == 0:
                c.execute("DELETE FROM portfolio WHERE user_id=? AND pair=?", (user_id, pair))
            else:
                c.execute("UPDATE portfolio SET amount=? WHERE user_id=? AND pair=?", (remaining, user_id, pair))
        else:
            bot.send_message(user_id, "Insufficient balance to sell.")
            return
    conn.commit()
    c.execute("UPDATE orders SET status='Executed' WHERE user_id=? AND pair=? AND order_type=? AND status='Pending'",
              (user_id, pair, order_type))
    conn.commit()
    bot.send_message(user_id, f"{order_type} order executed for {amount} {pair} at ${price:.2f}.")

# ===== PORTFOLIO =====
def calculate_portfolio(user_id):
    c.execute("SELECT pair, amount, avg_price FROM portfolio WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    if not rows:
        return "Portfolio is empty."
    msg = "Your Portfolio:\n"
    total_value = 0
    for pair, amount, avg_price in rows:
        current_price = fetch_price(pair)
        value = amount * current_price
        profit = value - (amount * avg_price)
        total_value += value
        msg += f"{pair}: {amount} units, Avg ${avg_price:.2f}, Current ${current_price:.2f}, P/L ${profit:.2f}\n"
    msg += f"Total Portfolio Value: ${total_value:.2f}"
    return msg

# ===== PRICE ALERTS =====
def add_price_alert(user_id, pair, target_price, direction):
    c.execute("INSERT INTO alerts (user_id,pair,target_price,direction) VALUES (?,?,?,?)",
              (user_id, pair, target_price, direction))
    conn.commit()
    bot.send_message(user_id, f"Alert set for {pair} {direction} ${target_price}")

def check_alerts():
    while True:
        c.execute("SELECT user_id, pair, target_price, direction FROM alerts")
        alerts = c.fetchall()
        for user_id, pair, target, direction in alerts:
            price = fetch_price(pair)
            if price is None:
                continue
            if (direction=="above" and price>=target) or (direction=="below" and price<=target):
                bot.send_message(user_id, f"⚡ {pair} price is {price}, alert {direction} {target} reached!")
                c.execute("DELETE FROM alerts WHERE user_id=? AND pair=? AND target_price=? AND direction=?", 
                          (user_id, pair, target, direction))
                conn.commit()
        time.sleep(10)

threading.Thread(target=check_alerts).start()

# ===== REFERRALS =====
def handle_referral(user_id, referrer_id):
    if referrer_id:
        c.execute("INSERT INTO referrals (referrer_id, referee_id) VALUES (?,?)", (referrer_id, user_id))
        conn.commit()
        # Reward referrer (optional)
        c.execute("UPDATE users SET balance=balance+? WHERE user_id=?", (10, referrer_id))
        conn.commit()
        bot.send_message(user_id, f"You joined using a referral from {referrer_id}! 🎉")
        bot.send_message(referrer_id, f"You earned a $10 referral bonus from user {user_id}!")

# ===== SUPPORT TICKETS =====
def submit_support(message):
    user_id = message.chat.id
    msg_text = message.text
    c.execute("INSERT INTO support_tickets (user_id,message) VALUES (?,?)", (user_id,msg_text))
    conn.commit()
    bot.send_message(user_id, "Support ticket submitted. Admins will respond shortly.")
    for admin in ADMIN_IDS:
        bot.send_message(admin, f"New support ticket from {user_id}: {msg_text}")

# ===== CHARTS =====
def send_chart(user_id, pair):
    prices = [fetch_price(pair) for _ in range(30)]
    buf = generate_chart(prices, pair)
    bot.send_photo(user_id, buf)
    buf.close()

# ===== MAIN MENU =====
def show_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("Deposit 💰", "Withdraw 🏦")
    markup.row("Trade 📈", "Portfolio 📊")
    markup.row("Transactions 📝", "Charts 📉")
    markup.row("Price Alerts 📢", "Referrals 🎁")
    markup.row("Profile 👤", "Support 🆘")
    bot.send_message(user_id, "Welcome! Choose an option:", reply_markup=markup)

@bot.message_handler(func=lambda m: True)
def main_menu(message):
    user_id = message.chat.id
    text = message.text

    if not check_kyc(user_id):
        bot.send_message(user_id, "⚠️ Your account is pending KYC verification. Complete KYC to access features.")
        return

    # ----- DEPOSIT -----
    if text == "Deposit 💰":
        msg = bot.send_message(user_id, "Enter deposit amount:")
        bot.register_next_step_handler(msg, deposit_flow)

    # ----- WITHDRAW -----
    elif text == "Withdraw 🏦":
        msg = bot.send_message(user_id, "Enter withdrawal amount:")
        bot.register_next_step_handler(msg, withdraw_flow)

    # ----- TRADE -----
    elif text == "Trade 📈":
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row("BTC/USD", "ETH/USD", "Back ⬅️")
        bot.send_message(user_id, "Choose trading pair:", reply_markup=markup)

    elif text in ["BTC/USD", "ETH/USD"]:
        pair = text
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row("Market Buy", "Market Sell")
        markup.row("Limit Buy", "Limit Sell", "Back ⬅️")
        bot.send_message(user_id, f"Select order type for {pair}:", reply_markup=markup)
        bot.register_next_step_handler(message, lambda m: order_flow(m, pair))

    # ----- PORTFOLIO -----
    elif text == "Portfolio 📊":
        report = calculate_portfolio(user_id)
        bot.send_message(user_id, report)

    # ----- TRANSACTIONS -----
    elif text == "Transactions 📝":
        c.execute("SELECT id,type,amount,wallet,status FROM transactions WHERE user_id=? ORDER BY id DESC", (user_id,))
        txs = c.fetchall()
        if not txs:
            bot.send_message(user_id, "No transactions yet.")
        else:
            msg = "\n".join([f"{t[0]}. {t[1]} ${t[2]} - {t[4]}" for t in txs])
            bot.send_message(user_id, msg)

    # ----- CHARTS -----
    elif text == "Charts 📉":
        msg = bot.send_message(user_id, "Enter trading pair for chart (e.g., BTC/USD):")
        bot.register_next_step_handler(msg, lambda m: send_chart(user_id, m.text))

    # ----- PRICE ALERTS -----
    elif text == "Price Alerts 📢":
        msg = bot.send_message(user_id, "Enter pair (e.g., BTC/USD) for alert:")
        bot.register_next_step_handler(msg, set_alert_pair)

    # ----- REFERRALS -----
    elif text == "Referrals 🎁":
        c.execute("SELECT referrer_id FROM referrals WHERE referee_id=?", (user_id,))
        row = c.fetchone()
        if row:
            bot.send_message(user_id, f"You were referred by {row[0]}")
        else:
            bot.send_message(user_id, "You have not used a referral link.")

    # ----- PROFILE -----
    elif text == "Profile 👤":
        c.execute("SELECT name,email,kyc_verified FROM profiles WHERE user_id=?", (user_id,))
        row = c.fetchone()
        status = "Verified ✅" if row[2] else "Pending ❌"
        bot.send_message(user_id, f"Name: {row[0]}\nEmail: {row[1]}\nKYC: {status}")

    # ----- SUPPORT -----
    elif text == "Support 🆘":
        msg = bot.send_message(user_id, "Write your support message:")
        bot.register_next_step_handler(msg, submit_support)

# ===== ALERT HANDLERS =====
def set_alert_pair(message):
    user_id = message.chat.id
    pair = message.text
    msg = bot.send_message(user_id, "Enter target price:")
    bot.register_next_step_handler(msg, lambda m: set_alert_price(user_id, pair, m.text))

def set_alert_price(user_id, pair, price_text):
    try:
        target_price = float(price_text)
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.row("above", "below")
        msg = bot.send_message(user_id, "Notify when price goes above or below target?", reply_markup=markup)
        bot.register_next_step_handler(msg, lambda m: finalize_alert(user_id, pair, target_price, m.text))
    except:
        bot.send_message(user_id, "Invalid price.")

def finalize_alert(user_id, pair, target_price, direction):
    if direction.lower() not in ["above","below"]:
        bot.send_message(user_id, "Invalid direction.")
        return
    add_price_alert(user_id, pair, target_price, direction.lower())

# ===== ORDER FLOW =====
def order_flow(message, pair):
    user_id = message.chat.id
    order_type = message.text
    msg_price = bot.send_message(user_id, f"Enter price for {order_type} {pair}:")
    bot.register_next_step_handler(msg_price, lambda m: order_amount(m, pair, order_type))

def order_amount(message, pair, order_type):
    user_id = message.chat.id
    try:
        price = float(message.text)
        msg_amount = bot.send_message(user_id, f"Enter amount to {order_type}:")
        bot.register_next_step_handler(msg_amount, lambda m: finalize_order(m, pair, order_type, price))
    except:
        bot.send_message(user_id, "Invalid price. Try again.")

def finalize_order(message, pair, order_type, price):
    user_id = message.chat.id
    try:
        amount = float(message.text)
        add_order(user_id, pair, order_type, price, amount)
        bot.send_message(user_id, f"{order_type} order placed for {amount} {pair} at ${price:.2f}. Pending execution.")
    except:
        bot.send_message(user_id, "Invalid amount. Try again.")

# ===== FLASK WEBHOOK SETUP =====
@app.route('/' + BOT_TOKEN, methods=['POST'])
def getMessage():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route('/')
def webhook():
    bot.remove_webhook()
    bot.set_webhook(url=RENDER_URL + BOT_TOKEN)
    return "Webhook set successfully!", 200

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# ===== STARTUP MODE =====
if __name__ == "__main__":
    import os

    if os.getenv("LOCAL_MODE") == "1":
        print("Running in LOCAL MODE (polling)...")
        bot.remove_webhook()
        bot.polling(none_stop=True)
    else:
        print("Running in RENDER MODE (webhook)...")
        threading.Thread(target=run_flask).start()
