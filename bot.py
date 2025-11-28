import json
import os
import re
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update, MessageEntity, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# -----------------------------
# Configuration
# -----------------------------
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your bot token
GROUP_ID = -1001234567890  # Replace with your group ID
ADMINS = [12345678, 98765432]  # List of admin Telegram user IDs
DATA_FILE = "orders.json"

# -----------------------------
# Status mapping
# -----------------------------
STATUS_MAP = {
    "out": "Out for delivery",
    "otw": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

# Regex pattern for order updates
ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9, ]+)\s+(?P<status>[a-zA-Z ]+)$", re.IGNORECASE)

# -----------------------------
# Data handling
# -----------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# -----------------------------
# Time helper
# -----------------------------
GMT5 = timezone(timedelta(hours=5))
def current_time():
    return datetime.now(GMT5).strftime("%H:%M:%S")

# -----------------------------
# Group message listener
# -----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != GROUP_ID:
        return  # ignore messages from other groups

    text = update.message.text.strip()
    match = ORDER_PATTERN.match(text)
    if not match:
        # If a single order number, allow lookup
        if text.isdigit():
            await send_order_status(update, context, text)
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
            "timestamp": current_time(),
            "agent": update.message.from_user.full_name,
        }

    save_data(data)

    # Confirmation message with auto-delete
    confirmation = await update.message.reply_text(
        f"✅ Updated {len(order_list)} order(s): {', '.join(order_list)}\nby {update.message.from_user.full_name}"
    )
    await asyncio.sleep(5)
    await confirmation.delete()

# -----------------------------
# Send order status
# -----------------------------
async def send_order_status(update, context, order_id):
    data = load_data()
    if order_id in data:
        info = data[order_id]
        await update.message.reply_text(
            f"📦 Order: {order_id}\n"
            f"Status: {info['status']}\n"
            f"Time: {info['timestamp']}\n"
            f"Updated by: {info['agent']}"
        )
    else:
        await update.message.reply_text("No record found for this order.")

# -----------------------------
# /start command
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send an order update in the group in format:\n"
        "`12345 out` or `12345,12346 otw`\n\n"
        "Admins can use /history, /stats, /reset\n"
        "Agents can use /myorders"
    )

# -----------------------------
# /myorders command
# -----------------------------
async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.full_name
    data = load_data()
    orders = [
        f"📦 {oid}: {info['status']} ⏱ {info['timestamp']}"
        for oid, info in data.items() if info.get("agent") == user
    ]
    if not orders:
        msg = f"{user}, you have no orders updated yet."
    else:
        msg = f"📝 Orders updated by {user}:\n" + "\n".join(orders)
    await update.message.reply_text(msg)

# -----------------------------
# /history command (admin only)
# -----------------------------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("⛔ Admins only.")
        return
    data = load_data()
    if not data:
        await update.message.reply_text("No order history yet.")
        return
    lines = [
        f"📦 {oid}: {info['status']} ⏱ {info['timestamp']} 👤 {info['agent']}"
        for oid, info in data.items()
    ]
    msg = "🕘 Order History:\n" + "\n".join(lines)
    await update.message.reply_text(msg)

# -----------------------------
# /stats command (admin only)
# -----------------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("⛔ Admins only.")
        return
    data = load_data()
    agent_count = {}
    for info in data.values():
        agent = info.get("agent", "Unknown")
        agent_count[agent] = agent_count.get(agent, 0) + 1
    lines = [f"👤 {agent}: {count} orders" for agent, count in agent_count.items()]
    msg = "📊 Today's Order Stats:\n" + "\n".join(lines)
    await update.message.reply_text(msg)

# -----------------------------
# /reset command (admin only)
# -----------------------------
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("⛔ Admins only.")
        return
    save_data({})
    await update.message.reply_text("✅ Order history cleared.")

# -----------------------------
# Main
# -----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", my_orders))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_listener))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
