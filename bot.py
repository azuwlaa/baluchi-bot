# bot.py
import os
import json
import re
from datetime import datetime
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ----------------------------
# CONFIGURATION
# ----------------------------
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your bot token
GROUP_ID = -1001234567890          # Replace with your group chat ID
ADMINS = [123456789, 987654321]   # Replace with Telegram IDs of admins

DATA_FILE = "orders.json"

# ----------------------------
# DATA HANDLING
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
# STATUS MAPPING
# ----------------------------
STATUS_MAP = {
    "out": "Out for delivery",
    "on the way": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z ]+)$", re.IGNORECASE)

# ----------------------------
# DELIVERY UPDATE HANDLER
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != GROUP_ID:
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
    agent_name = update.message.from_user.full_name

    for order_id in order_list:
        if order_id not in data:
            data[order_id] = []
        data[order_id].append({
            "status": status,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agent": agent_name,
        })

    save_data(data)
    await update.message.reply_text(f"✅ Updated {len(order_list)} order(s): {', '.join(order_list)}")

# ----------------------------
# ADMIN COMMANDS
# ----------------------------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ You are not authorized to use this command.")
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No orders yet.")
        return

    # Show last 10 orders updates
    all_orders = []
    for order_id, updates in data.items():
        for upd in updates:
            all_orders.append((order_id, upd))
    all_orders.sort(key=lambda x: x[1]["timestamp"], reverse=True)
    last_10 = all_orders[:10]

    msg_lines = []
    for order_id, upd in last_10:
        msg_lines.append(f"{order_id} - {upd['status']} by {upd['agent']} at {upd['timestamp']}")

    await update.message.reply_text("\n".join(msg_lines))

# ----------------------------
# DELIVERY AGENT COMMANDS
# ----------------------------
async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent_name = update.message.from_user.full_name
    data = load_data()

    my_updates = []
    for order_id, updates in data.items():
        for upd in updates:
            if upd['agent'] == agent_name:
                my_updates.append((order_id, upd))

    if not my_updates:
        await update.message.reply_text("You have not updated any orders yet.")
        return

    my_updates.sort(key=lambda x: x[1]["timestamp"], reverse=True)
    msg_lines = []
    for order_id, upd in my_updates[-10:]:
        msg_lines.append(f"{order_id} - {upd['status']} at {upd['timestamp']}")

    await update.message.reply_text("\n".join(msg_lines))

# ----------------------------
# PRIVATE LOOKUP
# ----------------------------
async def private_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Send only the order number.")
        return

    data = load_data()
    if text in data:
        info = data[text][-1]  # last update
        await update.message.reply_text(
            f"Order: {text}\nStatus: {info['status']}\nUpdated: {info['timestamp']}\nBy: {info['agent']}"
        )
    else:
        await update.message.reply_text("No record found for this order.")

# ----------------------------
# START COMMAND
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me an order number to get its status.")

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Delivery updates in group
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))

    # Admin & agent commands in group
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("myorders", myorders))

    # Private messages
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, private_lookup))
    app.add_handler(CommandHandler("start", start))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
