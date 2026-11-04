# Maneesha Enterprises - Billing & Stock (MongoDB)

Flask + MongoDB app: billing (58mm / 80mm thermal receipts), item & stock management, bill void, daily report.

## 1. MongoDB (free): MongoDB Atlas
1. Create a free M0 cluster at mongodb.com/atlas.
2. Database Access > add a user (username + password).
3. Network Access > Add IP Address > 0.0.0.0/0 (Koyeb IPs change).
4. Connect > Drivers > copy the connection string, e.g.
   mongodb+srv://USER:PASSWORD@cluster0.xxxxx.mongodb.net/
   (replace USER and PASSWORD; special characters in the password must be URL-encoded)

## 2. Deploy on Koyeb
1. Push this folder to a GitHub repository.
2. Koyeb > Create Web Service > GitHub > pick the repo > Builder: Buildpack.
   The start command is read from `Procfile`. Health check path: /health
3. Environment variables:
   - MONGODB_URI   = the Atlas connection string (required)
   - SECRET_KEY    = long random text (required)
   - APP_PASSWORD  = login password (required)
   - MONGODB_DB    = database name (optional, default "maneesha")
   - SHOP_PHONE, SHOP_FOOTER_NOTE = optional, printed on bills
4. Deploy, open the URL, log in, add items, start billing.

## Printing
- Default bill size is 58mm. For an 80mm printer, open a bill with `?w=80`.
- Install the printer driver, choose it in the print dialog, set margins to "None".

## Run locally
    pip install -r requirements.txt
    set MONGODB_URI=... (or have MongoDB running on localhost)
    python app.py
