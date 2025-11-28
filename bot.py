# bot.py - Telegram Order Status Bot (GMT+5, Group & Private, Clean Output)
import json
import os
import re
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ----------------------------
# CONFIGURATION
# ----------------------------
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your bot token
GROUP_ID = -1001234567890          # Replace with your group's ID
ADMINS = [123456789, 987654321]    # Replace with Telegram IDs of admins
DATA_FILE = "orders.json"
TIMEZONE_OFFSET = 5  # GMT+5

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

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z ]+)$", re.IGNORECASE)
ORDER_NUMBER_ONLY = re.compile(r"^\d+$")  # For order lookup by number only

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
# Helper Functions
# ----------------------------
def is_admin(user_id):
    return user_id in ADMINS

def gmt5_now():
    return datetime.utcnow() + timedelta(hours=TIMEZONE_OFFSET)

def format_time(dt_str):
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
    return dt.strftime("%H:%M")

# ----------------------------
# Group Listener (Agents Updating or Checking Orders)
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    text = update.message.text.strip()
    data = load_data()

    # 1️⃣ Update orders
    match = ORDER_PATTERN.match(text)
    if match:
        orders_raw = match.group("orders")
        status_raw = match.group("status").lower().strip()
        status = STATUS_MAP.get(status_raw, status_raw)

        order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
        if not order_list:
            return

        for order_id in order_list:
            if order_id not in data:
                data[order_id] = []

            data[order_id].append({
                "status": status,
                "timestamp": gmt5_now().strftime("%Y-%m-%d %H:%M:%S"),
                "agent": update.message.from_user.full_name
            })

        save_data(data)
        await update.message.reply_text(
            f"✅ Updated {len(order_list)} order(s): {', '.join(order_list)}"
        )
        return

    # 2️⃣ Lookup orders by number
    if ORDER_NUMBER_ONLY.match(text):
        order_id = text
        if order_id not in data:
            await update.message.reply_text(f"❌ No record found for order {order_id}.")
            return

        history = data[order_id]
        response = f"📦 Order {order_id} History (last 5 updates):\n"
        for entry in history[-5:]:
            response += f"• {entry['status']} by {entry['agent']} at {format_time(entry['timestamp'])}\n"
        await update.message.reply_text(response)
        return

# ----------------------------
# Private Lookup (Admins)
# ----------------------------
async def private_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Send only the order number.")
        return

    data = load_data()
    order_id = text

    if order_id not in data:
        await update.message.reply_text("❌ No record found for this order.")
        return

    history = data[order_id]
    response = f"📦 Order {order_id} History:\n"
    for entry in history[-10:]:
        response += f"• {entry['status']} by {entry['agent']} at {format_time(entry['timestamp'])}\n"
    await update.message.reply_text(response)

# ----------------------------
# My Orders (Both Private & Group)
# ----------------------------
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.full_name
    data = load_data()
    response = ""
    for order_id, entries in data.items():
        for entry in entries:
            if entry["agent"] == user:
                response += f"📦 {order_id}: {entry['status']} at {format_time(entry['timestamp'])}\n"

    if not response:
        response = "❌ You haven't updated any orders yet."
    await update.message.reply_text(response)

# ----------------------------
# Reset Command (Admin Only)
# ----------------------------
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return

    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    await update.message.reply_text("🗑️ All order history has been cleared.")

# ----------------------------
# Start Command
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Send an order number to get its status, or update orders in the group.\n"
        "Commands:\n/myorders - see your updates\n/history - admin only\n/reset - admin only"
    )

# ----------------------------
# /history Command (Admin Only)
# ----------------------------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Only admins can use this command.")
        return

    data = load_data()
    response = ""
    for order_id, entries in list(data.items())[-10:]:  # last 10 orders
        latest = entries[-1]
        response += f"📦 {order_id}: {latest['status']} by {latest['agent']} at {format_time(latest['timestamp'])}\n"

    if not response:
        response = "No orders yet."
    await update.message.reply_text(response)

# ----------------------------
# Main Entry
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Group messages from agents
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))

    # Private messages
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, private_lookup))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("myorders", my_orders))
    app.add_handler(CommandHandler("reset", reset))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
