# Telegram Order Status Bot - Final Version with Group & Topic Support

import json
import os
import re
from datetime import datetime, timedelta, timezone
from telegram import Update, MessageEntity
from telegram.constants import ChatAction
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
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # <-- replace with your bot token
GROUP_ID = -1001234567890           # <-- replace with your Telegram group ID
ADMINS = [123456789, 987654321]    # <-- list of admin user IDs
DATA_FILE = "orders.json"

# ----------------------------
# Status Mapping
# ----------------------------
STATUS_MAP = {
    "out": "Out for delivery",
    "otw": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z ]+)$", re.IGNORECASE)

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

def get_gmt5_time():
    tz = timezone(timedelta(hours=5))
    return datetime.now(tz)

def format_time(dt_str):
    dt = datetime.fromisoformat(dt_str)
    return dt.strftime('%H:%M:%S')

# ----------------------------
# Order Update Handler (Group)
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    text = update.message.text.strip()

    # Check for order number only lookup
    if text.isdigit():
        data = load_data()
        order = text
        if order in data:
            info = data[order]
            await update.message.reply_text(
                f"📦 Order: {order}\n"
                f"Status: {info['status']}\n"
                f"Updated by: {info['agent_name']}\n"
                f"🕒 {format_time(info['timestamp'])}"
            )
        else:
            await update.message.reply_text("No record found for this order.")
        return

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
    agent_name = update.message.from_user.first_name

    for order_id in order_list:
        data[order_id] = {
            "status": status,
            "timestamp": get_gmt5_time().isoformat(),
            "agent_name": agent_name
        }

    save_data(data)

    # Confirmation with thumbs up
    await update.message.react('👍')

    # Optional text confirmation, deleted after 5 seconds
    msg = await update.message.reply_text(f"✅ Updated {len(order_list)} order(s) by {agent_name}")
    await context.application.create_task(delete_after_delay(msg, 5))

async def delete_after_delay(msg, delay_sec):
    await context.application.create_task(asyncio.sleep(delay_sec))
    try:
        await msg.delete()
    except:
        pass

# ----------------------------
# Private or Group Commands
# ----------------------------
async def lookup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("Send only the order number.")
        return

    data = load_data()
    order = text
    if order in data:
        info = data[order]
        await update.message.reply_text(
            f"📦 Order: {order}\n"
            f"Status: {info['status']}\n"
            f"Updated by: {info['agent_name']}\n"
            f"🕒 {format_time(info['timestamp'])}"
        )
    else:
        await update.message.reply_text("No record found for this order.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send an order number to get its status or update in the group.")

# ----------------------------
# Admin Commands
# ----------------------------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("🚫 Only admins can use this command.")
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No order history yet.")
        return

    lines = []
    for order_id, info in list(data.items())[-10:]:
        lines.append(f"📦 {order_id} - {info['status']} - {info['agent_name']} - 🕒 {format_time(info['timestamp'])}")
    await update.message.reply_text("\n".join(lines))

async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    agent_name = update.message.from_user.first_name

    data = load_data()
    lines = []
    for order_id, info in data.items():
        if info['agent_name'] == agent_name:
            lines.append(f"📦 {order_id} - {info['status']} - 🕒 {format_time(info['timestamp'])}")

    if not lines:
        await update.message.reply_text("You have no order updates yet.")
    else:
        await update.message.reply_text(f"📝 Orders updated by {agent_name}:\n" + "\n".join(lines))

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("🚫 Only admins can reset history.")
        return
    save_data({})
    await update.message.reply_text("✅ Order history has been reset.")

# ----------------------------
# Stats Command
# ----------------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("🚫 Only admins can view stats.")
        return

    data = load_data()
    tz = timezone(timedelta(hours=5))
    today = datetime.now(tz).date()

    total_done = 0
    agent_counter = {}
    for order_id, info in data.items():
        order_time = datetime.fromisoformat(info['timestamp']).astimezone(tz)
        if order_time.date() == today:
            if info['status'] == 'Order delivery completed':
                total_done +=1
            agent = info['agent_name']
            agent_counter[agent] = agent_counter.get(agent,0)+1

    lines = [f"📊 Total orders delivered today: {total_done}"]
    for agent, count in agent_counter.items():
        lines.append(f"👤 {agent} - {count} order(s)")

    await update.message.reply_text("\n".join(lines))

# ----------------------------
# Main Entry
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lookup))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("stats", stats))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    import asyncio
    main()
