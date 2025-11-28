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

DATA_FILE = "orders.json"

# ----------------------------
# Configuration
# ----------------------------
ALLOWED_GROUP_ID = -1001234567890  # Replace with your group ID
ADMINS = [12345678, 87654321]      # Telegram IDs of admins

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

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z ]+)$", re.IGNORECASE)

# ----------------------------
# Group listener (delivery agents)
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Only allow from specific group
    if update.effective_chat.id != ALLOWED_GROUP_ID:
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
        if order_id not in data:
            data[order_id] = []
        data[order_id].append({
            "status": status,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "agent_id": update.message.from_user.id,
            "agent_name": update.message.from_user.full_name
        })

    save_data(data)

    await update.message.reply_text(
        f"Updated {len(order_list)} order(s): {', '.join(order_list)}"
    )

# ----------------------------
# Private lookup (admins or agents)
# ----------------------------
async def private_lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Send only the order number.")
        return

    data = load_data()
    order_history = data.get(text)
    if not order_history:
        await update.message.reply_text("No record found for this order.")
        return

    # Show only last update for normal agents
    if update.message.from_user.id not in ADMINS:
        last_update = order_history[-1]
        await update.message.reply_text(
            f"Order: {text}\nStatus: {last_update['status']}\nUpdated by: {last_update['agent_name']}\nTimestamp: {last_update['timestamp']}"
        )
    else:
        # Admins see full history
        lines = [f"{h['timestamp']} | {h['agent_name']} | {h['status']}" for h in order_history]
        await update.message.reply_text(f"Order: {text}\n" + "\n".join(lines))

# ----------------------------
# Admin command: history (paginated)
# ----------------------------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("You are not authorized to use this command.")
        return

    data = load_data()
    orders = list(data.items())
    if not orders:
        await update.message.reply_text("No orders in history.")
        return

    # Pagination
    page = int(context.args[0]) if context.args else 1
    per_page = 10
    total_pages = (len(orders) + per_page - 1) // per_page
    page = max(1, min(page, total_pages))

    start = (page - 1) * per_page
    end = start + per_page
    message_lines = []
    for order_id, updates in orders[start:end]:
        last_update = updates[-1]
        message_lines.append(
            f"{order_id}: {last_update['status']} by {last_update['agent_name']} at {last_update['timestamp']}"
        )

    buttons = []
    if page > 1:
        buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"hist_{page-1}"))
    if page < total_pages:
        buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"hist_{page+1}"))
    markup = InlineKeyboardMarkup([buttons]) if buttons else None

    await update.message.reply_text(
        f"Orders history (Page {page}/{total_pages}):\n" + "\n".join(message_lines),
        reply_markup=markup
    )

# ----------------------------
# Agent command: myorders
# ----------------------------
async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    data = load_data()
    user_orders = []

    for order_id, updates in data.items():
        for h in updates:
            if h["agent_id"] == user_id:
                user_orders.append(f"{order_id}: {h['status']} at {h['timestamp']}")

    if not user_orders:
        await update.message.reply_text("You have not updated any orders yet.")
        return

    await update.message.reply_text("\n".join(user_orders))

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

    # Gr
