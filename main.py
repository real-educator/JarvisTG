import os
import asyncio
import sqlite3
from datetime import datetime
from pyrogram import Client, filters, enums
from pyrogram.types import Message
from google import genai
from google.genai import types

# ==================== CONFIGURATION ====================
API_ID = 38074255  # Apna API ID yahan daalein (Integer)
API_HASH = "b24d8bf27bba4316a37c4bf2a7e9b9cf"  # Apna API HASH yahan daalein
GEMINI_API_KEY = "AQ.Ab8RN6JOOWHKx7N3AqVMgjTmBqmYUdct3ro03oxCinpCxTLwhw"  # Google AI Studio se free key daalein
BOT_NAME = "KSHATRIYA JARVIS"
SESSION_STRING = "BQJE948AKyGe3jgMEA8xSp-yzz4n5KdY1VrYLK-EWGOVL7aYNUblqizWwo9RB6C7RB4mt03PjkqCdNuOGnN_VhJo0U7Q3fZL6OnfYFmCoUGvStWeWCX5Y-nvn_mYLPcaN0-Q7O95WD8bNVSKnQ-Ji0n3_bAW2z8NqJwZI4cWvj7nzofoke23Ux7dvJ0zZP2brIQfanf-QS0rvuv2EsYXe1KaFMATrSpMdtH1gwUFbjLTIqZewztWAaBG3Gabupbrmwgo_-SvAvXzGdWzX9Wv6rCNFACC3Esy0LQRzJRDlVpbkQu1XO8LyS88eT-KhE_5SpW8GMK7y5L3o24EyN4GM9JqzqGO7QAAAAG_2mhyAA"
# =======================================================

app = Client("kshatriya_jarvis", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
# Agar key 'AQ.' se start hoti hai toh vertexai=True lagayein, warna normal
if GEMINI_API_KEY.startswith("AQ."):
    ai_client = genai.Client(vertexai=True, api_key=GEMINI_API_KEY)
else:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
# Folders & Database Setup
CACHE_DIR = os.path.abspath("jarvis_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

conn = sqlite3.connect("jarvis_brain.db", check_same_thread=False)
cursor = conn.cursor()

# Table 1: Messages & Media Cache (For Anti-Delete & Anti-Edit)
cursor.execute("""
CREATE TABLE IF NOT EXISTS messages (
    chat_id INTEGER,
    message_id INTEGER,
    sender_name TEXT,
    media_type TEXT,
    text TEXT,
    file_id TEXT,
    local_path TEXT,
    timestamp TEXT,
    PRIMARY KEY (chat_id, message_id)
)
""")

# Table 2: Telegram Full Dialogs/Contacts Memory (For AI Assistant)
cursor.execute("""
CREATE TABLE IF NOT EXISTS dialogs (
    chat_id INTEGER PRIMARY KEY,
    title TEXT,
    username TEXT,
    chat_type TEXT
)
""")
conn.commit()


# =====================================================================
# HELPER FUNCTIONS: MEDIA DETECTION & NATIVE MEDIA SENDER
# =====================================================================
def get_media_type( msg: Message) -> str:
    if msg.photo: return "photo"
    if msg.video: return "video"
    if msg.voice: return "voice"
    if msg.audio: return "audio"
    if msg.sticker: return "sticker"
    if msg.animation: return "animation"
    if msg.video_note: return "video_note"
    if msg.document: return "document"
    return "text"

def get_file_id(msg: Message) -> str:
    for attr in ["photo", "video", "voice", "audio", "sticker", "animation", "video_note", "document"]:
        media_obj = getattr(msg, attr, None)
        if media_obj:
            return media_obj.file_id
    return None

def is_self_destructing(msg: Message) -> bool:
    # Checks TTL seconds on Photo/Video/Voice/Audio or raw MTProto ttl_period
    for attr in ["photo", "video", "voice", "audio", "document"]:
        media_obj = getattr(msg, attr, None)
        if media_obj and getattr(media_obj, "ttl_seconds", None):
            return True
    if getattr(msg, "ttl_period", None):
        return True
    return False

async def send_native_media(client: Client, target_chat, media_type: str, source: str, caption: str = ""):
    """Bina file corrupt kiye direct Photo/Video/Sticker/Voice show karne wala function"""
    try:
        if media_type == "photo":
            await client.send_photo(target_chat, photo=source, caption=caption)
        elif media_type == "video":
            await client.send_video(target_chat, video=source, caption=caption)
        elif media_type == "voice":
            await client.send_voice(target_chat, voice=source, caption=caption)
        elif media_type == "audio":
            await client.send_audio(target_chat, audio=source, caption=caption)
        elif media_type == "animation":
            await client.send_animation(target_chat, animation=source, caption=caption)
        elif media_type == "sticker":
            await client.send_sticker(target_chat, sticker=source)
            if caption:
                await client.send_message(target_chat, caption)
        elif media_type == "video_note":
            await client.send_video_note(target_chat, video_note=source)
            if caption:
                await client.send_message(target_chat, caption)
        elif media_type == "document":
            await client.send_document(target_chat, document=source, caption=caption)
        else:
            await client.send_message(target_chat, caption)
    except Exception as e:
        await client.send_message(target_chat, f"{caption}\n\n⚠️ **Media Render Error:** `{e}`")


# =====================================================================
# FEATURE 0: FULL TELEGRAM DATA SYNC (Sabhi Chats/Channels Read Karna)
# =====================================================================
async def sync_telegram_data(client: Client):
    count = 0
    async for dialog in client.get_dialogs():
        chat = dialog.chat
        title = chat.first_name or chat.title or "Unknown"
        if chat.last_name:
            title += f" {chat.last_name}"
        username = f"@{chat.username}" if chat.username else "None"
        chat_type = str(chat.type).split(".")[-1]  # PRIVATE, GROUP, SUPERGROUP, CHANNEL
        
        cursor.execute(
            "INSERT OR REPLACE INTO dialogs VALUES (?, ?, ?, ?)",
            (chat.id, title, username, chat_type)
        )
        count += 1
    conn.commit()
    return count


# =====================================================================
# FEATURE 1 & 3: INCOMING MONITOR + ONE-TIME SAVER + ALL MEDIA CACHE
# =====================================================================
@app.on_message(filters.private & ~filters.me & ~filters.bot)
async def monitor_incoming(client: Client, message: Message):
    sender = message.from_user.first_name if message.from_user else "Unknown"
    chat_id = message.chat.id
    msg_id = message.id
    m_type = get_media_type(message)
    f_id = get_file_id(message)
    text_content = message.text or message.caption or ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    local_path = None

    # 1. Check One-Time / Self-Destructing Media
    if is_self_destructing(message):
        try:
            # Directory path with trailing slash preserves original filename & extension!
            dl_path = await client.download_media(message, file_name=f"{CACHE_DIR}/viewonce_{chat_id}_{msg_id}/")
            caption = (
                f"🔥 **{BOT_NAME} - One-Time Media Saved!**\n"
                f"👤 **Sender:** {sender} (`{chat_id}`)\n"
                f"⏰ **Time:** {now}\n"
                f"💬 **Caption:** {text_content or 'None'}"
            )
            await send_native_media(client, "me", m_type, dl_path, caption)
            if dl_path and os.path.exists(dl_path):
                os.remove(dl_path)
        except Exception as e:
            await client.send_message("me", f"⚠️ **One-Time Save Error:** `{e}`")
        return

    # 2. Download Media with Original Extension for Anti-Delete
    if m_type != "text":
        try:
            # Trailing slash ensures Pyrogram keeps .jpg, .mp4, .webp, .ogg etc.
            local_path = await client.download_media(
                message, file_name=f"{CACHE_DIR}/{chat_id}_{msg_id}/"
            )
        except Exception:
            local_path = None

    cursor.execute(
        "INSERT OR REPLACE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (chat_id, msg_id, sender, m_type, text_content, f_id, local_path, now)
    )
    conn.commit()


# Manual Command (.save) - Kisi bhi View-Once ya Timer media par reply karke .save likhein
@app.on_message(filters.me & filters.command("save", prefixes="."))
async def manual_save_viewonce(client: Client, message: Message):
    await message.delete()
    if not message.reply_to_message:
        return await client.send_message("me", "⚠️ Kisi media message par reply karke `.save` likhein!")
    
    rep = message.reply_to_message
    m_type = get_media_type(rep)
    dl_path = await client.download_media(rep, file_name=f"{CACHE_DIR}/manual_{rep.id}/")
    caption = f"🛡️ **Manually Saved by {BOT_NAME}**\n👤 **From:** {rep.chat.first_name or rep.chat.title}"
    await send_native_media(client, "me", m_type, dl_path, caption)
    if dl_path and os.path.exists(dl_path):
        os.remove(dl_path)


# =====================================================================
# FEATURE 2: EDITED MESSAGE TRACKER
# =====================================================================
@app.on_edited_message(filters.private & ~filters.me & ~filters.bot)
async def catch_edit(client: Client, message: Message):
    chat_id = message.chat.id
    msg_id = message.id
    new_text = message.text or message.caption or ""

    cursor.execute(
        "SELECT sender_name, text, timestamp FROM messages WHERE chat_id=? AND message_id=?",
        (chat_id, msg_id)
    )
    row = cursor.fetchone()
    if row:
        sender, old_text, old_time = row
        if old_text != new_text:
            alert = (
                f"✏️ **{BOT_NAME} - Edited Message Caught!**\n\n"
                f"👤 **Sender:** {sender} (`{chat_id}`)\n"
                f"🕒 **Sent At:** {old_time}\n\n"
                f"🔴 **Original:**\n`{old_text or '[No Text]'}`\n\n"
                f"🟢 **Edited To:**\n`{new_text or '[No Text]'}`"
            )
            await client.send_message("me", alert)
            cursor.execute("UPDATE messages SET text=? WHERE chat_id=? AND message_id=?", (new_text, chat_id, msg_id))
            conn.commit()


# =====================================================================
# FEATURE 3: ANTI-DELETE (Direct Media Show - Photo/Video/Sticker/Voice)
# =====================================================================
@app.on_deleted_messages()
async def catch_delete(client: Client, messages: list):
    for msg in messages:
        msg_id = msg.id
        if msg.chat:
            cursor.execute(
                "SELECT chat_id, sender_name, media_type, text, file_id, local_path, timestamp FROM messages WHERE chat_id=? AND message_id=?",
                (msg.chat.id, msg_id)
            )
        else:
            cursor.execute(
                "SELECT chat_id, sender_name, media_type, text, file_id, local_path, timestamp FROM messages WHERE message_id=?",
                (msg_id,)
            )
        
        row = cursor.fetchone()
        if row:
            chat_id, sender, m_type, text, f_id, local_path, timestamp = row
            caption = (
                f"🗑️ **{BOT_NAME} - Deleted {m_type.upper()} Recovered!**\n\n"
                f"👤 **Sender:** {sender} (`{chat_id}`)\n"
                f"⏰ **Time:** {timestamp}\n"
                f"💬 **Text/Caption:** {text or 'None'}"
            )

            if m_type == "text":
                await client.send_message("me", caption)
            else:
                # Use downloaded local file with intact extension, or fallback to file_id
                media_source = local_path if (local_path and os.path.exists(local_path)) else f_id
                await send_native_media(client, "me", m_type, media_source, caption)
                
                if local_path and os.path.exists(local_path):
                    os.remove(local_path)

            cursor.execute("DELETE FROM messages WHERE chat_id=? AND message_id=?", (chat_id, msg_id))
            conn.commit()


# =====================================================================
# FEATURE 4: AI JARVIS BRAIN (Natural Language Telegram Manager)
# =====================================================================
async def execute_jarvis_instruction(client: Client, user_instruction: str) -> str:
    # Fetch all indexed contacts, groups, and channels
    cursor.execute("SELECT chat_id, title, username, chat_type FROM dialogs")
    dialogs = cursor.fetchall()
    dialog_context = "\n".join([f"ID: {d[0]} | Name: {d[1]} | Username: {d[2]} | Type: {d[3]}" for d in dialogs[:250]])

    # Define tools that Gemini AI can trigger automatically
    def send_message_to_chat(chat_id: int, text: str) -> str:
        """Send a message or post to a specific user, group, or channel ID."""
        return f"SEND|{chat_id}|{text}"

    def broadcast_to_all_users(text: str) -> str:
        """Send a message to ALL private users/contacts in Telegram."""
        return f"BROADCAST|{text}"

    def read_recent_chat_messages(chat_id: int, limit: int = 10) -> str:
        """Read recent messages from a specific chat ID to summarize or check updates."""
        return f"READ|{chat_id}|{limit}"

    system_prompt = (
        f"You are {BOT_NAME}, an advanced AI Telegram controller. "
        f"The user will command you in Hindi, Hinglish, or English. "
        f"Here is the user's complete Telegram directory (Contacts, Groups, Channels):\n"
        f"{dialog_context}\n\n"
        f"Match the name requested by the user with the closest Name/Username in the directory and call the appropriate tool. "
        f"Always reply respectfully like Tony Stark's Jarvis in Hinglish."
    )

    response = ai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=user_instruction,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[send_message_to_chat, broadcast_to_all_users, read_recent_chat_messages],
            temperature=0.2
        )
    )

    # Check if AI decided to run an action/tool
    if response.function_calls:
        results = []
        for call in response.function_calls:
            name = call.name
            args = call.args

            if name == "send_message_to_chat":
                target_id = int(args["chat_id"])
                msg_text = args["text"]
                await client.send_message(target_id, msg_text)
                results.append(f"✅ **Done Sir!** Message/Post sent to `{target_id}`:\n> _{msg_text}_")

            elif name == "broadcast_to_all_users":
                msg_text = args["text"]
                cursor.execute("SELECT chat_id FROM dialogs WHERE chat_type='PRIVATE'")
                privates = cursor.fetchall()
                sent = 0
                for (cid,) in privates:
                    try:
                        await client.send_message(cid, msg_text)
                        sent += 1
                        await asyncio.sleep(1.5)  # FloodWait protection
                    except Exception:
                        pass
                results.append(f"📢 **Broadcast Complete, Sir!** `{sent}` private contacts ko message bhej diya gaya hai.")

            elif name == "read_recent_chat_messages":
                target_id = int(args["chat_id"])
                limit = int(args.get("limit", 10))
                history = []
                async for m in client.get_chat_history(target_id, limit=limit):
                    sender = m.from_user.first_name if m.from_user else "Channel/User"
                    history.append(f"{sender}: {m.text or '[Media]'}")
                history.reverse()
                joined_hist = "\n".join(history)
                results.append(f"📖 **Last {limit} Messages from `{target_id}`:**\n\n{joined_hist}")

        return "\n\n".join(results)

    return response.text or "⚡ Command processed, Sir."


# Trigger 1: Saved Messages mein bina kisi prefix ke direct baat karein!
# Ya kisi bhi chat mein ".j <instruction>" likhein
@app.on_message(filters.me & (filters.chat("me") | filters.command("j", prefixes=".")))
async def jarvis_ai_handler(client: Client, message: Message):
    # Ignore messages sent by Jarvis itself (which start with emojis used by Jarvis)
    if not message.text or message.text.startswith(("🔥", "🗑️", "✏️", "🤖", "✅", "📢", "📖", "⚠️", "⚡", ".")):
        if not message.text or not message.text.startswith(".j "):
            return

    query = message.text[3:].strip() if message.text.startswith(".j ") else message.text
    status_msg = await message.reply_text(f"🤖 **{BOT_NAME}:** Processing instruction, Sir...")

    try:
        reply = await execute_jarvis_instruction(client, query)
        await status_msg.edit_text(f"🤖 **{BOT_NAME}:**\n\n{reply}")
    except Exception as e:
        await status_msg.edit_text(f"⚠️ **Jarvis AI Error:** `{e}`")


# Trigger 2: Manual Data Sync Command (.sync)
@app.on_message(filters.me & filters.command("sync", prefixes="."))
async def manual_sync(client: Client, message: Message):
    await message.edit_text(f"🔄 **{BOT_NAME}:** Scanning all Telegram Chats, Groups & Channels...")
    total = await sync_telegram_data(client)
    await message.edit_text(f"✅ **{BOT_NAME} Memory Updated!**\nTotal `{total}` Contacts, Groups & Channels indexed.")


# Startup Initialization
async def start_jarvis():
    await app.start()
    print(f"🔄 {BOT_NAME} is reading your Telegram data...")
    total = await sync_telegram_data(app)
    print(f"✅ Synced {total} chats! {BOT_NAME} is now Fully Active!")
    await app.send_message(
        "me",
        f"⚡ **{BOT_NAME} v2.0 Online, Sir!**\n"
        f"📂 **Total Chats Read & Indexed:** `{total}`\n"
        f"🛡️ **Anti-Delete (Direct Media):** Active\n"
        f"🔥 **View-Once Saver:** Active\n"
        f"✏️ **Edit Tracker:** Active\n\n"
        f"💡 _Aap isi Saved Messages chat mein seedha Hindi/Hinglish mein hukum de sakte hain!_"
    )
    await asyncio.Event().wait()

if __name__ == "__main__":
    app.run(start_jarvis())
