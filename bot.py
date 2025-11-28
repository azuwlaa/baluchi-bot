import json
import os
import re
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    CallbackQueryHandler,
    filters,
)

# ----------------------------
# CONFIG
# ----------------------------
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your bot token
GROUP_ID = -1001234567890           # Replace with your group ID
ADMINS = [123456789, 987654321]    # Telegram IDs of admins
DATA_FILE = "orders.json"
TIMEZONE = timezone(timedelta(hours=5))  # GMT+5

# Status map
STATUS_MAP = {
    "out": "Out for delivery",
    "otw": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z ]+)$", re.IGNORECASE)

# ----------------------------
# Data handling
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
# Helpers
# ----------------------------
def format_time(ts_str):
    dt = datetime.fromisoformat(ts_str).astimezone(TIMEZONE)
    return dt.strftime("%H:%M:%S")

# ----------------------------
# Group listener
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    text = update.message.text.strip()
    match = ORDER_PATTERN.match(text)
    if not match:
        # Also allow checking order status in group by sending order number
        if text.isdigit():
            data = load_data()
            if text in data:
                info = data[text]
                msg = (
                    f"📦 Order: {text}\n"
                    f"Status: {info['status']}\n"
                    f"Agent: {info.get('agent', 'Unknown')}\n"
                    f"Time: {format_time(info['timestamp'])}"
                )
                await update.message.reply_text(msg)
            else:
                await update.message.reply_text("❌ No record found for this order.")
        return

    orders_raw = match.group("orders")
    status_raw = match.group("status").lower().strip()
    status = STATUS_MAP.get(status_raw, status_raw)

    order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not order_list:
        return

    data = load_data()
    agent = update.message.from_user.full_name

    for order_id in order_list:
        data[order_id] = {
            "status": status,
            "timestamp": datetime.now(TIMEZONE).isoformat(),
            "agent": agent
        }

    save_data(data)

    # Reply confirmation (deleted after 5 sec)
    msg = await update.message.reply_text(f"✅ Updated {len(order_list)} order(s) by {agent}")
    await context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id), 5)

# ----------------------------
# Admin and user commands
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send an order number to check status or update in group.")

# /history - admin only
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in ADMINS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No orders yet.")
        return

    # Show last 10 orders
    last_orders = list(data.items())[-10:]
    msg = "📜 **Last 10 Orders:**\n"
    for order_id, info in last_orders:
        msg += f"📦 {order_id} - {info['status']} by {info.get('agent','Unknown')} at {format_time(info['timestamp'])}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# /myorders - any user, only their updates
async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.full_name
    data = load_data()
    user_orders = [(oid, info) for oid, info in data.items() if info.get("agent") == user]

    if not user_orders:
        await update.message.reply_text("❌ You have no orders updated yet.")
        return

    msg = f"📝 **Orders updated by {user}:**\n"
    for oid, info in user_orders:
        msg += f"📦 {oid} - {info['status']} at {format_time(info['timestamp'])}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

# /stats - admin only
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No orders yet.")
        return

    today_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d")
    today_orders = [o for o in data.values() if o['timestamp'].startswith(today_str)]

    total = len(today_orders)
    done_count = sum(1 for o in today_orders if o['status'] == "Order delivery completed")
    in_progress = sum(1 for o in today_orders if o['status'] not in ["Order delivery completed", "No answer from the number"])
    no_answer = sum(1 for o in today_orders if o['status'] == "No answer from the number")

    # Per-agent stats
    agent_counts = {}
    for o in today_orders:
        agent = o.get("agent", "Unknown")
        agent_counts[agent] = agent_counts.get(agent, 0) + 1

    agent_stats = "\n".join([f"👤 {agent}: {count}" for agent, count in agent_counts.items()])

    message = (
        f"📊 **Today's Order Stats**\n"
        f"Total orders updated: {total}\n"
        f"✅ Completed: {done_count}\n"
        f"🚚 In progress: {in_progress}\n"
        f"❌ No answer: {no_answer}\n\n"
        f"🧑‍🤝‍🧑 **Per-Agent Stats**\n"
        f"{agent_stats}"
    )

    await update.message.reply_text(message, parse_mode="Markdown")

# /reset - admin only
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    save_data({})
    await update.message.reply_text("🗑️ Order history cleared.")

# ----------------------------
# Main
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, group_listener))  # private lookup
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("reset", reset))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
