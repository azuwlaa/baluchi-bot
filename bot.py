import json
import os
import re
from datetime import datetime, timedelta
from telegram import Update, ParseMode
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
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("Please set the BOT_TOKEN environment variable")

# The group where delivery agents will update orders
GROUP_ID = -1001234567890  # <-- Replace with your group ID

# Admin Telegram IDs
ADMINS = [123456789, 987654321]  # <-- Replace with your admin IDs

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

STATUS_WORDS = STATUS_MAP.keys()

ORDER_PATTERN = re.compile(
    r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z]+)$", re.IGNORECASE
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
    return datetime.utcnow() + timedelta(hours=5)


# ----------------------------
# GROUP ORDER UPDATES
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return  # Only from the specified group

    text = update.message.text.strip()
    match = ORDER_PATTERN.match(text)
    if not match:
        return

    status_raw = match.group("status").lower()
    if status_raw not in STATUS_WORDS:
        return

    orders_raw = match.group("orders")
    order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not order_list:
        return

    data = load_data()
    agent_name = update.message.from_user.full_name

    for order_id in order_list:
        data[order_id] = {
            "status": STATUS_MAP[status_raw],
            "timestamp": now_gmt5().strftime("%H:%M:%S"),
            "agent": agent_name,
        }

    save_data(data)

    msg = await update.message.reply_text(
        f"✅ Updated {len(order_list)} order(s) by {agent_name}"
    )
    # Optional: delete confirmation after 5 seconds if you want
    # context.application.create_task(
    #     context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id, timeout=5)
    # )


# ----------------------------
# ORDER LOOKUP (GROUP & PRIVATE)
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        return  # Only order numbers trigger

    data = load_data()
    if text in data:
        info = data[text]
        await update.message.reply_text(
            f"📦 Order: {text}\n"
            f"Status: {info['status']}\n"
            f"Updated: {info['timestamp']} ⏰\n"
            f"By: {info['agent']}",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text("No record found for this order.")


# ----------------------------
# COMMANDS
# ----------------------------
async def start(update, context):
    await update.message.reply_text("Send an order number to get its status.")


async def myorders(update, context):
    user_name = update.message.from_user.full_name
    data = load_data()
    user_orders = [(oid, info) for oid, info in data.items() if info.get("agent") == user_name]

    if not user_orders:
        await update.message.reply_text("You haven't updated any orders yet.")
        return

    message = f"📋 **Orders updated by {user_name}:**\n"
    for oid, info in user_orders:
        message += f"📦 {oid}: {info['status']} ⏰ {info['timestamp']}\n"

    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def history(update, context):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can view history.")
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No orders recorded yet.")
        return

    message = "**Order History:**\n"
    for oid, info in data.items():
        message += f"📦 {oid}: {info['status']} ⏰ {info['timestamp']} by {info['agent']}\n"

    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


async def reset(update, context):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can reset orders.")
        return

    save_data({})
    await update.message.reply_text("✅ All order history has been cleared.")


async def stats(update, context):
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

    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)


# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Group order updates
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))

    # Lookup order in group or private
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))

    # Commands work both in group and private
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("stats", stats))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
