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
    user_id = update.message.from_user.id
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
    else:
        # Private message if order hasn't been updated yet
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ This order hasn't been updated yet!"
        )

async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.id != GROUP_ID or not update.message.text:
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

        existing_orders, non_existing_orders = [], []
        for oid in orders:
            if oid in data:
                existing_orders.append(oid)
            else:
                non_existing_orders.append(oid)

        if non_existing_orders:
            await update.message.reply_text(
                f"❌ These orders haven't been updated yet: {', '.join(non_existing_orders)}"
            )

        orders = existing_orders
        if not orders: return

        updated = []
        for oid in orders:
            current_order = data[oid]
            if current_order.get("status") == STATUS_MAP["done"]:
                await update.message.reply_text(f"⚠️ Order {oid} has already been delivered!")
                continue
            current_order["status"] = STATUS_MAP["done"]
            current_order["timestamp"] = now_gmt5().strftime("%H:%M")
            current_order["agent"] = agent_name
            current_order.setdefault("history", []).append({
                "status": STATUS_MAP["done"],
                "agent": agent_name,
                "timestamp": current_order["timestamp"]
            })
            updated.append(oid)
        save_data(data)
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
    existing_orders, non_existing_orders = [], []
    for oid in orders:
        if oid in data:
            existing_orders.append(oid)
        else:
            non_existing_orders.append(oid)

    if non_existing_orders:
        await update.message.reply_text(
            f"❌ These orders haven't been updated yet: {', '.join(non_existing_orders)}"
        )

    orders = existing_orders
    if not orders: return

    updated = []
    for oid in orders:
        current_order = data[oid]

        if current_order.get("status") == STATUS_MAP["done"]:
            await update.message.reply_text(f"⚠️ Order {oid} has already been delivered!")
            continue  # Skip updating done orders

        current_order["status"] = status_full
        current_order["timestamp"] = now_gmt5().strftime("%H:%M")
        current_order["agent"] = agent_name
        history_list = current_order.get("history", [])
        history_list.append({"status": status_full,"agent": agent_name,"timestamp": current_order["timestamp"]})
        current_order["history"] = history_list
        data[oid] = current_order
        updated.append(oid)
    save_data(data)
    if status_key == "no":
        await notify_admins(context, updated, agent_name)
    msg = await update.message.reply_text(f"✅ Updated {len(updated)} order(s) by {agent_name}")
    await asyncio.sleep(5)
    try: await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
    except: pass
    if updated:
        await send_agent_log(context, updated, agent_name, status_full, action="Update", user_id=user_id)

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
        return await update.message.reply_text("❌ This order hasn't been updated yet!")
    history = data[order_id].get("history", [])
    last_non_done = None
    for entry in reversed(history):
        if entry["status"] != STATUS_MAP["done"]:
            last_non_done = entry
            break
    if last_non_done:
        data[order_id]["status"] = last_non_done["status"]
        data[order_id]["timestamp"] = last_non_done["timestamp"]
        data[order_id]["agent"] = last_non_done["agent"]
    else:
        data[order_id]["status"] = "Pending"
        data[order_id]["timestamp"] = now_gmt5().strftime("%H:%M")
        data[order_id]["agent"] = "Unknown"
    save_data(data)
    await update.message.reply_text(f"🔄 Order {order_id} status reverted.")
    await send_agent_log(context, [order_id], update.message.from_user.full_name, data[order_id]["status"], action="Undone", user_id=update.message.from_user.id)

async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = update.message.from_user.full_name
    user_id = update.message.from_user.id
    data = load_data()
    updated = []

    for oid, info in data.items():
        if info.get("status") == STATUS_MAP["done"]:
            continue
        if info.get("status") == STATUS_MAP["no"]:
            continue
        if info.get("agent") != agent:
            continue
        info["status"] = STATUS_MAP["done"]
        info["timestamp"] = now_gmt5().strftime("%H:%M")
        info.setdefault("history", []).append({
            "status": STATUS_MAP["done"],
            "agent": agent,
            "timestamp": info["timestamp"]
        })
        updated.append(oid)

    save_data(data)

    if not updated:
        return await update.message.reply_text(
            "No eligible orders to mark as done. Only your own orders in progress can be done."
        )

    msg = await update.message.reply_text(
        f"✅ Marked {len(updated)} order(s) as done by {agent}"
    )
    await asyncio.sleep(5)
    try:
        await context.bot.delete_message(chat_id=msg.chat_id, message_id=msg.message_id)
    except:
        pass

    await send_agent_log(context, updated, agent, STATUS_MAP["done"], action="Done", user_id=user_id)

async def completed_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    completed = [(oid, info) for oid, info in data.items() if info.get("status") == STATUS_MAP["done"]]
    if not completed:
        return await update.message.reply_text("No completed orders yet.")
    msg = "✅ Completed Orders:\n"
    for oid, info in completed:
        last_entry = info.get("history", [])[-1]
        msg += f"Order# {oid}: by {last_entry['agent']} at {last_entry['timestamp']}\n"
    await update.message.reply_text(msg)

async def ongoing_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    ongoing = [(oid, info) for oid, info in data.items() if info.get("status") != STATUS_MAP["done"]]
    if not ongoing:
        return await update.message.reply_text("No ongoing orders.")
    msg = "🚚 Ongoing Orders:\n"
    for oid, info in ongoing:
        last_entry = info.get("history", [])[-1] if info.get("history") else info
        msg += f"Order# {oid}: {last_entry['status']} by {last_entry.get('agent', 'Unknown')} at {last_entry.get('timestamp', 'Unknown')}\n"
    await update.message.reply_text(msg)

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await update.message.reply_text("❌ Only admins can view stats.")
    data = load_data()
    if not data:
        return await update.message.reply_text("No orders recorded yet.")

    total = done_count = in_progress = no_answer = 0
    agent_stats = {}
    for oid, info in data.items():
        status = info.get("status", "").lower()
        agent = info.get("agent", "Unknown")
        agent_stats.setdefault(agent, {"total": 0, "done": 0})
        agent_stats[agent]["total"] += 1
        total += 1
        if "completed" in status or status == STATUS_MAP["done"].lower():
            done_count += 1
            agent_stats[agent]["done"] += 1
        elif "no answer" in status or status == STATUS_MAP["no"].lower():
            no_answer += 1
        else:
            in_progress += 1

    msg = (
        f"📊 Today's Order Stats\n"
        f"Total orders updated: {total}\n"
        f"✅ Completed: {done_count}\n"
        f"🚚 In progress: {in_progress}\n"
        f"❌ No answer: {no_answer}\n\n"
        f"🧑‍🤝‍🧑 Per-Agent Stats\n"
    )
    for agent, stats_info in agent_stats.items():
        msg += f"{agent}: {stats_info['total']} updated, ✅ {stats_info['done']} done\n"

    await update.message.reply_text(msg)

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

    # Messages
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT, group_listener))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), lookup_order))

    print("Bot running with PTB v21+ (Python 3.13 compatible, HTML logs)")
    app.run_polling()

if __name__ == "__main__":
    main()
