import telebot

# === BOT TOKEN ===
TOKEN = "8324820648:AAFnnA65MrpHjymTol3vBRy4iwP8DFyGxx8"
bot = telebot.TeleBot(TOKEN)

# === DEPOSIT ADDRESSES ===
deposit_addresses = {
    "BTC": "bc1qfkf8ntrr74mze6sg6qk3eunhd9lstyzs3xt640",
    "USDT (TRC20)": "TLZuKgWPXczMNSdkxgDxbmjuqu1kbgExTg",
    "ETH": "0x17CfFAbFF7FDCc9a70e6E640C8cF8730a17840b2",
    "TRX": "TLZuKgWPXczMNSdkxgDxbmjuqu1kbgExTg",
    "BNB": "0x17CfFAbFF7FDCc9a70e6E640C8cF8730a17840b2"
}

# === START COMMAND ===
@bot.message_handler(commands=['start'])
def send_welcome(message):
    text = (
        "🤖 *Welcome to AitoCap Clone Bot!*\n\n"
        "You can use the following commands:\n"
        "💰 /deposit - View deposit addresses\n"
        "ℹ️ /help - Get help using the bot"
    )
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# === DEPOSIT COMMAND ===
@bot.message_handler(commands=['deposit'])
def send_deposit_addresses(message):
    text = "💳 *Deposit Addresses:*\n\n"
    for name, addr in deposit_addresses.items():
        text += f"• *{name}:* `{addr}`\n"
    bot.send_message(message.chat.id, text, parse_mode="Markdown")

# === HELP COMMAND ===
@bot.message_handler(commands=['help'])
def send_help(message):
    bot.send_message(message.chat.id, "Send /deposit to get your deposit addresses.")

# === RUN BOT ===
print("🤖 AitoCap clone bot starting...")
bot.infinity_polling()
