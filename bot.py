# bot.py — Full-feature Telegram trading admin+user system
# Features:
# - User registration + mandatory KYC
# - Deposit & withdrawal flows (Telegram) with optional proof upload
# - Admin panel (Flask) with login (env vars), approve/reject, manual balance adjust
# - Auto credit on deposit approval, auto debit on withdrawal approval (with insufficient balance check)
# - Reject requires reason (web form)
# - Multi-admin support and audit log (who performed action)
# - KYC/proof file download
# - Webhook-ready for Render (uses RENDER_EXTERNAL_URL)
# - Data persisted to users.json and transactions.json

import os
import json
import time
import datetime
from functools import wraps
from flask import Flask, request, render_template_string, send_from_directory, redirect, url_for, session
import telebot
from telebot import types

# ----------------- CONFIG -----------------
TOKEN = "8324820648:AAFnnA65MrpHjymTol3vBRy4iwP8DFyGxx8"  # your bot token (already provided)
# Admin username/password will be taken from environment variables (safer).
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "AitoCap@2025")
# Admin Telegram IDs from environment (comma-separated) OR default to the one you gave.
ADMIN_IDS_ENV = os.environ.get("ADMIN_IDS", "8405874261")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_ENV.split(",") if x.strip()]

CURRENCY = os.environ.get("CURRENCY", "USD")  # default currency display
DEPOSIT_METHODS = ["Bank Transfer", "Crypto (USDT)", "PayPal"]

# Storage paths
USERS_FILE = "users.json"
TX_FILE = "transactions.json"
UPLOAD_DIR = "kyc_uploads"

# Ensure directories and files exist
os.makedirs(UPLOAD_DIR, exist_ok=True)
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, "w") as f:
        json.dump({}, f)
if not os.path.exists(TX_FILE):
    with open(TX_FILE, "w") as f:
        json.dump([], f)

# ----------------- FLASK & TELEGRAM -----------------
app = Flask(__name__)
# session secret — for production set a stable secret via env var
app.secret_key = os.environ.get("FLASK_SECRET") or os.urandom(24)

bot = telebot.TeleBot(TOKEN)

# ----------------- UTIL HELPERS -----------------
def now_str():
    return datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def load_users():
    with open(USERS_FILE, "r") as f:
        return json.load(f)

def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def load_txs():
    with open(TX_FILE, "r") as f:
        return json.load(f)

def save_txs(txs):
    with open(TX_FILE, "w") as f:
        json.dump(txs, f, indent=2)

def append_audit_entry(tx, admin_name, action, reason=""):
    entry = {"admin": admin_name, "action": action, "reason": reason, "timestamp": now_str()}
    tx.setdefault("audit", []).append(entry)

def send_admin_notify(text):
    for aid in ADMIN_IDS:
        try:
            bot.send_message(aid, text)
        except Exception as e:
            print("Admin notify failed:", e)

def save_file_from_message(message, prefix):
    """
    Saves photo or document to UPLOAD_DIR.
    Returns saved filename (basename) or None.
    """
    try:
        if message.content_type == "photo":
            file_id = message.photo[-1].file_id
        elif message.content_type == "document":
            file_id = message.document.file_id
        else:
            return None
        finfo = bot.get_file(file_id)
        data = bot.download_file(finfo.file_path)
        base = finfo.file_path.split("/")[-1]
        filename = f"{prefix}_{int(time.time())}_{base}"
        path = os.path.join(UPLOAD_DIR, filename)
        with open(path, "wb") as fp:
            fp.write(data)
        return filename
    except Exception as e:
        print("save_file_from_message error:", e)
        return None

def add_transaction(user_id, tx_type, amount, method, proof_file=""):
    txs = load_txs()
    tx_id = (txs[-1]["id"] + 1) if txs else 1
    tx = {
        "id": tx_id,
        "user_id": str(user_id),
        "type": tx_type,
        "amount": float(amount),
        "method": method or "",
        "proof_file": proof_file or "",
        "status": "Pending",
        "timestamp": now_str(),
        "admin_comment": "",
        "audit": []
    }
    txs.append(tx)
    save_txs(txs)
    return tx

# ----------------- TELEGRAM HANDLERS: Registration & KYC -----------------
@bot.message_handler(commands=["start"])
def cmd_start(message):
    uid = str(message.from_user.id)
    users = load_users()
    if uid not in users:
        users[uid] = {
            "name": None,
            "email": None,
            "kyc_uploaded": False,
            "kyc_file": "",
            "balance": 0.0
        }
        save_users(users)
        bot.send_message(message.chat.id, "Welcome! Please enter your full name:")
        bot.register_next_step_handler(message, handle_name)
    else:
        bot.send_message(message.chat.id, "Welcome back! If you haven't uploaded KYC, please upload now (photo or PDF).")

def handle_name(message):
    uid = str(message.from_user.id)
    name = message.text.strip()
    users = load_users()
    users[uid]["name"] = name
    save_users(users)
    bot.send_message(message.chat.id, "Thanks. Please enter your email address:")
    bot.register_next_step_handler(message, handle_email)

def handle_email(message):
    uid = str(message.from_user.id)
    email = message.text.strip()
    users = load_users()
    users[uid]["email"] = email
    save_users(users)
    bot.send_message(message.chat.id, f"Registration saved.\nNow upload your KYC document (photo or PDF). KYC is mandatory to use the platform.")
    # user should upload file next

@bot.message_handler(content_types=["photo", "document"])
def handle_file(message):
    uid = str(message.from_user.id)
    users = load_users()
    if uid not in users:
        bot.send_message(message.chat.id, "Please send /start to register first.")
        return
    filename = save_file_from_message(message, prefix=uid)
    if not filename:
        bot.send_message(message.chat.id, "Could not process file — please send a photo or PDF.")
        return
    # If user has not uploaded KYC yet, mark as KYC; otherwise treat as generic proof
    if not users[uid].get("kyc_uploaded", False):
        users[uid]["kyc_uploaded"] = True
        users[uid]["kyc_file"] = filename
        save_users(users)
        bot.send_message(message.chat.id, "✅ KYC received. Awaiting admin review.")
        send_admin_notify(f"New KYC uploaded by {uid}. Visit /admin to review.")
    else:
        bot.send_message(message.chat.id, "File saved. If this is proof for a transaction, attach it when prompted in /deposit or /withdraw flow.")

# ----------------- TELEGRAM: Deposit & Withdraw flows -----------------
@bot.message_handler(commands=["deposit"])
def cmd_deposit(message):
    uid = str(message.from_user.id)
    users = load_users()
    if uid not in users:
        bot.send_message(message.chat.id, "Please /start to register first.")
        return
    if not users[uid].get("kyc_uploaded", False):
        bot.send_message(message.chat.id, "KYC required before deposits. Upload KYC first.")
        return
    # show deposit methods
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    for m in DEPOSIT_METHODS:
        markup.add(m)
    markup.add("Cancel")
    bot.send_message(message.chat.id, f"Choose deposit method ({CURRENCY}):", reply_markup=markup)
    bot.register_next_step_handler(message, deposit_choose_method)

def deposit_choose_method(message):
    uid = str(message.from_user.id)
    method = message.text.strip()
    if method == "Cancel":
        bot.send_message(message.chat.id, "Deposit cancelled.", reply_markup=types.ReplyKeyboardRemove())
        return
    if method not in DEPOSIT_METHODS:
        bot.send_message(message.chat.id, "Invalid method. Use /deposit to retry.")
        return
    bot.send_message(message.chat.id, "Enter deposit amount (numbers only):", reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(message, lambda m: deposit_amount_step(m, method))

def deposit_amount_step(message, method):
    uid = str(message.from_user.id)
    amt_text = message.text.strip()
    if not amt_text.replace(".", "", 1).isdigit():
        bot.send_message(message.chat.id, "Invalid amount. Try /deposit again.")
        return
    amount = float(amt_text)
    # ask for optional proof
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Upload proof now", "Skip proof")
    bot.send_message(message.chat.id, "Upload proof (screenshot/tx hash) now or Skip proof.", reply_markup=markup)
    bot.register_next_step_handler(message, lambda m: deposit_proof_step(m, amount, method))

def deposit_proof_step(message, amount, method):
    uid = str(message.from_user.id)
    if message.text == "Skip proof":
        tx = add_transaction(uid, "Deposit", amount, method, proof_file="")
        bot.send_message(message.chat.id, f"✅ Deposit request recorded (id {tx['id']}) — awaiting admin approval.")
        send_admin_notify(f"New Deposit #{tx['id']} from {uid} — ${amount} {CURRENCY}. Admin: /admin")
        return
    # if file sent:
    if message.content_type in ["photo", "document"]:
        filename = save_file_from_message(message, prefix=f"{uid}_proof")
        tx = add_transaction(uid, "Deposit", amount, method, proof_file=filename)
        bot.send_message(message.chat.id, f"✅ Deposit request recorded (id {tx['id']}) with proof — awaiting admin approval.")
        send_admin_notify(f"New Deposit #{tx['id']} from {uid} — ${amount} {CURRENCY} (proof attached). Admin: /admin")
        return
    # otherwise prompt
    bot.send_message(message.chat.id, "Please upload a photo/pdf as proof or send 'Skip proof'.")
    bot.register_next_step_handler(message, lambda m: deposit_proof_step(m, amount, method))

@bot.message_handler(commands=["withdraw"])
def cmd_withdraw(message):
    uid = str(message.from_user.id)
    users = load_users()
    if uid not in users:
        bot.send_message(message.chat.id, "Please /start to register first.")
        return
    if not users[uid].get("kyc_uploaded", False):
        bot.send_message(message.chat.id, "KYC required before withdrawals. Upload KYC first.")
        return
    bot.send_message(message.chat.id, "Enter withdrawal amount (numbers only):")
    bot.register_next_step_handler(message, withdraw_amount_step)

def withdraw_amount_step(message):
    uid = str(message.from_user.id)
    amt_text = message.text.strip()
    if not amt_text.replace(".", "", 1).isdigit():
        bot.send_message(message.chat.id, "Invalid amount. Try /withdraw again.")
        return
    amount = float(amt_text)
    bot.send_message(message.chat.id, "Enter destination (wallet address or bank details):")
    bot.register_next_step_handler(message, lambda m: withdraw_dest_step(m, amount))

def withdraw_dest_step(message, amount):
    uid = str(message.from_user.id)
    dest = message.text.strip()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("Upload proof now", "Skip proof")
    bot.send_message(message.chat.id, "Upload proof now (optional) or Skip proof.", reply_markup=markup)
    bot.register_next_step_handler(message, lambda m: withdraw_proof_step(m, amount, dest))

def withdraw_proof_step(message, amount, dest):
    uid = str(message.from_user.id)
    if message.text == "Skip proof":
        # simple 2FA: send code in chat (demo). For production, use more robust OTP.
        otp = str(int(time.time()) % 1000000)
        bot.send_message(message.chat.id, f"Your 2FA code: {otp}\nEnter the code to confirm withdrawal.")
        bot.register_next_step_handler(message, lambda m: finalize_withdraw_otp(m, amount, dest, otp, proof_file=""))
        return
    if message.content_type in ["photo", "document"]:
        filename = save_file_from_message(message, prefix=f"{uid}_proof")
        otp = str(int(time.time()) % 1000000)
        bot.send_message(message.chat.id, f"Your 2FA code: {otp}\nEnter the code to confirm withdrawal.")
        bot.register_next_step_handler(message, lambda m: finalize_withdraw_otp(m, amount, dest, otp, proof_file=filename))
        return
    bot.send_message(message.chat.id, "Please upload file or 'Skip proof'.")
    bot.register_next_step_handler(message, lambda m: withdraw_proof_step(m, amount, dest))

def finalize_withdraw_otp(message, amount, dest, otp, proof_file=""):
    uid = str(message.from_user.id)
    code = message.text.strip()
    if code != otp:
        bot.send_message(message.chat.id, "Invalid 2FA code. Withdrawal cancelled.")
        return
    tx = add_transaction(uid, "Withdrawal", amount, dest, proof_file=proof_file)
    bot.send_message(message.chat.id, f"✅ Withdrawal request recorded (id {tx['id']}) — awaiting admin approval.")
    send_admin_notify(f"New Withdrawal #{tx['id']} from {uid} — ${amount} {CURRENCY}. Admin: /admin")

# ----------------- FLASK: Admin auth utilities -----------------
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped

# ----------------- FLASK ROUTES: Admin panel -----------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "")
        pwd = request.form.get("password", "")
        if user == os.environ.get("ADMIN_USERNAME", ADMIN_USERNAME) and pwd == os.environ.get("ADMIN_PASSWORD", ADMIN_PASSWORD):
            session["logged_in"] = True
            session["admin_user"] = user
            return redirect(url_for("admin_panel"))
        else:
            return render_template_string("<h3>Invalid credentials</h3><a href='/login'>Back</a>")
    return render_template_string("""
        <h2>Admin Login</h2>
        <form method="post">
            <input name="username" placeholder="username" required><br><br>
            <input name="password" placeholder="password" type="password" required><br><br>
            <input type="submit" value="Login">
        </form>
    """)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/admin")
@login_required
def admin_panel():
    users = load_users()
    txs = load_txs()
    txs_sorted = sorted(txs, key=lambda x: x["id"], reverse=True)
    # simple admin HTML with actions
    html = """
    <html><head><title>Admin Panel</title>
    <style>body{font-family:Arial;padding:16px} table{border-collapse:collapse;width:100%} th,td{padding:8px;border:1px solid #ddd} a{color:#06c}</style>
    </head><body>
    <h1>AitoCap Admin Panel</h1>
    <p>Logged in as: {{admin_user}} | <a href="/logout">Logout</a></p>

    <h2>Pending Transactions</h2>
    <table>
    <tr><th>ID</th><th>User</th><th>Type</th><th>Amount</th><th>Method/Dest</th><th>Proof</th><th>Time</th><th>Status</th><th>Actions</th></tr>
    {% for tx in txs %}
      <tr>
        <td>{{tx['id']}}</td><td>{{tx['user_id']}}</td><td>{{tx['type']}}</td>
        <td>${{ "%.2f"|format(tx['amount']) }} {{currency}}</td>
        <td>{{tx['method']}}</td>
        <td>{% if tx['proof_file'] %}<a href="/kyc/{{tx['proof_file']}}">Download</a>{% else %}-{% endif %}</td>
        <td>{{tx['timestamp']}}</td><td>{{tx['status']}}</td>
        <td>
          {% if tx['status']=="Pending" %}
            <a href="/admin/approve/{{tx['id']}}">Approve</a> |
            <a href="/admin/reject_form/{{tx['id']}}">Reject</a>
          {% else %}
            -
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </table>

    <h2>Registered Users</h2>
    <table>
      <tr><th>User ID</th><th>Name</th><th>Email</th><th>KYC</th><th>KYC File</th><th>Balance</th><th>Adjust</th></tr>
      {% for uid,info in users.items() %}
      <tr>
        <td>{{uid}}</td>
        <td>{{info.get('name') or '-'}}</td>
        <td>{{info.get('email') or '-'}}</td>
        <td>{% if info.get('kyc_uploaded') %}✅{% else %}❌{% endif %}</td>
        <td>{% if info.get('kyc_file') %}<a href="/kyc/{{info.get('kyc_file')}}">Download</a>{% else %}-{% endif %}</td>
        <td>${{ "%.2f"|format(info.get('balance',0.0)) }} {{currency}}</td>
        <td><a href="/admin/adjust_balance/{{uid}}">Adjust</a></td>
      </tr>
      {% endfor %}
    </table>

    <h2>Recent Audit Example</h2>
    <pre>{{ txs[0] if txs else "No transactions yet." }}</pre>

    </body></html>
    """
    return render_template_string(html, txs=txs_sorted, users=users, admin_user=session.get("admin_user"), currency=CURRENCY)

# Approve endpoint: credits/debits and records admin user
@app.route("/admin/approve/<int:tx_id>")
@login_required
def admin_approve(tx_id):
    admin_user = session.get("admin_user", "web")
    txs = load_txs()
    users = load_users()
    for tx in txs:
        if tx["id"] == tx_id and tx["status"] == "Pending":
            uid = tx["user_id"]
            amount = float(tx["amount"])
            # ensure user record exists
            if uid not in users:
                users[uid] = {"name": None, "email": None, "kyc_uploaded": False, "kyc_file": "", "balance": 0.0}
            if tx["type"] == "Deposit":
                users[uid]["balance"] = float(users[uid].get("balance", 0.0)) + amount
                tx["status"] = "Approved"
                tx["admin_comment"] = f"Approved by {admin_user} at {now_str()}"
                append_audit_entry(tx, admin_user, "Approve Deposit", reason=f"Credited {amount} {CURRENCY}")
            elif tx["type"] == "Withdrawal":
                if users[uid].get("balance",0.0) >= amount:
                    users[uid]["balance"] = float(users[uid].get("balance", 0.0)) - amount
                    tx["status"] = "Approved"
                    tx["admin_comment"] = f"Approved by {admin_user} at {now_str()}"
                    append_audit_entry(tx, admin_user, "Approve Withdrawal", reason=f"Debited {amount} {CURRENCY}")
                else:
                    # insufficient funds -> reject automatically
                    tx["status"] = "Rejected"
                    reason = "Insufficient balance to approve withdrawal"
                    tx["admin_comment"] = f"Auto-Rejected by {admin_user} at {now_str()}: {reason}"
                    append_audit_entry(tx, admin_user, "Auto-Reject Withdrawal", reason=reason)
                    save_txs(txs); save_users(users)
                    try:
                        bot.send_message(int(uid), f"❌ Withdrawal #{tx_id} cannot be approved due to insufficient balance.")
                    except:
                        pass
                    return redirect(url_for("admin_panel"))
            else:
                tx["status"] = "Approved"
                append_audit_entry(tx, admin_user, "Approve", reason="")
            save_txs(txs)
            save_users(users)
            # notify user
            try:
                bot.send_message(int(uid), f"✅ Your {tx['type']} request (id: {tx_id}) has been APPROVED. New balance: ${users[uid]['balance']:.2f} {CURRENCY}")
            except:
                pass
            break
    return redirect(url_for("admin_panel"))

# Reject form & processing
@app.route("/admin/reject_form/<int:tx_id>", methods=["GET", "POST"])
@login_required
def admin_reject_form(tx_id):
    admin_user = session.get("admin_user", "web")
    txs = load_txs()
    tx = next((t for t in txs if t["id"] == tx_id), None)
    if not tx:
        return "Transaction not found", 404
    if request.method == "POST":
        reason = request.form.get("reason", "").strip()
        if not reason:
            return "<h3>Reason required</h3><a href='/admin'>Back</a>"
        tx["status"] = "Rejected"
        tx["admin_comment"] = f"Rejected by {admin_user} at {now_str()}: {reason}"
        append_audit_entry(tx, admin_user, "Reject", reason=reason)
        save_txs(txs)
        # notify user
        try:
            bot.send_message(int(tx["user_id"]), f"❌ Your {tx['type']} request (id: {tx_id}) was rejected. Reason: {reason}")
        except:
            pass
        return redirect(url_for("admin_panel"))
    # GET: show simple form
    return render_template_string("""
      <h3>Reject Transaction #{{tx_id}}</h3>
      <form method="post">
        <label>Reason (required):</label><br>
        <textarea name="reason" rows="4" cols="60" required></textarea><br><br>
        <input type="submit" value="Submit rejection"> &nbsp; <a href="/admin">Cancel</a>
      </form>
    """, tx_id=tx_id)

# Manual balance adjust
@app.route("/admin/adjust_balance/<user_id>", methods=["GET", "POST"])
@login_required
def admin_adjust_balance(user_id):
    admin_user = session.get("admin_user", "web")
    users = load_users()
    if user_id not in users:
        return "User not found", 404
    if request.method == "POST":
        try:
            amt = float(request.form.get("amount"))
        except:
            return "<h3>Invalid amount</h3><a href='/admin'>Back</a>"
        action = request.form.get("action")
        reason = request.form.get("reason","").strip()
        if action not in ["credit","debit"]:
            return "<h3>Invalid action</h3><a href='/admin'>Back</a>"
        if action == "credit":
            users[user_id]["balance"] = float(users[user_id].get("balance",0.0)) + amt
            audit_reason = f"Manual credit {amt} by {admin_user}. {reason}"
        else:
            users[user_id]["balance"] = float(users[user_id].get("balance",0.0)) - amt
            audit_reason = f"Manual debit {amt} by {admin_user}. {reason}"
        save_users(users)
        # create audit transaction for traceability
        txs = load_txs()
        tx_id = (txs[-1]["id"]+1) if txs else 1
        tx = {
            "id": tx_id,
            "user_id": user_id,
            "type": "ManualAdjust",
            "amount": amt,
            "method": "Admin",
            "proof_file": "",
            "status": "Completed",
            "timestamp": now_str(),
            "admin_comment": audit_reason,
            "audit": [{"admin": admin_user, "action": "ManualAdjust", "reason": audit_reason, "timestamp": now_str()}]
        }
        txs.append(tx)
        save_txs(txs)
        return redirect(url_for("admin_panel"))
    # GET: show form
    return render_template_string("""
      <h3>Adjust Balance for user {{uid}}</h3>
      <form method="post">
        <select name="action">
          <option value="credit">Credit</option>
          <option value="debit">Debit</option>
        </select><br><br>
        <input name="amount" placeholder="Amount (numbers only)"><br><br>
        <textarea name="reason" placeholder="Reason (optional)"></textarea><br><br>
        <input type="submit" value="Submit">
      </form>
      <p><a href="/admin">Back</a></p>
    """, uid=user_id)

# Serve stored files (KYC or proofs) — admin-only
@app.route("/kyc/<path:filename>")
@login_required
def serve_file(filename):
    return send_from_directory(UPLOAD_DIR, filename, as_attachment=True)

# Home / webhook setup
@app.route(f"/{TOKEN}", methods=["POST"])
def telegram_webhook():
    json_str = request.get_data(as_text=True)
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return "OK", 200

@app.route("/")
def home():
    return "AitoCap bot is running."

# ----------------- STARTUP: set webhook if on Render and run app -----------------
if __name__ == "__main__":
    # If Render exposes RENDER_EXTERNAL_URL (it does), use it to set webhook
    external = os.environ.get("RENDER_EXTERNAL_URL")
    if external:
        try:
            bot.remove_webhook()
        except:
            pass
        try:
            bot.set_webhook(url=f"https://{external}/{TOKEN}")
            print("Webhook set:", f"https://{external}/{TOKEN}")
        except Exception as e:
            print("Error setting webhook:", e)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
