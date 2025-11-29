import json
import os
import re
from datetime import datetime, timedelta, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ----------------------------
# CONFIG
# ----------------------------
BOT_TOKEN = "PASTE_YOUR_TOKEN_HERE"
GROUP_ID = -1003463796946  # Replace with your Telegram group ID
ADMINS = [624102836, 7477828866]  # Telegram IDs of admins
AGENT_LOG_CHANNEL = -1003484693080  # Channel ID for agent logs
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
    try:
        if not os.path.exists(DATA_FILE):
            with open(DATA_FILE, "w") as f:
                json.dump({}, f)
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except:
        pass

def now_gmt5():
    return datetime.now(timezone.utc) + timedelta(hours=5)

async def send_agent_log(context: ContextTypes.DEFAULT_TYPE, orders, agent_name, status_full):
    orders_text = ", ".join(orders)
    message = (
        f"#Update:\n"
        f"• Orders#: {orders_text}\n"
        f"• Agent: {agent_name}\n"
        f"• Time: {now_gmt5().strftime('%H:%M')} ⏰\n"
        f"• Status: {status_full}"
    )
    await context.bot.send_message(chat_id=AGENT_LOG_CHANNEL, text=message)

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, message: str):
    for admin_id in ADMINS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=message)
        except:
            pass

# ----------------------------
# DELETE MESSAGE JOB
# ----------------------------
async def delete_message_callback(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.bot.delete_message(chat_id=context.job.chat_id, message_id=context.job.data)
    except:
        pass

# ----------------------------
# GROUP LISTENER
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        return
    if not update.message or not update.message.text:
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

    for order_id in order_list:
        prev_status = data.get(order_id, {}).get("status", "")
        data[order_id] = {
            "status": status_full,
            "timestamp": now_gmt5().strftime("%H:%M"),
            "agent": agent_name,
            "prev_status": prev_status,
        }
        updated_orders.append(order_id)

    save_data(data)

    # Notify admins if any order is "no"
    if status_key == "no":
        await notify_admins(context, f"⚠️ Order(s) {', '.join(updated_orders)} marked as NO ANSWER by {agent_name}")

    # Confirmation message + delete after 5 seconds
    msg = await update.message.reply_text(f"✅ Updated {len(updated_orders)} order(s) by {agent_name}")
    context.job_queue.run_once(delete_message_callback, 5, data=msg.message_id, chat_id=msg.chat_id)

    # Send agent log
    await send_agent_log(context, updated_orders, agent_name, status_full)

# ----------------------------
# ORDER LOOKUP WITH INLINE BUTTONS
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    if not text.isdigit():
        return

    data = load_data()
    order_info = data.get(text, {"status": "Not updated yet", "agent": "N/A", "timestamp": "N/A"})
    msg_text = (
        f"Order#: {text}\n"
        f"Status: {order_info['status']}\n"
        f"Updated: {order_info['timestamp']} ⏰\n"
        f"By: {order_info['agent']}"
    )

    # Create buttons for each status
    keyboard = [
        [InlineKeyboardButton(name, callback_data=f"{text}|{key}")]
        for key, name in STATUS_MAP.items()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(msg_text, reply_markup=reply_markup)

# ----------------------------
# INLINE BUTTON CALLBACK
# ----------------------------
async def status_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = load_data()

    try:
        order_id, status_key = query.data.split("|")
    except:
        return

    if status_key not in STATUS_MAP:
        return

    status_full = STATUS_MAP[status_key]
    agent_name = query.from_user.full_name
    prev_status = data.get(order_id, {}).get("status", "")

    data[order_id] = {
        "status": status_full,
        "timestamp": now_gmt5().strftime("%H:%M"),
        "agent": agent_name,
        "prev_status": prev_status,
    }
    save_data(data)

    await query.edit_message_text(f"✅ Order# {order_id} updated to '{status_full}' by {agent_name}")
    await send_agent_log(context, [order_id], agent_name, status_full)

    if status_key == "no":
        await notify_admins(context, f"⚠️ Order# {order_id} marked as NO ANSWER by {agent_name}")

# ----------------------------
# COMMANDS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    await update.message.reply_text("Send an order number to get its status.")

async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    user_name = update.message.from_user.full_name
    data = load_data()
    user_orders = [(oid, info) for oid, info in data.items() if info.get("agent") == user_name]
    if not user_orders:
        await update.message.reply_text("You haven't updated any orders yet.")
        return
    message = f"📋 Orders updated by {user_name}\n"
    for oid, info in user_orders:
        message += f"Order# {oid}: {info['status']} ⏰ {info['timestamp']}\n"
    await update.message.reply_text(message)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
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

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can reset orders.")
        return
    save_data({})
    await update.message.reply_text("✅ All order history has been cleared.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
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

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    data = load_data()
    agent_name = update.message.from_user.full_name
    updated_orders = []
    for order_id, info in data.items():
        if info["status"].lower() != "no":
            data[order_id]["status"] = STATUS_MAP["done"]
            data[order_id]["timestamp"] = now_gmt5().strftime("%H:%M")
            data[order_id]["agent"] = agent_name
            updated_orders.append(order_id)
    save_data(data)
    if updated_orders:
        msg = await update.message.reply_text(f"✅ Marked {len(updated_orders)} order(s) as done by {agent_name}")
        context.job_queue.run_once(delete_message_callback, 5, data=msg.message_id, chat_id=msg.chat_id)
        await send_agent_log(context, updated_orders, agent_name, STATUS_MAP["done"])
    else:
        await update.message.reply_text("No orders eligible to mark as done.")

async def undone_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or update.message.from_user.id not in ADMINS:
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /undone <order#>")
        return
    order_id = args[0]
    data = load_data()
    if order_id not in data:
        await update.message.reply_text(f"Order# {order_id} not found.")
        return
    prev_status = data[order_id].get("prev_status", "In Progress")
    data[order_id]["status"] = prev_status
    data[order_id]["timestamp"] = now_gmt5().strftime("%H:%M")
    save_data(data)
    await update.message.reply_text(f"✅ Order# {order_id} reverted to previous status: {prev_status}")

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.job_queue  # initialize job queue

    # Handlers
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))
    app.add_handler(CallbackQueryHandler(status_button_callback))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("undone", undone_command))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
