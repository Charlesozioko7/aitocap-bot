import telebot
from flask import Flask
from tinydb import TinyDB, Query
import threading
import time

# ---------------- CONFIG ----------------
TOKEN = "8324820648:AAFnnA65MrpHjymTol3vBRy4iwP8DFyGxx8"  # your bot token
ADMIN_ID = 7757657728  # your Telegram ID
ADMIN_PASSWORD = "profitadmin"  # change if you want

# Wallets (as you provided)
WALLETS = {
    "BTC": "bc1qfkf8ntrr74mze6sg6qk3eunhd9lstyzs3xt640",
    "USDT-TRC20": "TLZuKgWPXczMNSdkxgDxbmjuqu1kbgExTg",
    "ETH": "0x17CfFAbFF7FDCc9a70e6E640C8cF8730a17840b2",
    "TRX": "TLZuKgWPXczMNSdkxgDxbmjuqu1kbgExTg",
    "BNB": "0x17CfFAbFF7FDCc9a70e6E640C8cF8730a17840b2"
}

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# ---------------- DB ----------------
db = TinyDB('data.json')
users_table = db.table('users')          # documents: {id: <int>, balance: <float>}
deposits_table = db.table('deposits')    # documents: {id: <int autogen>, user_id, coin, amount, txid, status, created_at}
withdrawals_table = db.table('withdrawals')  # documents: {id, user_id, coin, amount, wallet, status, created_at}
meta = db.table('meta')                  # for counters / config

# helper for IDs
def next_id(table_name):
    key = f"__nextid_{table_name}"
    rec = meta.get(Query().key == key)
    if not rec:
        meta.insert({'key': key, 'value': 1})
        return 1
    cur = rec['value']
    meta.update({'value': cur + 1}, Query().key == key)
    return cur

# ---------------- Helpers ----------------
def get_user_record(user_id):
    rec = users_table.get(Query().id == user_id)
    if not rec:
        users_table.insert({'id': user_id, 'balance': 0.0})
        rec = users_table.get(Query().id == user_id)
    return rec

def update_balance(user_id, new_balance):
    if users_table.contains(Query().id == user_id):
        users_table.update({'balance': new_balance}, Query().id == user_id)
    else:
        users_table.insert({'id': user_id, 'balance': new_balance})

def list_users():
    return users_table.all()

def add_deposit_request(user_id, coin, amount, txid=""):
    did = next_id('deposit')
    deposits_table.insert({
        'id': did,
        'user_id': user_id,
        'coin': coin,
        'amount': float(amount),
        'txid': txid,
        'status': 'pending',
        'created_at': time.time()
    })
    return did

def add_withdraw_request(user_id, coin, amount, wallet):
    wid = next_id('withdraw')
    withdrawals_table.insert({
        'id': wid,
        'user_id': user_id,
        'coin': coin,
        'amount': float(amount),
        'wallet': wallet,
        'status': 'pending',
        'created_at': time.time()
    })
    return wid

def format_money(x):
    try:
        return f"${float(x):.2f}"
    except:
        return str(x)

# ---------------- Flask keepalive ----------------
@app.route('/')
def home():
    return "✅ ProfitPlus bot is live with admin panel."

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# ---------------- Bot commands (user) ----------------

@bot.message_handler(commands=['start'])
def cmd_start(msg):
    get_user_record(msg.chat.id)
    text = (
        "👋 *Welcome to ProfitPlus!* \n\n"
        "Commands:\n"
        "/deposit - Show deposit addresses and request deposit\n"
        "/balance - View your balance\n"
        "/withdraw - Request withdrawal\n"
        "/help - Show help\n"
        "/admin - Admin login (admin only)\n\n"
        "To notify us that you've sent a deposit, either use /request_deposit or type \"I've paid\" and follow prompts."
    )
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['help'])
def cmd_help(msg):
    text = (
        "📖 *Help*\n\n"
        "/deposit - show deposit wallets\n"
        "/request_deposit - record a deposit for admin review\n"
        "/balance - view balance\n"
        "/withdraw - request a withdrawal\n"
    )
    bot.send_message(msg.chat.id, text, parse_mode="Markdown")

@bot.message_handler(commands=['deposit'])
def cmd_deposit(msg):
    lines = ["💳 *Deposit Addresses:*"]
    for k, v in WALLETS.items():
        lines.append(f"{k}: `{v}`")
    lines.append("\nAfter sending funds, run /request_deposit to tell us (or type \"I've paid\"). Admin will review and approve manually.")
    bot.send_message(msg.chat.id, "\n".join(lines), parse_mode="Markdown")

# request_deposit flow (starts when user runs command)
@bot.message_handler(commands=['request_deposit'])
def cmd_request_deposit(msg):
    bot.send_message(msg.chat.id, "🔔 Enter deposit details in the format:\nCOIN AMOUNT [TXID]\nExample: BTC 50 abc123txid (TXID optional)")
    bot.register_next_step_handler(msg, handle_request_deposit)

def handle_request_deposit(msg):
    parts = msg.text.strip().split()
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "❌ Invalid format. Use: COIN AMOUNT [TXID]")
        return
    coin = parts[0].upper()
    try:
        amount = float(parts[1])
    except:
        bot.send_message(msg.chat.id, "❌ Invalid amount. Use numbers, e.g., 50")
        return
    txid = parts[2] if len(parts) >= 3 else ""
    did = add_deposit_request(msg.chat.id, coin, amount, txid)
    bot.send_message(msg.chat.id, f"✅ Deposit request created (ID: {did}). Admin will review and confirm soon.")
    # notify admin
    bot.send_message(ADMIN_ID, f"🔔 New deposit request #{did}\nUser: {msg.chat.id}\nCoin: {coin}\nAmount: {format_money(amount)}\nTXID: {txid}\nApprove with /approve_deposit {did} or view pending with /pending_deposits")

# accept "I've paid" or variants -> start deposit step
@bot.message_handler(func=lambda m: m.text and m.text.lower().strip() in ["i've paid", "ive paid", "i have paid"])
def ive_paid_handler(msg):
    bot.send_message(msg.chat.id, "Great — enter deposit details now in format: COIN AMOUNT [TXID]\nExample: BTC 50 abc123")
    bot.register_next_step_handler(msg, handle_request_deposit)

@bot.message_handler(commands=['balance'])
def cmd_balance(msg):
    rec = get_user_record(msg.chat.id)
    bot.send_message(msg.chat.id, f"💼 Your balance: {format_money(rec['balance'])}")

# ---------------- Withdraw flow (user) ----------------
@bot.message_handler(commands=['withdraw'])
def cmd_withdraw(msg):
    bot.send_message(msg.chat.id, "💵 Enter withdrawal request: COIN AMOUNT\nExample: USDT-TRC20 10")
    bot.register_next_step_handler(msg, handle_withdraw_amount)

def handle_withdraw_amount(msg):
    parts = msg.text.strip().split()
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "❌ Invalid format. Use: COIN AMOUNT")
        return
    coin = parts[0].upper()
    try:
        amount = float(parts[1])
    except:
        bot.send_message(msg.chat.id, "❌ Invalid amount.")
        return
    rec = get_user_record(msg.chat.id)
    if amount > rec['balance']:
        bot.send_message(msg.chat.id, f"❌ Insufficient balance ({format_money(rec['balance'])}).")
        return
    bot.send_message(msg.chat.id, "🏦 Enter destination wallet address for withdrawal:")
    bot.register_next_step_handler(msg, handle_withdraw_wallet, coin, amount)

def handle_withdraw_wallet(msg, coin, amount):
    wallet = msg.text.strip()
    wid = add_withdraw_request(msg.chat.id, coin, amount, wallet)
    bot.send_message(msg.chat.id, f"✅ Withdrawal request created (ID: {wid}). Admin will review and confirm.")
    bot.send_message(ADMIN_ID, f"🔔 New withdrawal #{wid}\nUser: {msg.chat.id}\nCoin: {coin}\nAmount: {format_money(amount)}\nWallet: {wallet}\nApprove with /approve_withdraw {wid}")

# ---------------- Admin: login + panel ----------------
admin_sessions = {}  # chat_id -> True

@bot.message_handler(commands=['admin'])
def cmd_admin(msg):
    if msg.chat.id != ADMIN_ID:
        bot.send_message(msg.chat.id, "🚫 You are not authorized to use admin.")
        return
    bot.send_message(msg.chat.id, "🔐 Enter admin password:")
    bot.register_next_step_handler(msg, verify_admin)

def verify_admin(msg):
    if msg.chat.id != ADMIN_ID:
        return
    if msg.text == ADMIN_PASSWORD:
        admin_sessions[msg.chat.id] = True
        # show inline admin menu
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(telebot.types.InlineKeyboardButton("✅ Approve Deposits", callback_data="admin_approve_deposits"))
        markup.add(telebot.types.InlineKeyboardButton("📝 Withdraw Requests", callback_data="admin_withdrawals"))
        markup.add(telebot.types.InlineKeyboardButton("👥 View Users", callback_data="admin_view_users"))
        markup.add(telebot.types.InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast"))
        markup.add(telebot.types.InlineKeyboardButton("⚙️ Settings", callback_data="admin_settings"))
        bot.send_message(msg.chat.id, "🔑 Admin logged in. Choose an option:", reply_markup=markup)
    else:
        bot.send_message(msg.chat.id, "❌ Incorrect password.")

@bot.message_handler(commands=['logout'])
def cmd_logout(msg):
    admin_sessions.pop(msg.chat.id, None)
    bot.send_message(msg.chat.id, "👋 Logged out of admin mode.")

# ---------------- Admin commands for quick usage ----------------
@bot.message_handler(commands=['pending_deposits'])
def cmd_pending_deposits(msg):
    if msg.chat.id != ADMIN_ID:
        return
    pend = deposits_table.search(Query().status == 'pending')
    if not pend:
        bot.send_message(msg.chat.id, "No pending deposits.")
        return
    text_lines = ["🔎 Pending deposits:"]
    for d in pend:
        text_lines.append(f"ID:{d['id']} User:{d['user_id']} {d['coin']} {format_money(d['amount'])} TXID:{d.get('txid','')}")
    bot.send_message(msg.chat.id, "\n".join(text_lines))

@bot.message_handler(commands=['pending_withdrawals'])
def cmd_pending_withdrawals(msg):
    if msg.chat.id != ADMIN_ID:
        return
    pend = withdrawals_table.search(Query().status == 'pending')
    if not pend:
        bot.send_message(msg.chat.id, "No pending withdrawals.")
        return
    text_lines = ["🔎 Pending withdrawals:"]
    for w in pend:
        text_lines.append(f"ID:{w['id']} User:{w['user_id']} {w['coin']} {format_money(w['amount'])} -> {w['wallet']}")
    bot.send_message(msg.chat.id, "\n".join(text_lines))

@bot.message_handler(commands=['approve_deposit'])
def cmd_approve_deposit(msg):
    if msg.chat.id != ADMIN_ID: return
    parts = msg.text.split()
    if len(parts) != 2:
        bot.send_message(msg.chat.id, "Usage: /approve_deposit <deposit_id>")
        return
    try:
        did = int(parts[1])
    except:
        bot.send_message(msg.chat.id, "Invalid deposit id.")
        return
    rec = deposits_table.get(Query().id == did)
    if not rec or rec.get('status') != 'pending':
        bot.send_message(msg.chat.id, "Deposit not found or already processed.")
        return
    # credit user
    uid = rec['user_id']
    amt = rec['amount']
    user_rec = get_user_record(uid)
    new_bal = user_rec['balance'] + amt
    update_balance(uid, new_bal)
    deposits_table.update({'status': 'approved'}, Query().id == did)
    bot.send_message(msg.chat.id, f"✅ Deposit #{did} approved. User {uid} credited {format_money(amt)}.")
    bot.send_message(uid, f"💰 Your deposit (ID: {did}) of {format_money(amt)} has been *approved* by admin. New balance: {format_money(new_bal)}", parse_mode="Markdown")

@bot.message_handler(commands=['reject_deposit'])
def cmd_reject_deposit(msg):
    if msg.chat.id != ADMIN_ID: return
    parts = msg.text.split()
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "Usage: /reject_deposit <deposit_id> [reason]")
        return
    try:
        did = int(parts[1])
    except:
        bot.send_message(msg.chat.id, "Invalid deposit id.")
        return
    rec = deposits_table.get(Query().id == did)
    if not rec or rec.get('status') != 'pending':
        bot.send_message(msg.chat.id, "Deposit not found or already processed.")
        return
    deposits_table.update({'status': 'rejected'}, Query().id == did)
    uid = rec['user_id']
    bot.send_message(msg.chat.id, f"❌ Deposit #{did} rejected.")
    bot.send_message(uid, f"❌ Your deposit (ID: {did}) has been rejected by admin. Please contact support.")

@bot.message_handler(commands=['approve_withdraw'])
def cmd_approve_withdraw(msg):
    if msg.chat.id != ADMIN_ID: return
    parts = msg.text.split()
    if len(parts) != 2:
        bot.send_message(msg.chat.id, "Usage: /approve_withdraw <withdraw_id>")
        return
    try:
        wid = int(parts[1])
    except:
        bot.send_message(msg.chat.id, "Invalid withdraw id.")
        return
    rec = withdrawals_table.get(Query().id == wid)
    if not rec or rec.get('status') != 'pending':
        bot.send_message(msg.chat.id, "Withdraw not found or already processed.")
        return
    uid = rec['user_id']
    amt = rec['amount']
    # verify user has enough (should be validated previously, but double-check)
    user_rec = get_user_record(uid)
    if user_rec['balance'] < amt:
        bot.send_message(msg.chat.id, f"❌ User {uid} has insufficient balance.")
        withdrawals_table.update({'status': 'rejected'}, Query().id == wid)
        bot.send_message(uid, "❌ Your withdrawal was rejected due to insufficient balance.")
        return
    # deduct and mark approved
    new_bal = user_rec['balance'] - amt
    update_balance(uid, new_bal)
    withdrawals_table.update({'status': 'approved'}, Query().id == wid)
    bot.send_message(msg.chat.id, f"✅ Withdrawal #{wid} approved. User {uid} debited {format_money(amt)}.")
    bot.send_message(uid, f"💸 Your withdrawal (ID: {wid}) of {format_money(amt)} has been approved by admin. New balance: {format_money(new_bal)}")

@bot.message_handler(commands=['reject_withdraw'])
def cmd_reject_withdraw(msg):
    if msg.chat.id != ADMIN_ID: return
    parts = msg.text.split()
    if len(parts) < 2:
        bot.send_message(msg.chat.id, "Usage: /reject_withdraw <withdraw_id> [reason]")
        return
    try:
        wid = int(parts[1])
    except:
        bot.send_message(msg.chat.id, "Invalid withdraw id.")
        return
    rec = withdrawals_table.get(Query().id == wid)
    if not rec or rec.get('status') != 'pending':
        bot.send_message(msg.chat.id, "Withdraw not found or already processed.")
        return
    withdrawals_table.update({'status': 'rejected'}, Query().id == wid)
    uid = rec['user_id']
    bot.send_message(msg.chat.id, f"❌ Withdrawal #{wid} rejected.")
    bot.send_message(uid, f"❌ Your withdrawal (ID: {wid}) has been rejected by admin. Contact support for details.")

# broadcast (admin)
@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(msg):
    if msg.chat.id != ADMIN_ID:
        return
    # next step will be the message text
    bot.send_message(msg.chat.id, "Enter the message to broadcast to ALL users:")
    bot.register_next_step_handler(msg, handle_broadcast)

def handle_broadcast(msg):
    if msg.chat.id != ADMIN_ID:
        return
    text = msg.text
    users = list_users()
    sent = 0
    for u in users:
        try:
            bot.send_message(u['id'], f"📢 Announcement:\n\n{text}")
            sent += 1
        except:
            pass
    bot.send_message(msg.chat.id, f"✅ Broadcast sent to {sent} users.")

# view users (admin)
@bot.message_handler(commands=['users'])
def cmd_users(msg):
    if msg.chat.id != ADMIN_ID:
        return
    users = list_users()
    if not users:
        bot.send_message(msg.chat.id, "No registered users.")
        return
    lines = ["👥 Registered users:"]
    for u in users:
        lines.append(f"ID: {u['id']} — Balance: {format_money(u['balance'])}")
    bot.send_message(msg.chat.id, "\n".join(lines))

# ---------------- Inline admin callbacks ----------------
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_"))
def admin_callbacks(call):
    if call.message.chat.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Unauthorized")
        return

    key = call.data.split("_", 1)[1]

    if key == "approve_deposits":
        pend = deposits_table.search(Query().status == 'pending')
        if not pend:
            bot.edit_message_text("No pending deposits.", call.message.chat.id, call.message.message_id)
            return
        # show first 5 pending with inline approve/reject buttons
        for d in pend[:8]:
            text = f"Deposit ID:{d['id']}\nUser:{d['user_id']}\nCoin:{d['coin']} Amount:{format_money(d['amount'])}\nTXID:{d.get('txid','')}\nStatus:{d['status']}"
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("Approve", callback_data=f"approve_dep:{d['id']}"),
                       telebot.types.InlineKeyboardButton("Reject", callback_data=f"reject_dep:{d['id']}"))
            bot.send_message(call.message.chat.id, text, reply_markup=markup)
        bot.answer_callback_query(call.id, "Showing pending deposits...")

    elif key == "withdrawals":
        pend = withdrawals_table.search(Query().status == 'pending')
        if not pend:
            bot.edit_message_text("No pending withdrawals.", call.message.chat.id, call.message.message_id)
            return
        for w in pend[:8]:
            text = f"Withdraw ID:{w['id']}\nUser:{w['user_id']}\nCoin:{w['coin']} Amount:{format_money(w['amount'])}\nWallet:{w['wallet']}\nStatus:{w['status']}"
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(telebot.types.InlineKeyboardButton("Approve", callback_data=f"approve_wd:{w['id']}"),
                       telebot.types.InlineKeyboardButton("Reject", callback_data=f"reject_wd:{w['id']}"))
            bot.send_message(call.message.chat.id, text, reply_markup=markup)
        bot.answer_callback_query(call.id, "Showing pending withdrawals...")

    elif key == "view_users":
        users = list_users()
        if not users:
            bot.edit_message_text("No users yet.", call.message.chat.id, call.message.message_id)
            return
        text = "👥 Users:\n"
        for u in users[:50]:
            text += f"ID:{u['id']} Bal:{format_money(u['balance'])}\n"
        bot.send_message(call.message.chat.id, text)
        bot.answer_callback_query(call.id, "Users listed.")

    elif key == "broadcast":
        bot.send_message(call.message.chat.id, "Enter broadcast message (use /broadcast command):")
        bot.answer_callback_query(call.id, "Use /broadcast to send message.")

    elif key == "settings":
        # show wallets and simple info
        text = "⚙️ Settings\nWallets:"
        for k, v in WALLETS.items():
            text += f"\n{k}: {v}"
        bot.send_message(call.message.chat.id, text)
        bot.answer_callback_query(call.id, "Settings shown.")

# action callbacks approve/reject deposit & withdraw
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_dep:") or call.data.startswith("reject_dep:") or call.data.startswith("approve_wd:") or call.data.startswith("reject_wd:"))
def action_callbacks(call):
    if call.message.chat.id != ADMIN_ID:
        bot.answer_callback_query(call.id, "Unauthorized")
        return
    data = call.data
    if data.startswith("approve_dep:"):
        did = int(data.split(":",1)[1])
        rec = deposits_table.get(Query().id == did)
        if not rec or rec.get('status') != 'pending':
            bot.answer_callback_query(call.id, "Not found/already processed")
            return
        uid = rec['user_id']; amt = rec['amount']
        # credit user
        user_rec = get_user_record(uid)
        new_bal = user_rec['balance'] + amt
        update_balance(uid, new_bal)
        deposits_table.update({'status':'approved'}, Query().id == did)
        bot.send_message(call.message.chat.id, f"✅ Deposit #{did} approved.")
        bot.send_message(uid, f"💰 Your deposit (ID: {did}) of {format_money(amt)} was approved. New balance: {format_money(new_bal)}")
        bot.answer_callback_query(call.id, "Deposit approved")
    elif data.startswith("reject_dep:"):
        did = int(data.split(":",1)[1])
        rec = deposits_table.get(Query().id == did)
        if not rec or rec.get('status') != 'pending':
            bot.answer_callback_query(call.id, "Not found/already processed")
            return
        deposits_table.update({'status':'rejected'}, Query().id == did)
        uid = rec['user_id']
        bot.send_message(call.message.chat.id, f"❌ Deposit #{did} rejected.")
        bot.send_message(uid, f"❌ Your deposit (ID: {did}) was rejected by admin.")
        bot.answer_callback_query(call.id, "Deposit rejected")
    elif data.startswith("approve_wd:"):
        wid = int(data.split(":",1)[1])
        rec = withdrawals_table.get(Query().id == wid)
        if not rec or rec.get('status') != 'pending':
            bot.answer_callback_query(call.id, "Not found/already processed")
            return
        uid = rec['user_id']; amt = rec['amount']
        user_rec = get_user_record(uid)
        if user_rec['balance'] < amt:
            withdrawals_table.update({'status':'rejected'}, Query().id == wid)
            bot.send_message(call.message.chat.id, f"❌ User {uid} has insufficient balance. Withdrawal rejected.")
            bot.send_message(uid, f"❌ Your withdrawal (ID: {wid}) was rejected due to insufficient balance.")
            bot.answer_callback_query(call.id, "Insufficient funds")
            return
        new_bal = user_rec['balance'] - amt
        update_balance(uid, new_bal)
        withdrawals_table.update({'status':'approved'}, Query().id == wid)
        bot.send_message(call.message.chat.id, f"✅ Withdrawal #{wid} approved.")
        bot.send_message(uid, f"💸 Your withdrawal (ID: {wid}) of {format_money(amt)} has been approved. New balance: {format_money(new_bal)}")
        bot.answer_callback_query(call.id, "Withdrawal approved")
    elif data.startswith("reject_wd:"):
        wid = int(data.split(":",1)[1])
        rec = withdrawals_table.get(Query().id == wid)
        if not rec or rec.get('status') != 'pending':
            bot.answer_callback_query(call.id, "Not found/already processed")
            return
        withdrawals_table.update({'status':'rejected'}, Query().id == wid)
        uid = rec['user_id']
        bot.send_message(call.message.chat.id, f"❌ Withdrawal #{wid} rejected.")
        bot.send_message(uid, f"❌ Your withdrawal (ID: {wid}) was rejected by admin.")
        bot.answer_callback_query(call.id, "Withdrawal rejected")

# ---------------- Safety / startup ----------------
def run_bot():
    print("🤖 ProfitPlus bot starting (polling)...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    # Start Flask and bot threads
    threading.Thread(target=run_flask).start()
    run_bot()
