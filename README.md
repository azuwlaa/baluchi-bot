# baluchi-bot
A Telegram bot for delivery teams to update and check order delivery statuses.


## Features
- Delivery agents update orders in group chats
- Admins check order status privately
- Supports multiple order updates at once
- Status keywords map to friendly descriptions


## Status Codes
| Keyword | Meaning |
|--------------|-------------------------------------------|
| out | Out for delivery |
| on the way | On the way to city Hulhumale' |
| got | Received by Hulhumale' agents |
| done | Delivery completed |
| no | No answer from the number |


## Installation
```bash
git clone https://github.com/yourname/order-status-bot
cd order-status-bot
pip install -r requirements.txt
