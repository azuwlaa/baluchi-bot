import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message
from aiogram.filters import Command

# ===========================
# CONFIGURATION
# ===========================
BOT_TOKEN = ""
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

# ===========================
# JSON STORAGE
# ===========================
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

# ===========================
# BOT INITIALIZATION
# ===========================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===========================
# HELPER – AGENT LOG
# ===========================
async def send_agent_log(orders, agent_name, status_full):
    formatted = ", ".join(orders)
    text = (
        f"#Update:\n"
        f"• Orders#: {formatted}\n"
        f"• Agent: {agent_name}\n"
        f"• Time: {now_gmt5().strftime('%H:%M')} ⏰\n"
        f"• Status: {status_full}"
    )
    await bot.send_message(AGENT_LOG_CHANNEL, text)

async def notify_admins(orders, agent_name):
    text = f"⚠️ Order(s) {', '.join(orders)} marked as NO ANSWER by {agent_name}"
    for admin in ADMINS:
        try:
            await bot.send_message(admin, text)
        except:
            pass

# ===========================
# /start
# ===========================
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    await msg.answer("Send an order number to get its status.")

# ===========================
# ORDER LOOKUP (send number)
# ===========================
@dp.message(F.text.regexp(r"^\d+$"))
async def lookup(msg: Message):
    oid = msg.text.strip()
    data = load_data()

    if oid in data:
        info = data[oid]
        await msg.answer(
            f"Order#: {oid}\n"
            f"Status: {info['status']}\n"
            f"Updated: {info['timestamp']} ⏰\n"
            f"By: {info['agent']}"
        )

# ===========================
# GROUP LISTENER
# ===========================
ORDER_PATTERN = re.compile(r"^(?P<orders>[0-9 ,]+)\s+(?P<status>[a-zA-Z]+)$")

@dp.message(F.chat.id == GROUP_ID)
async def group_listener(msg: Message):
    if not msg.text:
        return

    match = ORDER_PATTERN.match(msg.text.strip())
    if not match:
        return

    orders_raw = match.group("orders")
    status_key = match.group("status").lower().strip()

    if status_key not in STATUS_MAP:
        return

    status_full = STATUS_MAP[status_key]
    orders = [o.strip() for o in orders_raw.split(",") if o.strip().isdigit()]

    if not orders:
        return

    data = load_data()
    agent_name = msg.from_user.full_name
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

    # Notify admins (NO ANSWER)
    if status_key == "no":
        await notify_admins(updated, agent_name)

    # Confirmation
    confirm = await msg.answer(f"✅ Updated {len(updated)} order(s) by {agent_name}")

    # Delete after 5 seconds
    await asyncio.sleep(5)
    try:
        await confirm.delete()
    except:
        pass

    # Agent log
    await send_agent_log(updated, agent_name, status_full)

# ===========================
# /myorders
# ===========================
@dp.message(Command("myorders"))
async def myorders(msg: Message):
    user = msg.from_user.full_name
    data = load_data()

    orders = [(oid, info) for oid, info in data.items() if info["agent"] == user]

    if not orders:
        return await msg.answer("You haven't updated any orders yet.")

    text = f"📋 Orders updated by {user}\n"
    for oid, info in orders:
        text += f"Order# {oid}: {info['status']} ⏰ {info['timestamp']}\n"

    await msg.answer(text)

# ===========================
# /history (admins only)
# ===========================
@dp.message(Command("history"))
async def history(msg: Message):
    if msg.from_user.id not in ADMINS:
        return await msg.answer("❌ Only admins can view history.")

    data = load_data()
    if not data:
        return await msg.answer("No orders recorded yet.")

    text = "📜 **Order History:**\n"
    for oid, info in data.items():
        text += f"Order# {oid}: {info['status']} ⏰ {info['timestamp']} by {info['agent']}\n"

    await msg.answer(text)

# ===========================
# /stats (admins only)
# ===========================
@dp.message(Command("stats"))
async def stats(msg: Message):
    if msg.from_user.id not in ADMINS:
        return await msg.answer("❌ Admin only command.")

    data = load_data()

    total = in_progress = done_count = no_answer = 0
    agent_stats = {}

    for oid, info in data.items():
        agent = info["agent"]
        status = info["status"].lower()

        agent_stats.setdefault(agent, {"total": 0, "done": 0})
        agent_stats[agent]["total"] += 1
        total += 1

        if "completed" in status:
            agent_stats[agent]["done"] += 1
            done_count += 1
        elif "no answer" in status:
            no_answer += 1
        else:
            in_progress += 1

    text = (
        f"📊 Today's Order Stats\n"
        f"Total: {total}\n"
        f"✅ Completed: {done_count}\n"
        f"🚚 In progress: {in_progress}\n"
        f"❌ No answer: {no_answer}\n\n"
        f"🧑‍🤝‍🧑 Per-Agent Stats\n"
    )

    for agent, st in agent_stats.items():
        text += f"{agent}: {st['total']} updated, {st['done']} done\n"

    await msg.answer(text)

# ===========================
# /reset (admins)
# ===========================
@dp.message(Command("reset"))
async def reset_db(msg: Message):
    if msg.from_user.id not in ADMINS:
        return await msg.answer("❌ Admin only command.")

    save_data({})
    await msg.answer("✅ All order history cleared.")

# ===========================
# /undone order#
# ===========================
@dp.message(Command("undone"))
async def undone(msg: Message):
    if msg.from_user.id not in ADMINS:
        return await msg.answer("❌ Admin only command.")

    args = msg.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await msg.answer("Usage: /undone 12345")

    target = args[1]
    data = load_data()

    if target not in data:
        return await msg.answer("Order not found.")

    old = data[target]["prev_status"] or "Pending"
    data[target]["status"] = old
    save_data(data)

    await msg.answer(f"🔄 Order {target} reverted to previous status: {old}")

# ===========================
# /done (mark everything done)
# ===========================
@dp.message(Command("done"))
async def mark_all_done(msg: Message):
    agent = msg.from_user.full_name
    data = load_data()
    updated = []

    for oid, info in data.items():
        if "no answer" not in info["status"].lower():
            data[oid]["status"] = STATUS_MAP["done"]
            data[oid]["timestamp"] = now_gmt5().strftime("%H:%M")
            data[oid]["agent"] = agent
            updated.append(oid)

    save_data(data)

    if not updated:
        return await msg.answer("No orders eligible to mark as done.")

    await msg.answer(f"✅ Marked {len(updated)} order(s) as completed.")
    await send_agent_log(updated, agent, STATUS_MAP["done"])

# ===========================
# MAIN LOOP
# ===========================
async def main():
    print("Bot running on Aiogram (Python 3.13 compatible)...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
