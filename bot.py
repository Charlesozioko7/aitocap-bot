import sqlite3
import requests
import threading
import time
import io
import random
import matplotlib.pyplot as plt
from flask import Flask, request
import telebot
from telebot import types

# ===== CONFIG =====
BOT_TOKEN = "8324820648:AAFnnA65MrpHjymTol3vBRy4iwP8DFyGxx8"
RENDER_URL = "https://aitocap-bot.onrender.com/"  # Replace with your Render URL
ADMIN_IDS = [7623720521]  # Your Telegram ID

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)

# ===== DATABASE =====
conn = sqlite3.connect("trading_app.db", check_same_thread=False)
c = conn.cursor()

# Tables
c.execute('''CREATE TABLE IF NOT EXISTS profiles (user_id INTEGER PRIMARY KEY, name TEXT, email TEXT, kyc_verified BOOLEAN DEFAULT 0, kyc_file TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, balance REAL DEFAULT 0)''')
c.execute('''CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT, amount REAL, wallet TEXT, status TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
c.execute('''CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, pair TEXT, order_type TEXT, price REAL, amount REAL, status TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
c.execute('''CREATE TABLE IF NOT EXISTS portfolio (user_id INTEGER, pair TEXT, amount REAL, avg_price REAL, PRIMARY KEY(user_id,pair))''')
c.execute('''CREATE TABLE IF NOT EXISTS alerts (user_id INTEGER, pair TEXT, target_price REAL, direction TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS referrals (referrer_id INTEGER, referee_id INTEGER, reward REAL DEFAULT 0)''')
c.execute('''CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, message TEXT, status TEXT DEFAULT 'Open', timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
conn.commit()

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

def check_kyc(user_id):
    c.execute("SELECT kyc_verified FROM profiles WHERE user_id=?", (user_id,))
    row = c.fetchone()
    return row and row[0] == 1

def generate_chart(prices, pair):
    plt.plot(prices)
    plt.title(f"{pair} Price Chart")
    plt.xlabel("Time")
    plt.ylabel("Price USD")
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    return buf

# ===== REGISTRATION & KYC =====
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.chat.id
    c.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,))
    if not c.fetchone():
        msg = bot.send_message(user_id, "Welcome! Enter your full name:")
        bot.register_next_step_handler(msg, get_name)
    elif not check_kyc(user_id):
        bot.send_message(user_id, "KYC pending. Please upload documents.")
        request_kyc(user_id)
    else:
        show_main_menu(user_id)

def get_name(message):
    user_id = message.chat.id
    name = message.text
    c.execute("INSERT OR REPLACE INTO profiles (user_id, name) VALUES (?,?)", (user_id, name))
    conn.commit()
    msg = bot.send_message(user_id, "Enter your email:")
    bot.register_next_step_handler(msg, get_email)

def get_email(message):
    user_id = message.chat.id
    email = message.text
    c.execute("UPDATE profiles SET email=? WHERE user_id=?", (email, user_id))
    conn.commit()
    request_kyc(user_id)

def request_kyc(user_id):
    msg = bot.send_message(user_id, "Upload your KYC document (photo/pdf). KYC is mandatory.")
    bot.register_next_step_handler(msg, save_kyc)

def save_kyc(message):
    user_id = message.chat.id
    if message.content_type in ["photo","document"]:
        file_id = message.photo[-1].file_id if message.content_type=="photo" else message.document.file_id
        c.execute("UPDATE profiles SET kyc_file=? WHERE user_id=?", (file_id,user_id))
        conn.commit()
        bot.send_message(user_id, "KYC uploaded ✅ Awaiting admin approval.")
        bot.send_message(ADMIN_IDS[0], f"New KYC submitted by user {user_id}. Use /approve_kyc {user_id}")
    else:
        bot.send_message(user_id, "Invalid file. Upload photo/pdf.")
        request_kyc(user_id)

# ===== ADMIN =====
@bot.message_handler(commands=['approve_kyc'])
def approve_kyc(message):
    if message.chat.id not in ADMIN_IDS:
        bot.reply_to(message,"Unauthorized")
        return
    try:
        _, user_id = message.text.split()
        user_id=int(user_id)
        c.execute("UPDATE profiles SET kyc_verified=1 WHERE user_id=?",(user_id,))
        conn.commit()
        bot.send_message(user_id,"✅ KYC approved. Access granted.")
        bot.reply_to(message,f"User {user_id} KYC approved")
    except:
        bot.reply_to(message,"Error. Usage: /approve_kyc <user_id>")

# ===== TRANSACTIONS =====
def add_transaction(user_id,tx_type,amount,wallet=None):
    c.execute("INSERT INTO transactions(user_id,type,amount,wallet,status) VALUES (?,?,?,?,?)",(user_id,tx_type,amount,wallet,"Pending"))
    conn.commit()

def deposit_flow(message):
    user_id = message.chat.id
    if not check_kyc(user_id):
        bot.send_message(user_id,"⚠️ Complete KYC first.")
        return
    amount=message.text
    if not amount.replace(".","",1).isdigit():
        bot.send_message(user_id,"Invalid amount.")
        return
    add_transaction(user_id,"Deposit",float(amount))
    bot.send_message(user_id,f"Deposit ${amount} recorded. Awaiting admin approval ✅")

def withdraw_flow(message):
    user_id = message.chat.id
    if not check_kyc(user_id):
        bot.send_message(user_id,"⚠️ Complete KYC first.")
        return
    amount=message.text
    if not amount.replace(".","",1).isdigit():
        bot.send_message(user_id,"Invalid amount.")
        return
    send_otp(user_id)
    msg=bot.send_message(user_id,"Enter 2FA code sent to you:")
    bot.register_next_step_handler(msg,lambda m: finalize_withdrawal_otp(user_id,float(amount),m.text))

def finalize_withdrawal_otp(user_id,amount,entered_otp):
    if not verify_otp(user_id,int(entered_otp)):
        bot.send_message(user_id,"Invalid 2FA. Withdrawal cancelled.")
        return
    msg=bot.send_message(user_id,"Enter wallet address:")
    bot.register_next_step_handler(msg,lambda m: finalize_withdrawal(user_id,amount,m.text))

def finalize_withdrawal(user_id,amount,wallet):
    add_transaction(user_id,"Withdrawal",amount,wallet)
    bot.send_message(user_id,f"Withdrawal ${amount} to {wallet} recorded. Awaiting admin approval ✅")

# ===== TRADING ENGINE =====
def place_order(user_id, pair, order_type, price, amount):
    c.execute("INSERT INTO orders(user_id,pair,order_type,price,amount,status) VALUES (?,?,?,?,?,?)",
              (user_id,pair,order_type,price,amount,"Open"))
    conn.commit()
    bot.send_message(user_id,f"Order placed: {order_type} {amount} {pair} at ${price}")

def show_portfolio(user_id):
    c.execute("SELECT pair, amount, avg_price FROM portfolio WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    if not rows:
        bot.send_message(user_id,"Portfolio empty.")
        return
    msg = "📊 Your Portfolio:\n"
    for r in rows:
        current_price = fetch_price(r[0]) or 0
        pl = (current_price - r[2])*r[1]
        msg += f"{r[0]}: {r[1]} units, Avg ${r[2]}, P/L: ${pl:.2f}\n"
    bot.send_message(user_id,msg)

# ===== PRICE ALERTS =====
def add_price_alert(user_id, pair, target_price, direction):
    c.execute("INSERT INTO alerts(user_id,pair,target_price,direction) VALUES (?,?,?,?)",
              (user_id,pair,target_price,direction))
    conn.commit()
    bot.send_message(user_id,f"Alert set for {pair} {direction} ${target_price}")

def check_alerts():
    while True:
        c.execute("SELECT rowid,user_id,pair,target_price,direction FROM alerts")
        alerts = c.fetchall()
        for alert in alerts:
            user_id = alert[1]
            pair = alert[2]
            target = alert[3]
            direction = alert[4]
            price = fetch_price(pair)
            if price:
                if (direction=="Above" and price>=target) or (direction=="Below" and price<=target):
                    bot.send_message(user_id,f"📢 ALERT: {pair} is now {direction} ${target} (Current: ${price})")
                    c.execute("DELETE FROM alerts WHERE rowid=?", (alert[0],))
                    conn.commit()
        time.sleep(60)

threading.Thread(target=check_alerts,daemon=True).start()

# ===== CHARTS =====
def send_price_chart(user_id, pair):
    prices=[]
    for _ in range(20):
        price=fetch_price(pair)
        if price:
            prices.append(price)
        time.sleep(1)
    buf = generate_chart(prices, pair)
    bot.send_photo(user_id, buf)

# ===== REFERRALS =====
def add_referral(referrer_id, referee_id):
    c.execute("INSERT INTO referrals(referrer_id,referee_id) VALUES (?,?)",(referrer_id,referee_id))
    conn.commit()
    bot.send_message(referrer_id,f"🎁 You referred user {referee_id}!")

def show_referrals(user_id):
    c.execute("SELECT referee_id,reward FROM referrals WHERE referrer_id=?", (user_id,))
    rows = c.fetchall()
    if not rows:
        bot.send_message(user_id,"No referrals yet.")
        return
    msg="🎁 Your Referrals:\n"
    for r in rows:
        msg+=f"User {r[0]} - Reward: ${r[1]:.2f}\n"
    bot.send_message(user_id,msg)

# ===== SUPPORT TICKETS =====
def create_ticket(user_id,message_text):
    c.execute("INSERT INTO support_tickets(user_id,message) VALUES (?,?)",(user_id,message_text))
    conn.commit()
    bot.send_message(user_id,"🆘 Support ticket created. Admin will respond soon.")

def list_tickets(user_id):
    if user_id not in ADMIN_IDS:
        bot.send_message(user_id,"Unauthorized")
        return
    c.execute("SELECT id,user_id,message,status FROM support_tickets WHERE status='Open'")
    rows=c.fetchall()
    if not rows:
        bot.send_message(user_id,"No open tickets.")
        return
    msg="🆘 Open Tickets:\n"
    for r in rows:
        msg+=f"ID: {r[0]}, User: {r[1]}, Msg: {r[2]}, Status: {r[3]}\n"
    bot.send_message(user_id,msg)

# ===== MAIN MENU & HANDLERS =====
def show_main_menu(user_id):
    markup=types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("Deposit 💰","Withdraw 🏦")
    markup.row("Trade 📈","Portfolio 📊")
    markup.row("Transactions 📝","Charts 📉")
    markup.row("Price Alerts 📢","Referrals 🎁")
    markup.row("Profile 👤","Support 🆘")
    bot.send_message(user_id,"Welcome! Choose an option:",reply_markup=markup)

# [MAIN MENU HANDLER CODE CONTINUED HERE: same as previous step with trade_menu, price_alert_menu, referrals_menu, support_menu]

# ===== FLASK WEBHOOK FOR RENDER =====
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

# ===== START FLASK =====
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
