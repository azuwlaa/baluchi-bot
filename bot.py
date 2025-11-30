import json
import os
import re
from datetime import datetime, timedelta, timezone
from telegram import Update
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
BOT_TOKEN = "<YOUR_BOT_TOKEN>"
GROUP_ID = -1003463796946  # Main group
ADMINS = [624102836, 7477828866]  # Admin Telegram IDs
AGENT_LOG_CHANNEL = -1003484693080

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

async def send_agent_log(context: ContextTypes.DEFAULT_TYPE, orders, agent_name, status_full, action_type="#Update"):
    """Send log message to agent log channel with clickable username"""
    orders_text = ", ".join(orders)
    message = (
        f"{action_type}\n"
        f"◻️ Orders#: {orders_text}\n"
        f"◻️ Agent: [{agent_name}](tg://user?id={context.user_id})\n"
        f"◻️ Time: {now_gmt5().strftime('%H:%M')} ⏰\n"
        f"◻️ Status: {status_full}"
    )
    await context.bot.send_message(chat_id=AGENT_LOG_CHANNEL, text=message, parse_mode="Markdown")

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, message: str):
    for admin_id in ADMINS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=message)
        except:
            pass

# ----------------------------
# GROUP LISTENER
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if update.message.chat.id != GROUP_ID:
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
    updated_orders = []
    already_done_orders = []

    for order_id in order_list:
        prev_status = data.get(order_id, {}).get("status", "")
        prev_agent = data.get(order_id, {}).get("agent", "")
        if prev_status == STATUS_MAP["done"]:
            already_done_orders.append((order_id, prev_agent))
            continue

        data[order_id] = {
            "status": status_full,
            "timestamp": now_gmt5().strftime("%H:%M"),
            "agent": agent_name,
            "prev_status": prev_status,
        }
        updated_orders.append(order_id)

    save_data(data)

    if updated_orders:
        await update.message.reply_text(f"✅ Updated {len(updated_orders)} order(s) by {agent_name}")
        await send_agent_log(context, updated_orders, agent_name, status_full)

    for order_id, done_agent in already_done_orders:
        await update.message.reply_text(f"⚠️ Order {order_id} already delivered by {done_agent}!", quote=True)

# ----------------------------
# ORDER LOOKUP
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text.isdigit():
        return
    data = load_data()
    if text in data:
        info = data[text]
        await update.message.reply_text(
            f"Order#: {text}\n"
            f"Status: {info['status']}\n"
            f"Updated: {info['timestamp']} ⏰\n"
            f"By: {info['agent']}"
        )
    else:
        await update.message.reply_text("This order hasn't been updated yet!", quote=False)

# ----------------------------
# COMMANDS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send an order number to get its status.")

async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.full_name
    data = load_data()
    user_orders = [(oid, info) for oid, info in data.items() if info.get("agent") == user_name]
    if not user_orders:
        await update.message.reply_text("You haven't updated any orders yet.")
        return
    message = f"◻️ Orders updated by {user_name}\n"
    for oid, info in user_orders:
        message += f"◻️ Order# {oid}: {info['status']} ⏰ {info['timestamp']}\n"
    await update.message.reply_text(message)

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent_name = update.message.from_user.full_name
    data = load_data()
    updated_orders = []

    for oid, info in data.items():
        if info.get("agent") == agent_name and info.get("status") != STATUS_MAP["done"] and info.get("status") != STATUS_MAP["no"]:
            data[oid]["status"] = STATUS_MAP["done"]
            data[oid]["timestamp"] = now_gmt5().strftime("%H:%M")
            updated_orders.append(oid)

    save_data(data)

    if updated_orders:
        await update.message.reply_text(f"✅ Marked {len(updated_orders)} order(s) as done by {agent_name}")
        await send_agent_log(context, updated_orders, agent_name, STATUS_MAP["done"], action_type="#Done")

async def undone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can undo orders.")
        return
    if len(context.args) != 1:
        await update.message.reply_text("Usage: /undone <order#>")
        return
    order_id = context.args[0]
    data = load_data()
    if order_id not in data:
        await update.message.reply_text("Order not found.")
        return
    data[order_id]["status"] = data[order_id].get("prev_status", "Unknown")
    save_data(data)
    await update.message.reply_text(f"✅ Order {order_id} status reverted.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can view stats.")
        return

    data = load_data()
    total_orders = 0
    total_done = 0
    total_in_progress = 0
    total_no_answer = 0
    agent_stats = {}

    for oid, info in data.items():
        total_orders += 1
        agent = info.get("agent", "Unknown")
        status = info.get("status", "").lower()

        if agent not in agent_stats:
            agent_stats[agent] = {"total": 0, "done": 0}

        agent_stats[agent]["total"] += 1
        if "done" in status or "completed" in status:
            total_done += 1
            agent_stats[agent]["done"] += 1
        elif "no answer" in status:
            total_no_answer += 1
        else:
            total_in_progress += 1

    message = (
        f"📊 Today's Order Stats\n"
        f"Total orders updated: {total_orders}\n"
        f"✅ Completed: {total_done}\n"
        f"🚚 In progress: {total_in_progress}\n"
        f"❌ No answer: {total_no_answer}\n\n"
        f"🧑‍🤝‍🧑 Per-Agent Stats\n"
    )

    for agent, stats_info in agent_stats.items():
        message += f"{agent}: ◻️ {stats_info['total']} updated, ✅ {stats_info['done']} done\n"

    await update.message.reply_text(message)

async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.full_name
    data = load_data()
    total, done, in_progress, no_answer = 0, 0, 0, 0

    for oid, info in data.items():
        if info.get("agent") != user_name:
            continue
        total += 1
        status = info.get("status", "").lower()
        if "done" in status:
            done += 1
        elif "no answer" in status:
            no_answer += 1
        else:
            in_progress += 1

    message = (
        f"📊 {user_name}'s Order Stats\n\n"
        f"✅ Completed: {done}\n"
        f"🚚 In Progress: {in_progress}\n"
        f"❌ No Answer: {no_answer}\n"
        f"◻️ Total Orders Updated: {total}"
    )

    await update.message.reply_text(message)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return

    data = load_data()
    ongoing_orders = [(oid, info) for oid, info in data.items() if info.get("status") != STATUS_MAP["done"]]

    if not ongoing_orders:
        await update.message.reply_text("🚀 No ongoing orders.")
        return

    message = f"🚚 Ongoing Orders\n\n"
    message += f"◻️ Total ongoing orders: {len(ongoing_orders)}\n\n"

    for oid, info in ongoing_orders:
        agent = info.get("agent", "Unknown")
        status_text = info.get("status", "Unknown")
        timestamp = info.get("timestamp", "")
        message += f"◻️ Order# {oid}: {status_text} by {agent} ⏰ {timestamp}\n"

    await update.message.reply_text(message)

async def completed_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    comp_orders = [(oid, info) for oid, info in data.items() if info.get("status") == STATUS_MAP["done"]]

    if not comp_orders:
        await update.message.reply_text("No completed orders yet.")
        return

    message = "✅ Completed Orders\n\n"
    for oid, info in comp_orders:
        message += f"◻️ Order# {oid}: by {info['agent']} at {info['timestamp']}\n"

    await update.message.reply_text(message)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can reset orders.")
        return
    save_data({})
    await update.message.reply_text("✅ All order history has been cleared.")

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("undone", undone))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("mystats", mystats))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("comp", completed_orders))
    app.add_handler(CommandHandler("reset", reset))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
