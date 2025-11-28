# bot.py
import json
import os
import re
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------------------
# Configuration
# ----------------------------
GROUP_ID = -1001234567890  # <-- Replace with your Telegram group ID
ADMINS = [123456789, 987654321]  # <-- Telegram IDs of admins

DATA_FILE = "orders.json"

# ----------------------------
# Data Handling
# ----------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


# ----------------------------
# Status Mapping
# ----------------------------
STATUS_MAP = {
    "out": "Out for delivery",
    "on the way": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

# Regex for formats like "12345 out" or "12345, 12346 out"
ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z ]+)$", re.IGNORECASE)

# ----------------------------
# Group listener (delivery agents)
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow updates from the designated group
    if update.effective_chat.id != GROUP_ID:
        return

    text = update.message.text.strip()
    match = ORDER_PATTERN.match(text)
    if not match:
        return

    orders_raw = match.group("orders")
    status_raw = match.group("status").lower().strip()
    status = STATUS_MAP.get(status_raw, status_raw)

    order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not order_list:
        return

    data = load_data()

    for order_id in order_list:
        data[order_id] = {
            "status": status,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agent": update.message.from_user.full_name,
            "agent_id": update.message.from_user.id,
        }

    save_data(data)

    # Confirmation message
    confirmation_text = f"✅ Updated {len(order_list)} order(s) by {update.message.from_user.full_name}:\n"
    for order_id in order_list:
        confirmation_text += f"• {order_id} → {status} at {data[order_id]['timestamp']}\n"
    await update.message.reply_text(confirmation_text)


# ----------------------------
# Private commands (admins)
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me an order number to get its status.")


async def private_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    data = load_data()

    # Only numeric order lookup
    if not text.isdigit():
        await update.message.reply_text("Send only the order number.")
        return

    if text in data:
        info = data[text]
        await update.message.reply_text(
            f"Order: {text}\nStatus: {info['status']}\nUpdated: {info['timestamp']}\nAgent: {info['agent']}"
        )
    else:
        await update.message.reply_text("No record found for this order.")


# ----------------------------
# Admin-only history command
# ----------------------------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("You are not authorized to view the history.")
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No order updates yet.")
        return

    # Show last 10 updates
    sorted_orders = sorted(data.items(), key=lambda x: x[1]["timestamp"], reverse=True)
    last_10 = sorted_orders[:10]
    text = "📜 Last 10 orders:\n"
    for order_id, info in last_10:
        text += f"{order_id}: {info['status']} (by {info['agent']} at {info['timestamp']})\n"

    await update.message.reply_text(text)


# ----------------------------
# Agent-only /myorders command
# ----------------------------
async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    data = load_data()

    user_orders = {oid: info for oid, info in data.items() if info.get("agent_id") == user_id}
    if not user_orders:
        await update.message.reply_text("You have not updated any orders yet.")
        return

    text = f"📦 Orders updated by you:\n"
    for order_id, info in user_orders.items():
        text += f"{order_id}: {info['status']} at {info['timestamp']}\n"
    await update.message.reply_text(text)


# ----------------------------
# Main entry
# ----------------------------
def main():
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        raise ValueError("Please set the BOT_TOKEN environment variable")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, private_lookup))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("myorders", myorders))

    print("Bot running...")
    app.run_polling()


if __name__ == "__main__":
    main()
