Baluchi Telegram Bot

A Telegram bot for managing delivery orders with per-agent tracking, order history, and real-time updates. Built with Python 3.13 and python-telegram-bot v21+.

Features

Per-agent order tracking: Each order records which agent updated it, what status, and when.

Immutable completed orders: Orders marked as done cannot be changed unless /undone is used.

Order status commands:

/myorders → Orders updated by the current agent

/history → Full order history (admin only)

/stats → Summary of orders per agent (admin only)

/comp → View all completed orders with agent & timestamp

/status → View ongoing orders

/done → Mark all eligible orders as done

/undone <order#> → Revert a completed order (admin only)

Group listener: Agents can update orders directly by sending messages in the group in the format:

123,124,125 out
126 got


No answer tracking: If an order is marked as no, all admins are notified.

Auto-delete confirmation messages: Clean chat after 5 seconds.

Requirements

Python 3.13+

python-telegram-bot v21+

Virtual environment recommended

Install dependencies:

pip install --pre python-telegram-bot==21.4b0

Setup

Clone or copy the bot files:

baluchi-bot/
├── bot.py
├── orders.json
├── README.md


Update configuration in bot.py:

BOT_TOKEN = "YOUR_BOT_TOKEN"
GROUP_ID = -100XXXXXXXXXX
ADMINS = [123456789, 987654321]
AGENT_LOG_CHANNEL = -100XXXXXXXXXX


Run the bot:

python bot.py

Commands
Command	Description
/start	Welcome message
/myorders	Orders updated by you
/history	Full order history (admin only)
/stats	Orders summary per agent (admin only)
/reset	Clear all order history (admin only)
/undone <id>	Revert a completed order (admin only)
/done	Mark all eligible orders as done
/comp	View all completed orders with agent & time
/status	View ongoing orders
Group Order Format

Agents can update orders by sending messages in group chat:

123 out
124,125 otw
126 got
127 no


out → Out for delivery

otw → On the way to Hulhumale'

got → Received by Hulhumale' agents

done → Order completed

no → No answer from customer

Notes

Completed orders (done) cannot be changed by agents directly. Only admins can use /undone to revert.

Order history tracks every change including agent name and timestamp.

Notifications: If an order is marked no, all admins are automatically notified
