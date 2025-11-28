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
BOT_TOKEN = " "
GROUP_ID = -1003463796946  # Replace with your Telegram group ID
ADMINS = [624102836]  # Replace with Telegram IDs of admins
AGENT_LOG_CHANNEL = -1003484693080  # Replace with a channel ID for agent logs

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

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z]+)$", re.IGNORECASE)

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
    return datetime.now(timezone.utc) + timedelta(hours=5)

async def send_agent_log(context: ContextTypes.DEFAULT_TYPE, message: str):
    await context.bot.send_message(chat_id=AGENT_LOG_CHANNEL, text=message)

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, message: str):
    for admin_id in ADMINS:
        await context.bot.send_message(chat_id=admin_id, text=message)

# ----------------------------
# GROUP LISTENER
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID or not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    match = ORDER_PATTERN.match(text)
    if not match:
        return

    orders_raw = match.group("orders")
    status_key = match.group("status").lower().strip()
    if status_key not in STATUS_MAP:
        return

    status_full = STATUS_MAP[status_key]
    order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not order_list:
        return

    data = load_data()
    agent_name = update.message.from_user.full_name
    timestamp = now_gmt5().strftime("%H:%M:%S")

    for order_id in order_list:
        if order_id not in data:
            data[order_id] = []
        data[order_id].append({"status": status_full, "timestamp": timestamp, "agent": agent_name})

    save_data(data)

    # Confirmation message (auto-delete)
    msg = await update.message.reply_text(f"✅ Updated {len(order_list)} order(s) by {agent_name}")
    context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id), 5)

    # Notify admin if status is 'no'
    if status_key == "no":
        await notify_admins(context, f"⚠️ Order(s) {', '.join(order_list)} marked as NO ANSWER by {agent_name}")

    # Send update to agent log channel
    for order_id in order_list:
        log_msg = (
            f"#Update:\n• Order#: {order_id}\n"
            f"• Agent: {agent_name}\n"
            f"• Time: {timestamp}\n"
            f"• Status: {status_full}"
        )
        await send_agent_log(context, log_msg)

    # Check for urgent keyword
    if "urgent" in text.lower():
        await notify_admins(context, f"❗ Order(s) {', '.join(order_list)} marked URGENT by {agent_name}")

# ----------------------------
# ORDER LOOKUP (PRIVATE/GROUP)
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text.isdigit():
        return

    data = load_data()
    if text in data:
        info_list = data[text]
        message = f"📦 Order#: {text}\n"
        for info in info_list:
            message += f"Status: {info['status']} ⏰ {info['timestamp']} by {info['agent']}\n"
        await update.message.reply_text(message)
    else:
        await update.message.reply_text("No record found for this order.")

# ----------------------------
# /start
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text("Send an order number to get its status.")

# ----------------------------
# /myorders
# ----------------------------
async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_name = update.message.from_user.full_name
    data = load_data()
    user_orders = [(oid, info) for oid, history in data.items() for info in history if info.get("agent") == user_name]

    if not user_orders:
        await update.message.reply_text("You haven't updated any orders yet.")
        return

    message = f"📋 Orders updated by {user_name}:\n"
    for oid, info in user_orders:
        message += f"📦 {oid}: {info['status']} ⏰ {info['timestamp']}\n"

    await update.message.reply_text(message)

# ----------------------------
# /history (admin only)
# ----------------------------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.from_user.id not in ADMINS:
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No orders recorded yet.")
        return

    message = "**Order History:**\n"
    for oid, history in data.items():
        for info in history:
            message += f"📦 {oid}: {info['status']} ⏰ {info['timestamp']} by {info['agent']}\n"

    await update.message.reply_text(message)

# ----------------------------
# /reset (admin only)
# ----------------------------
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.from_user.id not in ADMINS:
        return

    save_data({})
    await update.message.reply_text("✅ All order history has been cleared.")

# ----------------------------
# /stats (admin only)
# ----------------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.from_user.id not in ADMINS:
        return

    data = load_data()
    total = done_count = in_progress = no_answer = 0
    agent_stats = {}

    for oid, history in data.items():
        for info in history:
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
        f"📊 Today's Order Stats\n"
        f"Total orders updated: {total}\n"
        f"✅ Completed: {done_count}\n"
        f"🚚 In progress: {in_progress}\n"
        f"❌ No answer: {no_answer}\n\n"
        f"🧑‍🤝‍🧑 Per-Agent Stats\n"
    )
    for agent, stats_info in agent_stats.items():
        message += f"{agent}: {stats_info['total']} updated, ✅ {stats_info['done']} done\n"

    await update.message.reply_text(message)

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Job queue initialized automatically in PTB
    app.job_queue

    # Handlers
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("stats", stats))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
