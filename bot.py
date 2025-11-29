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
CONFIG_FILE = "config.json"
DATA_FILE = "orders.json"

ADMINS = [624102836, 7477828866]
AGENT_LOG_CHANNEL = -1003484693080

STATUS_MAP = {
    "out": "Out for delivery",
    "otw": "On the way to city Hulhumale'",
    "got": "Received by Hulhumale' agents",
    "done": "Order delivery completed",
    "no": "No answer from the number",
}

ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z]+)$", re.IGNORECASE)

# ----------------------------
# CONFIG FILE HANDLING
# ----------------------------
def load_config():
    if not os.path.exists(CONFIG_FILE):
        save_config({"GROUP_ID": -1003463796946})
    with open(CONFIG_FILE, "r") as f:
        return json.load(f)

def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=4)

config = load_config()
GROUP_ID = config.get("GROUP_ID", -1003463796946)

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
    oid = text

    if oid in data:
        info = data[oid]
        await update.message.reply_text(
            f"Order#: {oid}\n"
            f"Status: {info['status']}\n"
            f"Updated: {info['timestamp']} ⏰\n"
            f"By: {info['agent']}"
        )
    else:
        # Only send private message if order does not exist
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
        non_existing_orders = []

        for oid in orders:
            if oid not in data:
                non_existing_orders.append(oid)
                continue
            current_order = data[oid]

            if current_order.get("status") == STATUS_MAP["done"]:
                completed_by = current_order.get("agent", "Unknown")
                await update.message.reply_text(
                    f"⚠️ Order {oid} has already been delivered by {completed_by}!"
                )
                continue

            current_order["status"] = STATUS_MAP["done"]
            current_order["timestamp"] = now_gmt5().strftime("%H:%M")
            current_order["agent"] = agent_name
            current_order.setdefault("history", []).append({
                "status": STATUS_MAP["done"],
                "agent": agent_name,
                "timestamp": current_order["timestamp"]
            })
            data[oid] = current_order
            updated.append(oid)

        save_data(data)

        if non_existing_orders:
            await update.message.reply_text(
                f"❌ These orders haven't been updated yet: {', '.join(non_existing_orders)}"
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
        current_order = data.get(oid, {"status": "", "timestamp": "", "agent": "", "history": []})

        # Skip done orders and alert who completed it
        if current_order.get("status") == STATUS_MAP["done"]:
            completed_by = current_order.get("agent", "Unknown")
            await update.message.reply_text(
                f"⚠️ Order {oid} has already been delivered by {completed_by}!"
            )
            continue

        # Update or create
        current_order["status"] = status_full
        current_order["timestamp"] = now_gmt5().strftime("%H:%M")
        current_order["agent"] = agent_name
        current_order.setdefault("history", []).append({
            "status": status_full,
            "agent": agent_name,
            "timestamp": current_order["timestamp"]
        })
        data[oid] = current_order
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
# Same as previous version: start, myorders, reset, undone, done_command, completed_orders, ongoing_orders, stats, mystats

# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("undone", undone))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("comp", completed_orders))
    app.add_handler(CommandHandler("status", ongoing_orders))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("mystats", mystats))

    # Messages
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
