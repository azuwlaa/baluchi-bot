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
DATA_FILE = "orders.json"

STATUS_MAP = {
    "out": "Out for delivery",
    "otw": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>\w+)$", re.IGNORECASE)

# ----------------------------
# Helpers
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
# GROUP ORDER UPDATE
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return

    text = update.message.text.strip()
    match = ORDER_PATTERN.match(text)
    if not match:
        return

    orders_raw = match.group("orders")
    status_key = match.group("status").lower().strip()
    
    if status_key not in STATUS_MAP:
        # Only allow updates that match STATUS_MAP keys
        await update.message.reply_text(
            f"❌ Invalid status. Use one of: {', '.join(STATUS_MAP.keys())}"
        )
        return

    status_full = STATUS_MAP[status_key]

    order_list = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not order_list:
        return

    data = load_data()
    agent_name = update.message.from_user.full_name

    for order_id in order_list:
        data.setdefault(order_id, {"history": []})
        data[order_id]["status"] = status_full
        data[order_id]["history"].append({
            "status": status_full,
            "timestamp": now_gmt5().strftime("%H:%M:%S"),
            "agent": agent_name
        })

    save_data(data)

    msg = await update.message.reply_text(f"✅ Updated {len(order_list)} order(s) by {agent_name}")
    if context.job_queue:
        context.job_queue.run_once(
            lambda ctx: ctx.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id),
            5
        )

# ----------------------------
# ORDER LOOKUP (PRIVATE & GROUP)
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        return

    data = load_data()
    if text in data:
        last = data[text]["history"][-1]
        await update.message.reply_text(
            f"📦 Order {text}: {last['status']} by {last['agent']} ⏱ {last['timestamp']}",
            parse_mode=ParseMode.MARKDOWN
        )

# ----------------------------
# COMMANDS
# ----------------------------
async def start(update: Update, context):
    await update.message.reply_text("Send an order number to get its status.")

async def myorders(update: Update, context):
    user_name = update.message.from_user.full_name
    data = load_data()
    user_orders = [(oid, info) for oid, info in data.items() if any(h["agent"] == user_name for h in info["history"])]

    if not user_orders:
        await update.message.reply_text("You haven't updated any orders yet.")
        return

    message = f"📋 *Orders updated by {user_name}*\n"
    for oid, info in user_orders:
        for h in info["history"]:
            if h["agent"] == user_name:
                message += f"📦 {oid}: {h['status']} ⏱ {h['timestamp']}\n"

    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def history(update: Update, context):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can view history.")
        return

    data = load_data()
    if not data:
        await update.message.reply_text("No orders recorded yet.")
        return

    message = "*Order History:*\n"
    for oid, info in data.items():
        last = info["history"][-1]
        message += f"📦 {oid}: {last['status']} ⏱ {last['timestamp']} by {last['agent']}\n"

    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

async def reset(update: Update, context):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can reset orders.")
        return

    save_data({})
    await update.message.reply_text("✅ All order history cleared.")

async def stats(update: Update, context):
    if update.effective_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can view stats.")
        return

    data = load_data()
    total = done_count = in_progress = no_answer = 0
    agent_stats = {}

    for info in data.values():
        last = info["history"][-1]
        status = last["status"].lower()
        agent = last["agent"]
        agent_stats.setdefault(agent, {"total": 0, "done": 0})
        agent_stats[agent]["total"] += 1
        if "completed" in status or "done" in status:
            done_count += 1
            agent_stats[agent]["done"] += 1
        elif "no answer" in status or "no" in status:
            no_answer += 1
        else:
            in_progress += 1
        total += 1

    message = (
        f"📊 *Today's Order Stats*\n"
        f"Total orders updated: {total}\n"
        f"✅ Completed: {done_count}\n"
        f"🚚 In progress: {in_progress}\n"
        f"❌ No answer: {no_answer}\n\n"
        f"🧑‍🤝‍🧑 *Per-Agent Stats*\n"
    )
    for agent, stats_info in agent_stats.items():
        message += f"{agent}: {stats_info['total']} updated, ✅ {stats_info['done']} done\n"

    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN)

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Group updates
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    # Lookup orders anywhere
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
