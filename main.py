# Telegram Order Status Bot (Clean Full Version)
# Supports multiple orders + mapped statuses

import json
import os
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

# Regex for formats like:
# "12345 out"
# "12345, 12346 out"
ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z ]+)$", re.IGNORECASE)

# ----------------------------
# Group listener (delivery agents)
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    match = ORDER_PATTERN.match(text)

    if not match:
        return

    orders_raw = match.group("orders")
    status_raw = match.group("status").lower().strip()
    status = STATUS_MAP.get(status_raw, status_raw)

    # Split multiple orders
    order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not order_list:
        return

    data = load_data()

    for order_id in order_list:
        data[order_id] = {
            "status": status,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    save_data(data)

    await update.message.reply_text(
        f"Updated {len(order_list)} order(s): {', '.join(order_list)}"
    )

# ----------------------------
# Private lookup (admins)
# ----------------------------
async def private_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    if not text.isdigit():
        await update.message.reply_text("Send only the order number.")
        return

    data = load_data()

    if text in data:
        info = data[text]
        await update.message.reply_text(
            f"Order: {text}\nStatus: {info['status']}\nUpdated: {info['timestamp']}"
        )
    else:
        await update.message.reply_text("No record found for this order.")

# ----------------------------
# Start command
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me an order number to get its status.")

# ----------------------------
# Main entry
# ----------------------------
def main():
    BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, private_lookup))
    app.add_handler(CommandHandler("start", start))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
