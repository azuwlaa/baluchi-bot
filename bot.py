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

GROUP_ID = -1003484693080  # replace
ADMIN_LOG_CHANNEL = -1003484693080  # replace
ADMINS = {624102836}  # replace
DATA_FILE = "orders.json"

STATUS_MAP = {
    "out": "Out for delivery",
    "otw": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z]+)$", re.IGNORECASE)
URGENT_PATTERN = re.compile(r"order[# ]+(?P<oid>\d+)\s+urgent", re.IGNORECASE)


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
    return datetime.now(timezone.utc) + timedelta(hours=5)


# ----------------------------
# Agent Log Sender
# ----------------------------
async def send_agent_log(context: ContextTypes.DEFAULT_TYPE, oid, info):
    msg = (
        f"#Update:\n"
        f"• Order#: {oid}\n"
        f"• Agent: {info['agent']}\n"
        f"• Time: {info['timestamp']}\n"
        f"• Status: {info['status']}"
    )
    await context.bot.send_message(chat_id=ADMIN_LOG_CHANNEL, text=msg)


# ----------------------------
# Urgent Handler
# ----------------------------
async def handle_urgent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    m = URGENT_PATTERN.search(text)
    if not m:
        return

    oid = m.group("oid")
    data = load_data()

    if oid not in data:
        await update.message.reply_text("❌ Order not found.")
        return

    agent = data[oid].get("agent")
    if not agent:
        await update.message.reply_text("⚠️ No agent assigned yet.")
        return

    await update.message.reply_text("🚨 Urgent flag sent.")
    await context.bot.send_message(chat_id=ADMIN_LOG_CHANNEL, text=f"URGENT: Order {oid} by {agent}")


# ----------------------------
# Group Listener (Main Updates)
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Check for urgent messages first
    await handle_urgent(update, context)

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
    timestamp = now_gmt5().strftime("%H:%M:%S")

    for oid in order_list:
        data[oid] = {
            "status": status_full,
            "timestamp": timestamp,
            "agent": agent_name,
        }
        await send_agent_log(context, oid, data[oid])

    save_data(data)

    msg = await update.message.reply_text(f"✅ Updated {len(order_list)} order(s) by {agent_name}")
    context.job_queue.run_once(lambda ctx: ctx.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id), 5)


# ----------------------------
# Order Lookup
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
            f"Updated: {info['timestamp']}\n"
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
        await update.message.reply_text("You haven't updated any orders yet.")
        return

    msg = f"📋 Orders updated by {user_name}\n"
    for oid, info in user_orders:
        msg += f"Order# {oid}: {info['status']} ({info['timestamp']})\n"

    await update.message.reply_text(msg)


# ----------------------------
# /history (admins only)
# ----------------------------
async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("Admins only.")
        return

    data = load_data()
    msg = "Order History:\n"
    for oid, info in data.items():
        msg += f"{oid} — {info['status']} ({info['timestamp']}) by {info['agent']}\n"

    await update.message.reply_text(msg)


# ----------------------------
# /stats (admins only)
# ----------------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        await update.message.reply_text("Admins only.")
        return

    data = load_data()

    total = len(data)
    done = sum(1 for x in data.values() if "completed" in x["status"].lower())
    no = sum(1 for x in data.values() if "no answer" in x["status"].lower())
    inprog = total - done - no

    agent_stats = {}
    for info in data.values():
        agent = info.get("agent", "Unknown")
        if agent not in agent_stats:
            agent_stats[agent] = {"total": 0, "done": 0}
        agent_stats[agent]["total"] += 1
        if "completed" in info["status"].lower():
            agent_stats[agent]["done"] += 1

    msg = (
        f"📊 Today's Stats\n"
        f"Total: {total}\n"
        f"Completed: {done}\n"
        f"In progress: {inprog}\n"
        f"No answer: {no}\n\n"
        f"Per-Agent:\n"
    )

    for a, s in agent_stats.items():
        msg += f"{a}: {s['total']} updated, {s['done']} done\n"

    await update.message.reply_text(msg)


# ----------------------------
# Bot Main
# ----------------------------
def main():
    app = ApplicationBuilder().token("TOKEN_HERE").build()

    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, lookup_order))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("stats", stats))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
