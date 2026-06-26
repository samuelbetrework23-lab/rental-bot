"""
House Rental Matching Telegram Bot - MVP
For Render.com free tier deployment (with keep-alive web server)
"""

import os
import sqlite3
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8770372470:AAH-xux4BcA_-uNnbneja3ElnHo7lyGdS1w")
DB_PATH = "listings.db"
PORT = int(os.environ.get("PORT", 8080))

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

LOCATION, PRICE, ROOMS, DESCRIPTION, PHOTO, CONFIRM = range(6)
SEARCH_LOCATION, SEARCH_MAX_PRICE = range(6, 8)


# ---------------------------------------------------------------------------
# KEEP-ALIVE WEB SERVER (so Render sees an open port + UptimeRobot can ping it)
# ---------------------------------------------------------------------------
class KeepAliveHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        pass  # suppress noisy logs


def run_keep_alive_server():
    server = HTTPServer(("0.0.0.0", PORT), KeepAliveHandler)
    logger.info(f"Keep-alive server running on port {PORT}")
    server.serve_forever()


# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_id INTEGER NOT NULL,
            owner_username TEXT,
            location TEXT NOT NULL,
            price INTEGER NOT NULL,
            rooms TEXT,
            description TEXT,
            photo_file_id TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def save_listing(data):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO listings (owner_id, owner_username, location, price, rooms, description, photo_file_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["owner_id"],
            data.get("owner_username"),
            data["location"],
            data["price"],
            data.get("rooms"),
            data.get("description"),
            data.get("photo_file_id"),
        ),
    )
    conn.commit()
    listing_id = cur.lastrowid
    conn.close()
    return listing_id


def search_listings(location=None, max_price=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    query = "SELECT id, owner_id, owner_username, location, price, rooms, description, photo_file_id FROM listings WHERE is_active = 1"
    params = []
    if location:
        query += " AND location LIKE ?"
        params.append(f"%{location}%")
    if max_price:
        query += " AND price <= ?"
        params.append(max_price)
    query += " ORDER BY created_at DESC LIMIT 10"
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows


def my_listings(owner_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id, location, price, is_active FROM listings WHERE owner_id = ? ORDER BY created_at DESC",
        (owner_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def deactivate_listing(listing_id, owner_id):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "UPDATE listings SET is_active = 0 WHERE id = ? AND owner_id = ?",
        (listing_id, owner_id),
    )
    conn.commit()
    changed = cur.rowcount > 0
    conn.close()
    return changed


# ---------------------------------------------------------------------------
# BOT HANDLERS
# ---------------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🏠 ቤት ላስታውቅ (Post a listing)", callback_data="post")],
        [InlineKeyboardButton("🔍 ቤት ልፈልግ (Search listings)", callback_data="search")],
        [InlineKeyboardButton("📋 የእኔ ማስታወቂያዎች (My listings)", callback_data="mine")],
    ]
    await update.message.reply_text(
        "👋 እንኳን ደህና መጡ!\n\nይህ bot ቤት አከራዮችን እና ተከራዮችን ደላላ ሳያስፈልግ በቀጥታ ያገናኛል።\n\nምን ማድረግ ይፈልጋሉ?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "post":
        await query.message.reply_text("📍 ቤቱ የት ይገኛል? (ለምሳሌ: ቦሌ፣ ጀርመን ኤምባሲ አካባቢ)")
        return LOCATION
    elif query.data == "search":
        await query.message.reply_text("📍 በየት አካባቢ ቤት ይፈልጋሉ? (ለምሳሌ: ቦሌ) ወይም 'ሁሉም' ብለው ይጻፉ")
        return SEARCH_LOCATION
    elif query.data == "mine":
        await show_my_listings(update, context)
        return ConversationHandler.END


async def post_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["location"] = update.message.text
    await update.message.reply_text("💰 ዋጋው በወር ስንት ብር ነው? (ቁጥር ብቻ ይጻፉ፣ ለምሳሌ: 8000)")
    return PRICE


async def post_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not text.isdigit():
        await update.message.reply_text("⚠️ እባክዎ ቁጥር ብቻ ይጻፉ (ለምሳሌ: 8000)")
        return PRICE
    context.user_data["price"] = int(text)
    await update.message.reply_text("🚪 ስንት ክፍል ነው? (ለምሳሌ: 1 መኝታ ቤት፣ ሳሎን)")
    return ROOMS


async def post_rooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["rooms"] = update.message.text
    await update.message.reply_text("📝 ስለ ቤቱ አጭር መግለጫ ይጻፉ")
    return DESCRIPTION


async def post_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text
    await update.message.reply_text("📷 የቤቱን ፎቶ ይላኩ (ካለ)፣ ካልሆነ 'ዝለል' ብለው ይጻፉ")
    return PHOTO


async def post_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["photo_file_id"] = update.message.photo[-1].file_id
    else:
        context.user_data["photo_file_id"] = None
    return await post_confirm(update, context)


async def post_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    data["owner_id"] = update.effective_user.id
    data["owner_username"] = update.effective_user.username
    listing_id = save_listing(data)

    summary = (
        f"✅ ማስታወቂያዎ ተመዝግቧል! (ID: {listing_id})\n\n"
        f"📍 አካባቢ: {data['location']}\n"
        f"💰 ዋጋ: {data['price']} ብር/ወር\n"
        f"🚪 ክፍል: {data.get('rooms')}\n"
        f"📝 መግለጫ: {data.get('description')}\n\n"
        f"ተከራዮች ሲፈልጉ ያገኙታል። ለማቆም /myposts ይጻፉ።"
    )
    await update.message.reply_text(summary)
    context.user_data.clear()
    return ConversationHandler.END


async def search_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data["search_location"] = None if text in ("ሁሉም", "all", "All") else text
    await update.message.reply_text("💰 ከፍተኛ ዋጋ (ብር/ወር) ስንት ይፈልጋሉ? ካልወደዱ 'ምንም' ይጻፉ")
    return SEARCH_MAX_PRICE


async def search_max_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    max_price = int(text) if text.isdigit() else None
    location = context.user_data.get("search_location")

    results = search_listings(location=location, max_price=max_price)
    if not results:
        await update.message.reply_text("😕 ምንም ማስታወቂያ አልተገኘም። ቆይተው እንደገና ይሞክሩ።")
        return ConversationHandler.END

    await update.message.reply_text(f"🔎 {len(results)} ውጤት(ቶች) ተገኝቷል:")
    for row in results:
        (listing_id, owner_id, owner_username, loc, price, rooms,
         description, photo_file_id) = row
        contact = f"@{owner_username}" if owner_username else "ስልክ ለማግኘት ባለቤቱን ያግኙ"
        caption = (
            f"📍 {loc}\n"
            f"💰 {price} ብር/ወር\n"
            f"🚪 {rooms}\n"
            f"📝 {description}\n"
            f"👤 አግኙ: {contact}\n"
            f"🆔 ID: {listing_id}"
        )
        if photo_file_id:
            await update.message.reply_photo(photo=photo_file_id, caption=caption)
        else:
            await update.message.reply_text(caption)
    return ConversationHandler.END


async def show_my_listings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    rows = my_listings(user_id)
    target = update.callback_query.message if update.callback_query else update.message
    if not rows:
        await target.reply_text("እስካሁን ምንም ማስታወቂያ አላስገቡም።")
        return
    text = "📋 የእርስዎ ማስታወቂያዎች:\n\n"
    for listing_id, location, price, is_active in rows:
        status = "✅ ገብቷል" if is_active else "❌ ቦዟል"
        text += f"ID {listing_id}: {location} - {price} ብር/ወር [{status}]\n"
    text += "\nማስታወቂያ ለማቆም: /remove <ID>"
    await target.reply_text(text)


async def myposts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_my_listings(update, context)


async def remove_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("እንዴት ይጠቀሙ: /remove 5")
        return
    listing_id = int(context.args[0])
    success = deactivate_listing(listing_id, update.effective_user.id)
    if success:
        await update.message.reply_text(f"✅ ማስታወቂያ ID {listing_id} ቆሟል።")
    else:
        await update.message.reply_text("⚠️ ይህ ID አልተገኘም ወይም የእርስዎ አይደለም።")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("ተቋርጧል። /start ብለው ከመጀመሪያ ይጀምሩ።")
    return ConversationHandler.END


def main():
    init_db()

    # Start the keep-alive HTTP server in a background thread
    keep_alive_thread = threading.Thread(target=run_keep_alive_server, daemon=True)
    keep_alive_thread.start()

    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(menu_callback, pattern="^(post|search|mine)$")],
        states={
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_location)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_price)],
            ROOMS: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_rooms)],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, post_description)],
            PHOTO: [MessageHandler((filters.PHOTO | filters.TEXT) & ~filters.COMMAND, post_photo)],
            SEARCH_LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_location)],
            SEARCH_MAX_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_max_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myposts", myposts_command))
    app.add_handler(CommandHandler("remove", remove_command))
    app.add_handler(conv_handler)

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
