import json
import os
import re
import asyncio
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ----------------------------
# CONFIG
# ----------------------------
BOT_TOKEN = ""  # Add your bot token
GROUP_ID = -1003463796946
ADMINS = [624102836, 7477828866]
AGENT_LOG_CHANNEL = -1003484693080
DATA_FILE = "orders.json"

STATUS_MAP = {
    "out": "Out for delivery",
    "otw": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z]+)$", re.IGNORECASE)

# ----------------------------
# JSON STORAGE
# ----------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        save_data({})
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

def now_gmt5():
    return datetime.now(timezone.utc) + timedelta(hours=5)

# ----------------------------
# HELPER FUNCTIONS
# ----------------------------
async def send_agent_log(context: ContextTypes.DEFAULT_TYPE, orders, agent_name, status_full):
    message = (
        f"#Update:\n"
        f"• Orders#: {', '.join(orders)}\n"
        f"• Agent: {agent_name}\n"
        f"• Time: {now_gmt5().strftime('%H:%M')} ⏰\n"
        f"• Status: {status_full}"
    )
    await context.bot.send_message(chat_id=AGENT_LOG_CHANNEL, text=message)

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, orders, agent_name):
    msg = f"⚠️ Order(s) {', '.join(orders)} marked as NO ANSWER by {agent_name}"
    for admin in ADMINS:
        try:
            await context.bot.send_message(chat_id=admin, text=msg)
        except:
            pass

# ----------------------------
# COMMAND HANDLERS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send an order number to get its status.")

async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.full_name
    data = load_data()
    orders = [(oid, info) for oid, info in data.items() if info.get("agent") == user]
    if not orders:
        return await update.message.reply_text("You haven't updated any orders yet.")
    text = f"📋 Orders updated by {user}\n"
    for oid, info in orders:
        text += f"Order# {oid}: {info['status']} ⏰ {info['timestamp']}\n"
    await update.message.reply_text(text)

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")
    data = load_data()
    if not data:
        return await update.message.reply_text("No orders recorded yet.")
    text = "**Order History:**\n"
    for oid, info in data.items():
        text += f"Order# {oid}: {info['status']} ⏰ {info['timestamp']} by {info['agent']}\n"
    await update.message.reply_text(text)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")
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
    text = (
        f"📊 Order Stats\n"
        f"Total: {total}\n"
        f"✅ Completed: {done_count}\n"
        f"🚚 In Progress: {in_progress}\n"
        f"❌ No Answer: {no_answer}\n\n"
        f"🧑‍🤝‍🧑 Per-Agent Stats\n"
    )
    for agent, stats_info in agent_stats.items():
        text += f"{agent}: {stats_info['total']} updated, ✅ {stats_info['done']} done\n"
    await update.message.reply_text(text)

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")
    save_data({})
    await update.message.reply_text("✅ All order history cleared.")

async def undone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Admin only.")
    args = update.message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await update.message.reply_text("Usage: /undone 12345")
    order_id = args[1]
    data = load_data()
    if order_id not in data:
        return await update.message.reply_text("Order not found.")
    prev = data[order_id].get("prev_status", "Pending")
    data[order_id]["status"] = prev
    save_data(data)
    await update.message.reply_text(f"🔄 Order {order_id} reverted to: {prev}")

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = update.message.from_user.full_name
    data = load_data()
    updated = []

    for oid, info in data.items():
        if "no answer" not in info["status"].lower():
            info["status"] = STATUS_MAP["done"]
            info["timestamp"] = now_gmt5().strftime("%H:%M")
            info["agent"] = agent
            updated.append(oid)

    save_data(data)

    if not updated:
        return await update.message.reply_text("No orders eligible to mark as done.")

    # Auto-delete confirmation
    msg = await update.message.reply_text(
        f"✅ Marked {len(updated)} order(s) as done by {agent}"
    )
    await asyncio.sleep(5)
    try:
        await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
    except:
        pass

    await send_agent_log(context, updated, agent, STATUS_MAP["done"])

# ----------------------------
# MESSAGE HANDLERS
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.text.isdigit():
        return
    data = load_data()
    oid = update.message.text.strip()
    if oid in data:
        info = data[oid]
        await update.message.reply_text(
            f"Order#: {oid}\n"
            f"Status: {info['status']}\n"
            f"Updated: {info['timestamp']} ⏰\n"
            f"By: {info['agent']}"
        )

async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != GROUP_ID:
        return
    if not update.message.text:
        return

    match = ORDER_PATTERN.match(update.message.text.strip())
    if not match:
        return

    orders_raw = match.group("orders")
    status_key = match.group("status").lower()
    if status_key not in STATUS_MAP:
        return

    status_full = STATUS_MAP[status_key]
    orders = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not orders:
        return

    data = load_data()
    agent_name = update.message.from_user.full_name
    updated = []

    for oid in orders:
        prev_status = data.get(oid, {}).get("status", "")
        data[oid] = {
            "status": status_full,
            "timestamp": now_gmt5().strftime("%H:%M"),
            "agent": agent_name,
            "prev_status": prev_status,
        }
        updated.append(oid)

    save_data(data)

    if status_key == "no":
        await notify_admins(context, updated, agent_name)

    # Auto-delete confirmation
    msg = await update.message.reply_text(
        f"✅ Updated {len(updated)} order(s) by {agent_name}"
    )
    await asyncio.sleep(5)
    try:
        await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
    except:
        pass

    await send_agent_log(context, updated, agent_name, status_full)

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("undone", undone))
    app.add_handler(CommandHandler("done", done_command))

    # Message handlers
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))

    print("Bot running with PTB v21+ (Python 3.13 compatible)")
    app.run_polling()

if __name__ == "__main__":
    main()
