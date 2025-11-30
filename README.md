# Baluchi Delivery Bot

A Telegram bot to manage delivery orders with agent tracking, order statuses, and statistics.

---

## Features

- Agents can update orders with statuses:  
  - `out` → Out for delivery  
  - `otw` → On the way to city Hulhumale'  
  - `got` → Received by Hulhumale' agents  
  - `done` → Order delivery completed  
  - `no` → No answer from the number  

- **Agent-specific updates**: Each agent can only mark done for orders they previously updated.  
- `/undone <order#>`: Admins can revert completed orders.  
- `/status`: Admin-only command to see ongoing orders.  
- `/stats`: Admin-only command showing total orders and per-agent stats.  
- `/mystats`: Agents can view their personal stats.  
- `/comp`: List all completed orders.  
- `/myorders`: List orders updated by the agent.  
- Orders not yet updated show private message: `This order hasn't been updated yet!`.  
- Logs sent to a channel with agent username clickable.

---

## Installation

1. Clone the repository:

```bash
git clone https://github.com/yourusername/baluchi-bot.git
cd baluchi-bot
