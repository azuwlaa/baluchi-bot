import json
import os
import re
import asyncio
from datetime import datetime, timedelta, timezone, time
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# ----------------------------
# CONFIG
# ----------------------------
BOT_TOKEN = ""  # Add your bot token
GROUP_ID = -1002631348221
ADMINS = [624102836, 7477828866]
AGENT_LOG_CHANNEL = -1003484693080
DATA_FILE = "orders.json"
AGENTS_FILE = "agents.json"

AUTO_DELETE_SECONDS = 10

# ----------------------------
# STATUS MAP
# ----------------------------
STATUS_MAP = {
    "out": "Out for delivery",

    "otw": "On the way to Hulhumale'",
    "on": "On the way to Hulhumale'",
    "ontheway": "On the way to Hulhumale'",
    "on-the-way": "On the way to Hulhumale'",
    "on_the_way": "On the way to Hulhumale'",

    "got": "Received by Hulhumale' agents",
    "rwav": "Received by Hulhumale' agents",
    "resv": "Received by Hulhumale' agents",
    "reav": "Received by Hulhumale' agents",
    "rcvd": "Received by Hulhumale' agents",
    "rwsv": "Received by Hulhumale' agents",
    "rwv": "Received by Hulhumale' agents",

    "no": "No answer from the number",
    "noanswer": "No answer from the number",
    "noanswers": "No answer from the number",
    "noanswering": "No answer from the number",
    "noans": "No answer from the number",

    "air": "On the way to airport",
    "done": "Order delivery completed",
}

NO_ANSWER_KEYS = {"no", "noanswer", "noanswers", "noanswering", "noans"}

ORDER_PATTERN = re.compile(
    r"^(?P<orders>[0-9 ,/]+)\s+(?P<status>[a-zA-Z _-]+)$",
    re.IGNORECASE
)


# ----------------------------
# HELPERS
# ----------------------------
def normalize_status_key(text: str) -> str:
    return text.lower().replace(" ", "").replace("-", "").replace("_", "")


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        save_data({})
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data: dict):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


def load_agents() -> dict:
    if not os.path.exists(AGENTS_FILE):
        save_agents({})
    with open(AGENTS_FILE, "r") as f:
        return json.load(f)


def save_agents(data: dict):
    with open(AGENTS_FILE, "w") as f:
        json.dump(data, f, indent=4)


def remember_agent(user_id: int, name: str):
    agents = load_agents()
    agents[str(user_id)] = name
    save_agents(agents)


def now_gmt5() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=5)


def apply_status(data: dict, orders: list, status_full: str, agent_name: str) -> list:
    """Apply a status to a list of order IDs. Returns list of updated IDs."""
    updated = []
    timestamp = now_gmt5().strftime("%H:%M")

    for oid in orders:
        current = data.get(oid, {})
        if current.get("status") == STATUS_MAP["done"]:
            continue

        current["status"] = status_full
        current["timestamp"] = timestamp
        current["agent"] = agent_name
        current.setdefault("history", []).append({
            "status": status_full,
            "agent": agent_name,
            "timestamp": timestamp,
        })
        data[oid] = current
        updated.append(oid)

    return updated


# ----------------------------
# AUTO-DELETE / TEMP MESSAGES
# ----------------------------
async def _schedule_delete(bot, chat_id: int, message_id: int, delay_seconds: int):
    await asyncio.sleep(delay_seconds)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def send_temporary_reply(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    timeout: int = AUTO_DELETE_SECONDS,
    parse_mode=None,
):
    if not update.message:
        return None
    msg = await update.message.reply_text(text, parse_mode=parse_mode)
    asyncio.create_task(_schedule_delete(context.bot, msg.chat_id, msg.message_id, timeout))
    return msg


# ----------------------------
# LOGGING HELPERS
# ----------------------------
async def send_agent_log(context, orders: list, agent_name: str, status_full: str, action: str = "Update", user_id: int = None):
    orders_text = ", ".join(orders)
    agent_html = f'<a href="tg://user?id={user_id}">{agent_name}</a>' if user_id else agent_name
    msg = (
        f"<b>#{action}</b>\n"
        f"• Orders#: {orders_text}\n"
        f"• Agent: {agent_html}\n"
        f"• Time: {now_gmt5().strftime('%H:%M')} ⏰\n"
        f"• Status: {status_full}"
    )
    await context.bot.send_message(chat_id=AGENT_LOG_CHANNEL, text=msg, parse_mode="HTML")


async def notify_admins(context, orders: list, agent_name: str):
    msg = f"⚠️ Orders {', '.join(orders)} marked as NO ANSWER by {agent_name}"
    for admin in ADMINS:
        try:
            await context.bot.send_message(chat_id=admin, text=msg)
        except Exception:
            pass


# ----------------------------
# /start
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Send an order number to check its status.")


# ----------------------------
# /urgent
# ----------------------------
async def urgent_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await send_temporary_reply(update, context, "❌ Admin only.")

    args = update.message.text.split()[1:]
    orders = [o for o in args if o.isdigit() and len(o) <= 6]

    if not orders:
        return await send_temporary_reply(update, context, "❌ No valid order numbers.")

    msg = await context.bot.send_message(chat_id=GROUP_ID, text=f"🚨 URGENT ORDERS: {', '.join(orders)}")
    try:
        await context.bot.pin_chat_message(chat_id=GROUP_ID, message_id=msg.message_id)
    except Exception:
        pass

    await send_temporary_reply(update, context, "✅ Urgent pinned.")


# ----------------------------
# LOOKUP ORDER (PRIVATE)
# ----------------------------
async def lookup_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()

    if not text.isdigit() or len(text) == 7:
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
    else:
        await update.message.reply_text("❌ No updates for this order yet.")


# ----------------------------
# GROUP LISTENER
# ----------------------------
async def group_listener(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    if update.message.chat.id != GROUP_ID:
        return

    text = update.message.text.strip()
    agent_name = update.message.from_user.full_name
    user_id = update.message.from_user.id

    remember_agent(user_id, agent_name)

    # (0) REPLY-BASED STATUS UPDATES
    if update.message.reply_to_message and update.message.reply_to_message.text:
        original_text = update.message.reply_to_message.text.strip()
        replied_orders = [o for o in re.split(r"[,/ ]+", original_text) if o.isdigit() and 1 <= len(o) <= 6]

        if replied_orders:
            status_key = normalize_status_key(text)
            if status_key in STATUS_MAP:
                status_full = STATUS_MAP[status_key]
                data = load_data()
                updated = apply_status(data, replied_orders, status_full, agent_name)
                save_data(data)

                if updated:
                    await send_temporary_reply(update, context, f"🔁 Updated orders {', '.join(updated)} via reply.")
                    await send_agent_log(context, updated, agent_name, status_full, action="Reply-Update", user_id=user_id)
                return

    # (1) "done" alone
    if text.lower() == "done":
        return await done_command(update, context)

    # (2) AUTO-OUT: only numbers
    raw_list = re.split(r"[,/ ]+", text)
    only_numbers = [o for o in raw_list if o.isdigit() and 1 <= len(o) <= 6]

    if only_numbers and len(only_numbers) == len(raw_list):
        status_full = STATUS_MAP["out"]
        data = load_data()
        updated = apply_status(data, only_numbers, status_full, agent_name)
        save_data(data)

        if updated:
            await send_temporary_reply(update, context, f"🚚 Marked {', '.join(updated)} as Out.")
            await send_agent_log(context, updated, agent_name, status_full, action="Update", user_id=user_id)
        return

    # (3) MANUAL DONE: "123/33 done"
    match_done = re.match(r"^([0-9 ,/]+)\s+done$", text, re.IGNORECASE)
    if match_done:
        orders = [o for o in re.split(r"[,/ ]+", match_done.group(1)) if o.isdigit() and 1 <= len(o) <= 6]
        if orders:
            status_full = STATUS_MAP["done"]
            data = load_data()
            updated = apply_status(data, orders, status_full, agent_name)
            save_data(data)

            if updated:
                await send_temporary_reply(update, context, f"✅ Marked {', '.join(updated)} done.")
                await send_agent_log(context, updated, agent_name, status_full, action="Done", user_id=user_id)
        return

    # (4) STANDARD UPDATES: "123 otw", "1080 no", etc.
    match = ORDER_PATTERN.match(text)
    if not match:
        return

    orders = [o for o in re.split(r"[,/ ]+", match.group("orders")) if o.isdigit() and 1 <= len(o) <= 6]
    if not orders:
        return

    status_key = normalize_status_key(match.group("status"))
    if status_key not in STATUS_MAP:
        return

    status_full = STATUS_MAP[status_key]
    data = load_data()
    updated = apply_status(data, orders, status_full, agent_name)
    save_data(data)

    if status_key in NO_ANSWER_KEYS:
        await notify_admins(context, updated, agent_name)

    if updated:
        await send_temporary_reply(update, context, f"✅ Updated {len(updated)} order(s).")
        await send_agent_log(context, updated, agent_name, status_full, action="Update", user_id=user_id)


# ----------------------------
# /agents
# ----------------------------
async def agents_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agents = load_agents()

    if not agents:
        return await update.message.reply_text("No agents recorded yet.")

    lines = ["🧑‍🤝‍🧑 *Registered Agents:*"]
    for uid, name in agents.items():
        lines.append(f"- [{name}](tg://user?id={uid}) — `ID:{uid}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ----------------------------
# /myorders
# ----------------------------
async def myorders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.full_name
    data = load_data()

    orders = [(oid, info) for oid, info in data.items() if info.get("agent") == user]

    if not orders:
        return await update.message.reply_text("You haven't updated any orders.")

    msg = [f"📝 *Orders updated by {user}:*"]
    for oid, info in orders:
        history = info.get("history", [])
        hist = "\n".join(f"  - *{h['status']}* at `{h['timestamp']}`" for h in reversed(history)) or "_No history._"
        msg.append(f"\n*Order `{oid}`* → {info['status']} at `{info['timestamp']}`\n{hist}")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


# ----------------------------
# /mystats
# ----------------------------
async def mystats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user.full_name
    data = load_data()

    total = done = no_ans = in_prog = 0

    for info in data.values():
        if info.get("agent") != user:
            continue
        total += 1
        status = info["status"].lower()
        if status == STATUS_MAP["done"].lower():
            done += 1
        elif status == STATUS_MAP["no"].lower():
            no_ans += 1
        else:
            in_prog += 1

    await update.message.reply_text(
        f"📊 Stats for {user}\n"
        f"Total updated: {total}\n"
        f"✅ Done: {done}\n"
        f"🚚 In progress: {in_prog}\n"
        f"❌ No answer: {no_ans}"
    )


# ----------------------------
# /check
# ----------------------------
async def check_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = update.message.text.split()

    if len(args) != 2 or not args[1].isdigit() or len(args[1]) == 7:
        return await send_temporary_reply(update, context, "Usage: /check 12345")

    order_id = args[1]
    data = load_data()

    if order_id not in data:
        return await send_temporary_reply(update, context, "❌ Order not found.")

    info = data[order_id]
    msg = [f"📝 *Order `{order_id}`*", f"Status: *{info['status']}*"]
    for h in info.get("history", []):
        msg.append(f"- *{h['status']}* by {h['agent']} at `{h['timestamp']}`")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


# ----------------------------
# /reset
# ----------------------------
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await send_temporary_reply(update, context, "❌ Admin only.")

    save_data({})
    save_agents({})
    await send_temporary_reply(update, context, "🗑 All data cleared.")


# ----------------------------
# /undone
# ----------------------------
async def undone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await send_temporary_reply(update, context, "❌ Admin only.")

    args = update.message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await send_temporary_reply(update, context, "Usage: /undone 12345")

    oid = args[1]
    data = load_data()

    if oid not in data:
        return await send_temporary_reply(update, context, "Order not found.")

    history = data[oid].get("history", [])
    last = next((h for h in reversed(history) if h["status"] != STATUS_MAP["done"]), None)

    if last:
        data[oid].update({"status": last["status"], "timestamp": last["timestamp"], "agent": last["agent"]})
    else:
        data[oid].update({"status": "Pending", "timestamp": now_gmt5().strftime("%H:%M"), "agent": "Unknown"})

    save_data(data)
    await send_temporary_reply(update, context, f"🔄 Order {oid} reverted.")


# ----------------------------
# /done
# ----------------------------
async def done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agent = update.message.from_user.full_name
    user_id = update.message.from_user.id
    remember_agent(user_id, agent)

    data = load_data()
    eligible = [oid for oid, info in data.items() if info.get("agent") == agent and info.get("status") != STATUS_MAP["done"]]
    updated = apply_status(data, eligible, STATUS_MAP["done"], agent)
    save_data(data)

    if not updated:
        return await send_temporary_reply(update, context, "No orders eligible for done.")

    await send_temporary_reply(update, context, f"✅ Marked {len(updated)} orders done.")
    await send_agent_log(context, updated, agent, STATUS_MAP["done"], action="Done", user_id=user_id)


# ----------------------------
# /comp
# ----------------------------
async def completed_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    completed = [(oid, info) for oid, info in data.items() if info.get("status") == STATUS_MAP["done"]]

    if not completed:
        return await update.message.reply_text("No completed orders.")

    msg = ["✅ *Completed Orders:*"]
    for oid, info in completed:
        last = (info.get("history") or [info])[-1]
        msg.append(f"- `{oid}` by {last['agent']} at `{last['timestamp']}`")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


# ----------------------------
# /status
# ----------------------------
async def ongoing_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = load_data()
    ongoing = [(oid, info) for oid, info in data.items() if info.get("status") != STATUS_MAP["done"]]

    if not ongoing:
        return await update.message.reply_text("No ongoing orders.")

    msg = ["🚚 *Ongoing Orders:*"]
    for oid, info in ongoing:
        last = (info.get("history") or [info])[-1]
        msg.append(f"- `{oid}` → {last['status']} by {last['agent']} at `{last['timestamp']}`")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


# ----------------------------
# /stats
# ----------------------------
async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id not in ADMINS:
        return await send_temporary_reply(update, context, "❌ Admin only.")

    data = load_data()
    if not data:
        return await send_temporary_reply(update, context, "No orders yet.")

    total = done = no_ans = in_prog = 0
    agent_stats = {}

    for info in data.values():
        status = info.get("status", "").lower()
        agent = info.get("agent", "Unknown")

        entry = agent_stats.setdefault(agent, {"total": 0, "done": 0})
        entry["total"] += 1
        total += 1

        if status == STATUS_MAP["done"].lower():
            entry["done"] += 1
            done += 1
        elif status == STATUS_MAP["no"].lower():
            no_ans += 1
        else:
            in_prog += 1

    msg = [
        "📊 *Today's Stats*",
        f"Total updated: {total}",
        f"✅ Done: {done}",
        f"🚚 In progress: {in_prog}",
        f"❌ No answer: {no_ans}",
        "\n🧍 *Agent Breakdown:*",
    ]
    for agent, s in agent_stats.items():
        msg.append(f"- {agent}: {s['total']} updated, {s['done']} done")

    await update.message.reply_text("\n".join(msg), parse_mode="Markdown")


# ----------------------------
# DAILY SUMMARY + RESET
# ----------------------------
async def daily_summary(context: ContextTypes.DEFAULT_TYPE):
    data = load_data()

    if not data:
        await context.bot.send_message(chat_id=AGENT_LOG_CHANNEL, text="📊 Daily Summary (No orders today).")
        save_data({})
        return

    total = done = no_ans = in_prog = 0
    agent_stats = {}

    for info in data.values():
        status = info.get("status", "").lower()
        agent = info.get("agent", "Unknown")

        entry = agent_stats.setdefault(agent, {"total": 0, "done": 0})
        entry["total"] += 1
        total += 1

        if status == STATUS_MAP["done"].lower():
            entry["done"] += 1
            done += 1
        elif status == STATUS_MAP["no"].lower():
            no_ans += 1
        else:
            in_prog += 1

    msg = [
        "📊 <b>Daily Summary</b>",
        f"Total updated: {total}",
        f"✅ Done: {done}",
        f"🚚 In progress: {in_prog}",
        f"❌ No answer: {no_ans}",
        "\n<b>🧍 Agent Breakdown:</b>",
    ]
    for agent, s in agent_stats.items():
        msg.append(f"- {agent}: {s['total']} updated, {s['done']} done")

    await context.bot.send_message(chat_id=AGENT_LOG_CHANNEL, text="\n".join(msg), parse_mode="HTML")
    save_data({})


# ----------------------------
# MAIN
# ----------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myorders", myorders))
    app.add_handler(CommandHandler("mystats", mystats))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("undone", undone))
    app.add_handler(CommandHandler("done", done_command))
    app.add_handler(CommandHandler("comp", completed_orders))
    app.add_handler(CommandHandler("status", ongoing_orders))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("check", check_order))
    app.add_handler(CommandHandler("urgent", urgent_command))
    app.add_handler(CommandHandler("agents", agents_list))

    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.TEXT & ~filters.COMMAND, group_listener))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, lookup_order))

    app.job_queue.run_daily(daily_summary, time=time(hour=1, minute=0, tzinfo=timezone.utc))

    print("Bot running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
