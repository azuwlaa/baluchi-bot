# Telegram Order Status Bot

This repository contains a Telegram bot for managing and tracking delivery orders.

---

## Features

* Updates orders in a specific group only.
* Delivery agents automatically tracked.
* Admin-only commands:

  * `/history` - view all order updates
  * `/stats` - view agent stats
  * `/reset` - clear order history
* Agents can use `/myorders` to see their updated orders.
* Auto-delete confirmation messages after 5 seconds.
* GMT+5 timezone timestamps.
* Clean and elegant status messages with emojis.
* Supports multiple orders in one message, e.g., `12345,12346 otw`.

---

## Setup

### Requirements

Create a `requirements.txt` file:

```
python-telegram-bot>=20.3
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### Configuration

In `bot.py`, configure the following variables:

```python
BOT_TOKEN = "YOUR_BOT_TOKEN_HERE"  # Replace with your bot token
GROUP_ID = -1001234567890           # Replace with your Telegram group ID
ADMINS = [12345678, 98765432]       # Replace with admin user IDs
```

### Running the bot

```bash
python bot.py
```

---

## Folder Structure

```
telegram-order-status-bot/
├── bot.py
├── orders.json  # Automatically created
├── requirements.txt
└── README.md
```

---

## Usage

### Order Status Updates (Group)

Delivery agents send order updates in the group using the format:

```
12345 out
12345,12346 otw
```

Available status codes:

* `out` - Out for delivery
* `otw` - On the way to city Hulhumale'
* `got` - Received by Hulhumale' agents
* `done` - Order delivery completed
* `no` - No answer from the number

The bot replies with a confirmation message that auto-deletes after 5 seconds.

### Admin Commands (Group or Private)

* `/history` - View order history.
* `/stats` - View daily stats per agent.
* `/reset` - Clear all order history.

### Agent Commands

* `/myorders` - View orders updated by yourself.

---

### Notes

* Make sure the bot is added to the group.
* Only the specified `GROUP_ID` can update orders.
* Admin IDs must be set in `ADMINS`.
* Time is shown in GMT+5.
* Multiple order updates can be sent in one message, separated by commas.

---

This bot is ready to be deployed and pushed to GitHub.
