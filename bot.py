import json
import os
import re
from datetime import datetime, timedelta, timezone
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import asyncio

# ----------------------------
# CONFIG
# ----------------------------
BOT_TOKEN = ""  # Your bot token
DATA_FILE = "orders.json"

ADMINS = [624102836, 7477828866]
AGENT_LOG_CHANNEL = -1003484693080
GROUP_ID = -1003463796946  # static main group

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
async def send_agent_log(context: ContextTypes.DEFAULT_TYPE, orders, agent_name, status_full, action="Update", user_id=None):
    orders_text = ", ".join(orders)
    agent_html = f'<a href="tg://user?id={user_id}">{agent_name}</a>' if user_id else agent_name
    message = (
        f"<b>#{action}</b>\n"
        f"• Orders#: {orders_text}\n"
        f"• Agent: {agent_html}\n"
        f"• Time: {now_gmt5().strftime('%H:%M')} ⏰\n"
        f"• Status: {status_full}"
    )
    await context.bot.send_message(
        chat_id=AGENT_LOG_CHANNEL,
        text=message,
        parse_mode="HTML"
    )

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, orders, agent_name):
    msg = f"⚠️ Order(s) {', '.join(orders)} marked as NO ANSWER by {agent_name}"
    for admin in ADMINS:
        try:
            await context.bot.send_message(chat_id=admin, text=msg)
        except:
            pass

# ----------------------------
# MESSAGE HANDLERS
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user_id = update.message.from_user.id
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
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ This order hasn't been updated yet!"
        )

async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if update.message.chat.id != GROUP_ID:
        return

    text = update.message.text.strip()
    agent_name = update.message.from_user.full_name
    user_id = update.message.from_user.id

    # Manual done per order
    match_done = re.match(r"^([0-9 ,]+)\s+done$", text, re.IGNORECASE)
    if match_done:
        orders = [o.strip() for o in match_done.group(1).split(",") if o.strip().isdigit()]
        if not orders: return
        data = load_data()
        updated = []
        non_existing = []

        for oid in orders:
            if oid not in data:
                non_existing.append(oid)
                continue
            order = data[oid]
            if order.get("status") == STATUS_MAP["done"]:
                completed_by = order.get("agent", "Unknown")
                await update.message.reply_text(
                    f"⚠️ Order {oid} has already been delivered by {completed_by}!"
                )
                continue
            order["status"] = STATUS_MAP["done"]
            order["timestamp"] = now_gmt5().strftime("%H:%M")
            order["agent"] = agent_name
            order.setdefault("history", []).append({
                "status": STATUS_MAP["done"],
                "agent": agent_name,
                "timestamp": order["timestamp"]
            })
            data[oid] = order
            updated.append(oid)

        save_data(data)
        if non_existing:
            await update.message.reply_text(
                f"❌ These orders haven't been updated yet: {', '.join(non_existing)}"
            )
        if updated:
            await update.message.reply_text(
                f"✅ Orders {', '.join(updated)} marked as done manually by {agent_name}"
            )
            await send_agent_log(context, updated, agent_name, STATUS_MAP["done"], action="Done", user_id=user_id)
        return

    # Standard status updates
    match = ORDER_PATTERN.match(text)
    if not match: return
    orders_raw = match.group("orders")
    status_key = match.group("status").lower()
    if status_key not in STATUS_MAP: return
    status_full = STATUS_MAP[status_key]
    orders = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]
    if not orders: return

    data = load_data()
    updated = []

    for oid in orders:
        order = data.get(oid, {"status": "", "timestamp": "", "agent": "", "history": []})
        if order.get("status") == STATUS_MAP["done"]:
            completed_by = order.get("agent", "Unknown")
            await update.message.reply_text(
                f"⚠️ Order {oid} has already been delivered by {completed_by}!"
            )
            continue
        order["status"] = status_full
        order["timestamp"] = now_gmt5().strftime("%H:%M")
        order["agent"] = agent_name
        order.setdefault("history", []).append({
            "status": status_full,
            "agent": agent_name,
            "timestamp": order["timestamp"]
        })
        data[oid] = order
        updated.append(oid)

    save_data(data)
    if status_key == "no":
        await notify_admins(context, updated, agent_name)
    if updated:
        msg = await update.message.reply_text(f"✅ Updated {len(updated)} order(s) by {agent_name}")
        await asyncio.sleep(5)
        try:
            await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
        except:
            pass
        await send_agent_log(context, updated, agent_name, status_full, action="Update", user_id=user_id)

# ----------------------------
# COMMAND HANDLERS
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! Send an order number to check status.")

async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can reset orders.")
        return
    save_data({})
    await update.message.reply_text("✅ All order history has been cleared.")

# ----------------------------
# /done command (agent-specific)
# ----------------------------
async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.full_name
    user_id = update.message.from_user.id
    data = load_data()
    updated = []

    for oid, info in data.items():
        if info.get("agent") != user_name:
            continue
        if info.get("status") == STATUS_MAP["done"]:
            continue
        if "no answer" in info.get("status", "").lower():
            continue
        data[oid]["status"] = STATUS_MAP["done"]
        data[oid]["timestamp"] = now_gmt5().strftime("%H:%M")
        updated.append(oid)
    save_data(data)

    if updated:
        await update.message.reply_text(f"✅ You marked {len(updated)} order(s) as done.")
        await send_agent_log(context, updated, user_name, STATUS_MAP["done"], action="Done", user_id=user_id)

# ----------------------------
# /undone command
# ----------------------------
async def undone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can undo orders.")
        return
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /undone <order#>")
        return
    order_id = args[0]
    data = load_data()
    if order_id in data and data[order_id]["status"] == STATUS_MAP["done"]:
        data[order_id]["status"] = "Undone"
        save_data(data)
        await update.message.reply_text(f"✅ Order {order_id} undone.")
    else:
        await update.message.reply_text("❌ That order is not done or doesn't exist.")

# ----------------------------
# /comp command
# ----------------------------
async def completed_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    comp_orders = [(oid, info) for oid, info in data.items() if info.get("status") == STATUS_MAP["done"]]
    if not comp_orders:
        await update.message.reply_text("No completed orders yet.")
        return
    message = "✅ Completed Orders:\n"
    for oid, info in comp_orders:
        message += f"Order# {oid}: by {info['agent']} at {info['timestamp']}\n"
    await update.message.reply_text(message)

# ----------------------------
# /status command (admin-only)
# ----------------------------
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can use this command.")
        return
    data = load_data()
    ongoing = [(oid, info) for oid, info in data.items() if info.get("status") != STATUS_MAP["done"]]
    if not ongoing:
        await update.message.reply_text("No ongoing orders.")
        return
    message = "🚚 Ongoing Orders:\n"
    for oid, info in ongoing:
        message += f"Order# {oid}: {info['status']} by {info['agent']} ⏰ {info['timestamp']}\n"
    await update.message.reply_text(message)

# ----------------------------
# /stats command (admin-only)
# ----------------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("❌ Only admins can view stats.")
        return
    data = load_data()
    agent_stats = {}
    for oid, info in data.items():
        agent = info.get("agent", "Unknown")
        if agent not in agent_stats:
            agent_stats[agent] = {"total": 0, "done": 0}
        agent_stats[agent]["total"] += 1
        if info.get("status") == STATUS_MAP["done"]:
            agent_stats[agent]["done"] += 1
    message = "📊 Agent Stats:\n"
    for agent, s in agent_stats.items():
        message += f"{agent}: total {s['total']}, done {s['done']}\n"
    await update.message.reply_text(message)

# ----------------------------
# /mystats command
# ----------------------------
async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.message.from_user.full_name
    data = load_data()
    total = done = 0
    for oid, info in data.items():
        if info.get("agent") != user_name:
            continue
        total += 1
        if info.get("status") == STATUS_MAP["done"]:
            done += 1
    await update.message.reply_text(f"Your stats: total updated: {total}, done: {done}")

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("undone", undone))
    app.add_handler(CommandHandler("comp", completed_orders))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("mystats", mystats))

    # Messages
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
