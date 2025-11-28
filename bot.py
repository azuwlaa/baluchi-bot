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
    filters,
)

# ----------------------------
# CONFIG
# ----------------------------

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

ORDER_PATTERN = re.compile(
    r"^(?P<orders>[0-9 ,]+)\s+(?P<status>" + "|".join(STATUS_MAP.keys()) + r")$", re.IGNORECASE
)

# ----------------------------
# Helper Functions
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

def now_gmt5():
    """Return current time in GMT+5 as timezone-aware datetime"""
    return datetime.now(timezone.utc) + timedelta(hours=5)

# ----------------------------
# ORDER UPDATE HANDLER (GROUP)
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return  # Only accept updates from the specified group

    text = update.message.text.strip()
    match = ORDER_PATTERN.match(text)
    if not match:
        return

    orders_raw = match.group("orders")
    status_key = match.group("status").lower().strip()
    status_full = STATUS_MAP[status_key]

    order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not order_list:
        return

    data = load_data()
    agent_name = update.message.from_user.full_name

    for order_id in order_list:
        data[order_id] = {
            "status": status_full,
            "timestamp": now_gmt5().strftime("%H:%M:%S"),
            "agent": agent_name,
        }

    save_data(data)

    # Send confirmation that auto deletes after 5 seconds
    msg = await update.message.reply_text(f"✅ Updated {len(order_list)} order(s) by {agent_name}")
    await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)

# ----------------------------
# ORDER LOOKUP (PRIVATE or GROUP)
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        return  # Ignore non-order-number messages

    data = load_data()
    if text in data:
        info = data[text]
        await update.message.reply_text(
            f"Order#: {text}\n"
            f"Status: {info['status']}\n"
            f"Updated: {info['timestamp']} ⏰\n"
            f"By: {info['agent']}"
        )

# ----------------------------
# /start
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send an order number to get its status.")

# ----------------------------
# /myorders
# ----------------------------
async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.full_name
    data = load_data()
    user_orders = [(oid, info) for oid, info in data.items() if info.get("agent") == user_name]

    if not user_orders:
        await update.message.reply_text("❌ You haven't updated any orders yet.")
        return

    message = f"📋 **Orders updated by {user_name}**\n"
    for oid, info in user_orders:
        message += f"Order# {oid}: {info['status']} ⏰ {info['timestamp']}\n"

    await update.message.reply_text(message)

# ----------------------------
# /history (admin only)
# ----------------------------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can view history.")
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No orders recorded yet.")
        return

    message = "**Order History:**\n"
    for oid, info in data.items():
        message += f"Order# {oid}: {info['status']} ⏰ {info['timestamp']} by {info['agent']}\n"

    await update.message.reply_text(message)

# ----------------------------
# /reset (admin only)
# ----------------------------
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can reset orders.")
        return

    save_data({})
    await update.message.reply_text("✅ All order history has been cleared.")

# ----------------------------
# /stats (admin only)
# ----------------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can view stats.")
        return

    data = load_data()
    total = done_count = in_progress = no_answer = 0
    agent_stats = {}

    for oid, info in data.items():
        status = info["status"].lower()
        agent = info.get("agent", "Unknown")
        if agent not in agent_stats:
            agent_stats[agent] = {"total": 0, "done": 0}

        agent_stats[agent]["total"] += 1
        if "completed" in status:
            done_count += 1
            agent_stats[agent]["done"] += 1
        elif "no answer" in status:
            no_answer += 1
        else:
            in_progress += 1
        total += 1

    message = (
        f"📊 **Today's Order Stats**\n"
        f"Total orders updated: {total}\n"
        f"✅ Completed: {done_count}\n"
        f"🚚 In progress: {in_progress}\n"
        f"❌ No answer: {no_answer}\n\n"
        f"🧑‍🤝‍🧑 **Per-Agent Stats**\n"
    )
    for agent, stats_info in agent_stats.items():
        message += f"{agent}: {stats_info['total']} updated, ✅ {stats_info['done']} done\n"

    await update.message.reply_text(message)

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Group order updates
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))

    # Order lookup in private or group
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("stats", stats))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
