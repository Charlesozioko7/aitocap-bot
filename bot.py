# bot.py -- ProfitPlus (AitoCap clone) with manual withdrawals + admin pagination + Approve All
# Requirements: pyTelegramBotAPI, flask, requests
# Env vars recommended: TOKEN, ADMIN_ID, WEBHOOK_BASE (or RENDER_EXTERNAL_URL)

import os
import json
import re
import time
import uuid
from datetime import datetime
from flask import Flask, request
import telebot
from telebot import types

# ---------------- CONFIG ----------------
TOKEN = os.getenv("TOKEN") or "8324820648:AAFnnA65MrpHjymTol3vBRy4iwP8DFyGxx8"
ADMIN_ID = int(os.getenv("ADMIN_ID") or 7623720521)
BOT_NAME = os.getenv("BOT_NAME") or "ProfitPlus"
DATA_FILE = "data.json"

WEBHOOK_BASE = os.getenv("WEBHOOK_BASE") or os.getenv("RENDER_EXTERNAL_URL") or "https://aitocap-bot.onrender.com"
WEBHOOK_URL = f"{WEBHOOK_BASE.rstrip('/')}/{TOKEN}"

DEPOSIT_ADDR = {
    "BTC": "bc1qfkf8ntrr74mze6sg6qk3eunhd9lstyzs3xt640",
    "USDT-TRC20": "TLZuKgWPXczMNSdkxgDxbmjuqu1kbgExTg",
    "ETH": "0x17CfFAbFF7FDCc9a70e6E640C8cF8730a17840b2",
    "TRX": "TLZuKgWPXczMNSdkxgDxbmjuqu1kbgExTg",
    "BNB": "0x17CfFAbFF7FDCc9a70e6E640C8cF8730a17840b2"
}
COINS = list(DEPOSIT_ADDR.keys())
MIN_WITHDRAW_USD = 10.0

# ---------------- helpers ----------------
def escape_md_v2(text: str) -> str:
    # Escape characters for MarkdownV2
    to_escape = r"_*[]()~`>#+-=|{}.!\\"
    return re.sub(r"([" + re.escape(to_escape) + r"])", r"\\\1", text)

def load_db():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_db(db):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("save_db error:", e)

db = load_db()

def ensure_user(uid):
    uid = str(uid)
    if uid not in db:
        db[uid] = {
            "balances": { "real": {c: 0.0 for c in COINS}, "demo": {c: 0.0 for c in COINS} },
            "transactions": [],
            "pending_deposits": [],
            "pending_withdrawals": []
        }
        db[uid]["balances"]["demo"]["USDT-TRC20"] = 100.0
        save_db(db)
    return db[uid]

def format_balances(user, mode="real"):
    bal = user["balances"].get(mode, {})
    return "\n".join([f"{escape_md_v2(c)}: {bal.get(c,0):.6f}" for c in COINS])

# ---------------- app & bot ----------------
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# transient state for user flows
flow_state = {}  # { user_id_str: {"action":..., ...} }

# ---------------- keyboards ----------------
def main_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("💰 Deposit", callback_data="deposit"),
           types.InlineKeyboardButton("💸 Withdraw", callback_data="withdraw"))
    kb.add(types.InlineKeyboardButton("📊 Balances", callback_data="balances"),
           types.InlineKeyboardButton("📜 History", callback_data="history"))
    kb.add(types.InlineKeyboardButton("🛠 Admin Panel", callback_data="admin_panel"))
    return kb

def deposit_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    for c in COINS:
        kb.add(types.InlineKeyboardButton(c, callback_data=f"deposit_{c}"))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="menu"))
    return kb

def withdraw_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    for c in COINS:
        kb.add(types.InlineKeyboardButton(c, callback_data=f"withdraw_{c}"))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="menu"))
    return kb

def admin_pending_kb(page=0, total=0):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(types.InlineKeyboardButton("Approve All", callback_data="admin_approve_all"))
    kb.add(types.InlineKeyboardButton("Refresh", callback_data="admin_pending"))
    # pagination controls
    kb.add(types.InlineKeyboardButton("⬅️ Prev", callback_data=f"admin_prev_{page}"),
           types.InlineKeyboardButton("Next ➡️", callback_data=f"admin_next_{page}"))
    kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="menu"))
    return kb

# ---------------- safe send ----------------
def send_safe(chat_id, text, reply_markup=None):
    try:
        bot.send_message(chat_id, escape_md_v2(text), parse_mode="MarkdownV2", reply_markup=reply_markup)
    except Exception:
        try:
            bot.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception as e:
            print("send_safe failed:", e)

# ---------------- commands ----------------
@bot.message_handler(commands=['start'])
def cmd_start(m):
    ensure_user(m.from_user.id)
    txt = (f"👋 Welcome to *{BOT_NAME}*!\n\n"
           "Use the menu below to Deposit, Withdraw, view Balances or History.")
    send_safe(m.chat.id, txt, reply_markup=main_kb())

@bot.message_handler(commands=['help'])
def cmd_help(m):
    send_safe(m.chat.id, "Commands: /start, /help. Use the menu.", reply_markup=main_kb())

# ---------------- webhook endpoints ----------------
@app.route("/", methods=["GET"])
def index():
    return f"{BOT_NAME} running", 200

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    json_str = request.get_data().decode("utf-8")
    if not json_str:
        return "ok", 200
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "ok", 200

# ---------------- admin helpers ----------------
def collect_all_pending_withdrawals():
    # returns list of dicts with user_id, entry
    out = []
    for user_id, u in db.items():
        for w in u.get("pending_withdrawals", []):
            out.append({"user_id": user_id, "entry": w})
    # sort by time
    out.sort(key=lambda x: x["entry"].get("time",""))
    return out

def paginate(items, page, page_size=4):
    total = len(items)
    start = page * page_size
    end = start + page_size
    return items[start:end], total

# ---------------- callback handler ----------------
@bot.callback_query_handler(func=lambda c: True)
def on_callback(call):
    uid = call.from_user.id
    ensure_user(uid)
    data = call.data

    if data == "menu":
        send_safe(uid, "Main menu:", reply_markup=main_kb())
        return

    if data == "deposit":
        send_safe(uid, "Choose coin to deposit:", reply_markup=deposit_kb())
        return

    if data.startswith("deposit_"):
        coin = data.split("_",1)[1]
        addr = DEPOSIT_ADDR.get(coin, "N/A")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ I sent funds (Confirm)", callback_data=f"confirm_deposit_{coin}"))
        kb.add(types.InlineKeyboardButton("⬅️ Back", callback_data="deposit"))
        send_safe(uid, f"💰 *{coin} Deposit Address*\n\nSend {coin} to:\n`{addr}`\n\nAfter sending, press Confirm and paste tx hash or amount.", reply_markup=kb)
        return

    if data.startswith("confirm_deposit_"):
        coin = data.split("_",2)[2]
        flow_state[str(uid)] = {"action":"confirm_deposit", "coin":coin}
        send_safe(uid, f"Paste the TX hash or enter the amount you sent for {coin}:")
        return

    if data == "withdraw":
        send_safe(uid, "Choose coin to withdraw (min $10):", reply_markup=withdraw_kb())
        return

    if data.startswith("withdraw_"):
        coin = data.split("_",1)[1]
        flow_state[str(uid)] = {"action":"withdraw_amount", "coin":coin}
        send_safe(uid, f"Enter amount in USD to withdraw for {coin} (minimum ${MIN_WITHDRAW_USD:.2f}):")
        return

    if data == "balances":
        user = db.get(str(uid))
        if not user:
            ensure_user(uid)
            user = db[str(uid)]
        text = f"📊 Balances (real):\n{format_balances(user, 'real')}\n\n📊 Demo Balances:\n{format_balances(user, 'demo')}"
        send_safe(uid, text, reply_markup=main_kb())
        return

    if data == "history":
        user = db.get(str(uid), {})
        txs = user.get("transactions", [])[-20:]
        if not txs:
            send_safe(uid, "No transactions yet.", reply_markup=main_kb())
            return
        lines = []
        for t in reversed(txs):
            tm = t.get("time","")[:19].replace("T"," ")
            lines.append(f"{tm} — {t.get('type')} — {t.get('coin','')} {t.get('amount','')}")
        send_safe(uid, "📜 Last transactions:\n" + "\n".join(lines), reply_markup=main_kb())
        return

    # Admin panel
    if data == "admin_panel":
        if call.from_user.id != ADMIN_ID:
            send_safe(uid, "Admin panel is restricted.")
            return
        send_safe(uid, "Admin Panel — Pending withdrawals:", reply_markup=admin_pending_kb(page=0))
        # Immediately show first page
        show_admin_pending_page(0)
        return

    if data == "admin_pending":
        if call.from_user.id != ADMIN_ID:
            send_safe(uid, "Admin only.")
            return
        show_admin_pending_page(0)
        return

    if data.startswith("admin_prev_") or data.startswith("admin_next_"):
        if call.from_user.id != ADMIN_ID:
            send_safe(uid, "Admin only.")
            return
        parts = data.split("_")
        cur = int(parts[-1]) if parts[-1].isdigit() else 0
        if data.startswith("admin_prev_"):
            page = max(0, cur-1)
        else:
            page = cur+1
        show_admin_pending_page(page)
        return

    if data == "admin_approve_all":
        if call.from_user.id != ADMIN_ID:
            send_safe(uid, "Admin only.")
            return
        approved = []
        skipped = []
        pend = collect_all_pending_withdrawals()
        for item in pend:
            user_id = item["user_id"]
            w = item["entry"]
            coin = w["coin"]
            amount = float(w.get("amount",0) or 0)
            user = db.get(str(user_id))
            if not user:
                skipped.append((user_id, coin, amount, "user missing"))
                continue
            bal = user["balances"]["real"].get(coin,0.0)
            if bal >= amount:
                user["balances"]["real"][coin] = round(bal - amount, 6)
                try:
                    user["pending_withdrawals"].remove(w)
                except:
                    pass
                user["transactions"].append({"type":"withdraw_confirmed","coin":coin,"amount":amount,"time":datetime.utcnow().isoformat()})
                save_db(db)
                approved.append((user_id, coin, amount, w.get("address")))
                try:
                    send_safe(user_id, f"✅ Your withdrawal of {amount} {coin} was approved by admin (bulk).")
                except:
                    pass
            else:
                skipped.append((user_id, coin, amount, "insufficient balance"))
        # summary to admin
        msg = f"Approve All completed. Approved: {len(approved)}. Skipped: {len(skipped)}."
        if approved:
            msg += "\n\nApproved examples:\n" + "\n".join([f"{a[0]} {a[2]} {a[1]}" for a in approved[:8]])
        if skipped:
            msg += "\n\nSkipped examples:\n" + "\n".join([f"{s[0]} {s[2]} {s[1]} ({s[3]})" for s in skipped[:8]])
        send_safe(ADMIN_ID, msg)
        return

    # Approve / Reject single pending via callback pattern approve_<user>_<wid>
    if data.startswith("approve_") or data.startswith("reject_"):
        if call.from_user.id != ADMIN_ID:
            send_safe(uid, "Admin only.")
            return
        parts = data.split("_",2)
        action = parts[0]
        target_user = parts[1]
        wid = parts[2] if len(parts) > 2 else ""
        u = db.get(str(target_user))
        if not u:
            send_safe(ADMIN_ID, "User not found.")
            return
        found = None
        for w in list(u.get("pending_withdrawals", [])):
            if w.get("id") == wid:
                found = w
                break
        if not found:
            send_safe(ADMIN_ID, "Pending withdrawal not found (maybe already processed).")
            return
        coin = found.get("coin")
        amount = float(found.get("amount",0) or 0)
        addr = found.get("address")
        if action == "approve":
            bal = u["balances"]["real"].get(coin,0.0)
            if bal >= amount:
                u["balances"]["real"][coin] = round(bal - amount, 6)
                try:
                    u["pending_withdrawals"].remove(found)
                except:
                    pass
                u["transactions"].append({"type":"withdraw_confirmed","coin":coin,"amount":amount,"time":datetime.utcnow().isoformat()})
                save_db(db)
                send_safe(target_user, f"✅ Your withdrawal of {amount} {coin} has been approved by admin.")
                send_safe(ADMIN_ID, f"✅ Approved withdrawal for {target_user}: {amount} {coin} -> `{addr}`")
            else:
                send_safe(ADMIN_ID, f"❌ Insufficient balance for user {target_user}.")
        else:
            try:
                u["pending_withdrawals"].remove(found)
            except:
                pass
            u["transactions"].append({"type":"withdraw_rejected","coin":coin,"amount":amount,"time":datetime.utcnow().isoformat()})
            save_db(db)
            send_safe(target_user, f"❌ Your withdrawal request for {amount} {coin} was rejected by admin.")
            send_safe(ADMIN_ID, f"❌ Rejected withdrawal for {target_user}: {amount} {coin}")
        return

    send_safe(uid, "Unknown action. Returning to menu.", reply_markup=main_kb())

# ---------------- show paginated admin page ----------------
def show_admin_pending_page(page=0, page_size=4):
    items = collect_all_pending_withdrawals()
    page_items, total = paginate(items, page, page_size)
    pages = (total + page_size - 1) // page_size if total else 1
    if not page_items:
        send_safe(ADMIN_ID, f"No pending withdrawals (page {page+1}/{pages}).", reply_markup=admin_pending_kb(page, total))
        return
    for item in page_items:
        user_id = item["user_id"]
        w = item["entry"]
        wid = w.get("id")
        coin = w.get("coin")
        amount = w.get("amount")
        addr = w.get("address")
        t = w.get("time")
        text = (f"🔔 Pending\nUser: {user_id}\nCoin: {coin}\nAmount: {amount}\nAddress: `{addr}`\nTime: {t}\nID: {wid}")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_{user_id}_{wid}"),
               types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{user_id}_{wid}"))
        try:
            bot.send_message(ADMIN_ID, escape_md_v2(text), parse_mode="MarkdownV2", reply_markup=kb)
        except:
            bot.send_message(ADMIN_ID, text, reply_markup=kb)
    # footer navigation
    send_safe(ADMIN_ID, f"Page {page+1}/{pages} — showing {len(page_items)} of {total}", reply_markup=admin_pending_kb(page, total))

# ---------------- message handler (flows + admin text commands) ----------------
@bot.message_handler(func=lambda m: True)
def on_message(m):
    uid = m.from_user.id
    ensure_user(uid)
    text = (m.text or "").strip()

    st = flow_state.get(str(uid))
    if st:
        action = st.get("action")
        coin = st.get("coin")
        if action == "confirm_deposit":
            val = text
            try:
                amt = float(val)
                entry = {"coin": coin, "amount": amt, "time": datetime.utcnow().isoformat()}
                db[str(uid)]["pending_deposits"].append(entry)
                db[str(uid)]["transactions"].append({"type":"deposit_request","coin":coin,"amount":amt,"time":entry["time"]})
                save_db(db)
                send_safe(uid, f"🔔 Deposit request recorded: {amt} {coin}. Admin will verify.")
                send_safe(ADMIN_ID, f"🔔 Deposit request from {uid}: {amt} {coin}\nApprove with: /confirm_deposit {uid} {coin} {amt}")
            except:
                entry = {"coin": coin, "tx": val, "time": datetime.utcnow().isoformat()}
                db[str(uid)]["pending_deposits"].append(entry)
                db[str(uid)]["transactions"].append({"type":"deposit_request_tx","coin":coin,"tx":val,"time":entry["time"]})
                save_db(db)
                send_safe(uid, "🔔 Deposit proof recorded. Admin will verify and credit your account.")
                send_safe(ADMIN_ID, f"🔔 Deposit proof from {uid} for {coin}. TX: `{val}`\nTo credit: /confirm_deposit {uid} {coin} <amount>")
            flow_state.pop(str(uid), None)
            return

        if action == "withdraw_amount":
            try:
                amt = float(text)
            except:
                send_safe(uid, "❌ Invalid amount. Withdraw canceled.", reply_markup=main_kb())
                flow_state.pop(str(uid), None)
                return
            if amt < MIN_WITHDRAW_USD:
                send_safe(uid, f"❌ Minimum withdrawal is ${MIN_WITHDRAW_USD:.2f}. Enter /withdraw again.", reply_markup=main_kb())
                flow_state.pop(str(uid), None)
                return
            flow_state[str(uid)] = {"action":"withdraw_address", "coin": coin, "amount": amt}
            send_safe(uid, "Enter the destination wallet address (paste the full address):")
            return

        if action == "withdraw_address":
            address = text
            amount = st.get("amount")
            coin = st.get("coin")
            wid = str(uuid.uuid4())
            entry = {"id": wid, "coin": coin, "amount": amount, "address": address, "time": datetime.utcnow().isoformat()}
            db[str(uid)]["pending_withdrawals"].append(entry)
            db[str(uid)]["transactions"].append({"type":"withdraw_request","coin":coin,"amount":amount,"address":address,"time":entry["time"]})
            save_db(db)
            flow_state.pop(str(uid), None)
            send_safe(uid, f"🔔 Withdrawal request submitted: {amount} {coin} to:\n`{address}`\nPlease wait for admin approval.", reply_markup=main_kb())
            # notify admin with buttons
            admin_msg = (f"🔔 Withdrawal request from {uid} (@{m.from_user.username or 'unknown'}):\n"
                         f"Amount: {amount} {coin}\nAddress: `{address}`\nTime: {entry['time']}")
            kb = types.InlineKeyboardMarkup()
            kb.add(types.InlineKeyboardButton("✅ Approve", callback_data=f"approve_{uid}_{wid}"),
                   types.InlineKeyboardButton("❌ Reject", callback_data=f"reject_{uid}_{wid}"))
            try:
                bot.send_message(ADMIN_ID, escape_md_v2(admin_msg), parse_mode="MarkdownV2", reply_markup=kb)
            except:
                bot.send_message(ADMIN_ID, admin_msg, reply_markup=kb)
            return

    # Admin text commands
    if text.lower().startswith("/confirm_deposit") and m.from_user.id == ADMIN_ID:
        parts = text.split()
        if len(parts) != 4:
            send_safe(ADMIN_ID, "Usage: /confirm_deposit <user_id> <coin> <amount>")
            return
        _, user_id, coin, amount = parts
        try:
            amount = float(amount)
        except:
            send_safe(ADMIN_ID, "Invalid amount.")
            return
        if user_id not in db:
            send_safe(ADMIN_ID, "User not found.")
            return
        u = db[user_id]
        u["balances"]["real"][coin] = round(u["balances"]["real"].get(coin,0.0) + amount, 6)
        # remove matching pending deposit if present
        for p in list(u.get("pending_deposits", [])):
            if p.get("coin") == coin and float(p.get("amount",0) or 0) == amount:
                try:
                    u["pending_deposits"].remove(p)
                    break
                except:
                    pass
        u["transactions"].append({"type":"deposit_confirmed","coin":coin,"amount":amount,"time":datetime.utcnow().isoformat()})
        save_db(db)
        send_safe(user_id, f"✅ Your deposit of {amount} {coin} has been approved by admin.")
        send_safe(ADMIN_ID, f"✅ Deposit confirmed for user {user_id}: {amount} {coin}.")
        return

    if text.lower().startswith("/confirm_withdraw") and m.from_user.id == ADMIN_ID:
        parts = text.split()
        if len(parts) != 4:
            send_safe(ADMIN_ID, "Usage: /confirm_withdraw <user_id> <coin> <amount>")
            return
        _, user_id, coin, amount = parts
        try:
            amount = float(amount)
        except:
            send_safe(ADMIN_ID, "Invalid amount.")
            return
        if user_id not in db:
            send_safe(ADMIN_ID, "User not found.")
            return
        u = db[user_id]
        bal = u["balances"]["real"].get(coin, 0.0)
        if bal >= amount:
            u["balances"]["real"][coin] = round(bal - amount, 6)
            for w in list(u.get("pending_withdrawals", [])):
                if w.get("coin")==coin and float(w.get("amount",0) or 0) == amount:
                    addr = w.get("address")
                    try:
                        u["pending_withdrawals"].remove(w)
                    except:
                        pass
                    break
            u["transactions"].append({"type":"withdraw_confirmed","coin":coin,"amount":amount,"time":datetime.utcnow().isoformat()})
            save_db(db)
            send_safe(user_id, f"✅ Your withdrawal of {amount} {coin} has been approved by admin.")
            send_safe(ADMIN_ID, f"✅ Withdrawal confirmed for user {user_id}: {amount} {coin}.")
        else:
            send_safe(ADMIN_ID, f"❌ User {user_id} has insufficient balance.")
        return

    if text.lower().startswith("/reject_withdraw") and m.from_user.id == ADMIN_ID:
        parts = text.split()
        if len(parts) != 4:
            send_safe(ADMIN_ID, "Usage: /reject_withdraw <user_id> <coin> <amount>")
            return
        _, user_id, coin, amount = parts
        try:
            amount = float(amount)
        except:
            send_safe(ADMIN_ID, "Invalid amount.")
            return
        if user_id not in db:
            send_safe(ADMIN_ID, "User not found.")
            return
        u = db[user_id]
        removed = False
        for w in list(u.get("pending_withdrawals", [])):
            if w.get("coin")==coin and float(w.get("amount",0) or 0) == amount:
                try:
                    u["pending_withdrawals"].remove(w)
                    removed = True
                    break
                except:
                    pass
        if removed:
            u["transactions"].append({"type":"withdraw_rejected","coin":coin,"amount":amount,"time":datetime.utcnow().isoformat()})
            save_db(db)
            send_safe(user_id, f"❌ Your withdrawal request for {amount} {coin} was rejected by admin.")
            send_safe(ADMIN_ID, f"❌ Withdrawal for user {user_id} rejected: {amount} {coin}.")
        else:
            send_safe(ADMIN_ID, "No matching pending withdrawal found.")
        return

    # user text flows
    if text.lower() in ("/withdraw", "withdraw"):
        send_safe(uid, "Choose coin to withdraw:", reply_markup=withdraw_kb())
        return

    if text.lower() in ("/balance", "balance"):
        u = db.get(str(uid))
        if not u:
            ensure_user(uid)
            u = db[str(uid)]
        send_safe(uid, f"📊 Real balances:\n{format_balances(u, 'real')}\n\n📊 Demo balances:\n{format_balances(u,'demo')}", reply_markup=main_kb())
        return

    send_safe(uid, "I didn't understand that. Use the menu below.", reply_markup=main_kb())

# ---------------- webhook & polling ----------------
def set_webhook():
    try:
        bot.remove_webhook()
        time.sleep(0.3)
        bot.set_webhook(url=WEBHOOK_URL)
        print("Webhook set to:", WEBHOOK_URL)
        return True
    except Exception as e:
        print("Failed to set webhook:", e)
        return False

def collect_all_pending_withdrawals():
    out = []
    for user_id, u in db.items():
        for w in u.get("pending_withdrawals", []):
            out.append({"user_id": user_id, "entry": w})
    out.sort(key=lambda x: x["entry"].get("time",""))
    return out

def paginate(items, page, page_size=4):
    total = len(items)
    start = page * page_size
    end = start + page_size
    return items[start:end], total

if __name__ == "__main__":
    print(f"Starting {BOT_NAME}...")
    ok = set_webhook()
    if not ok:
        print("Webhook failed, falling back to polling.")
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print("Polling stopped:", e)
    else:
        port = int(os.environ.get("PORT", "5000"))
        app.run(host="0.0.0.0", port=port)
