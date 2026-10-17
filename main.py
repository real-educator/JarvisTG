import os
import json
import asyncio
import sqlite3
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from groq import Groq

# ==================== SAFE CONFIGURATION ====================
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
# Railway mein chahe GROQ_API_KEY naam rakhein ya GEMINI_API_KEY, dono chalega!
AI_API_KEY = (os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
SESSION_STRING = os.getenv("SESSION_STRING", "")
BOT_NAME = "KSHATRIYA JARVIS"
# ============================================================

app = Client("kshatriya_jarvis", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)
ai_client = Groq(api_key=AI_API_KEY)

# Folders & Database Setup
CACHE_DIR = os.path.abspath("jarvis_cache")
os.makedirs(CACHE_DIR, exist_ok=True)

conn = sqlite3.connect("jarvis_brain.db", check_same_thread=False)
cursor = conn.cursor()

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
def get_media_type(msg: Message) -> str:
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
    for attr in ["photo", "video", "voice", "audio", "document"]:
        media_obj = getattr(msg, attr, None)
        if media_obj and getattr(media_obj, "ttl_seconds", None):
            return True
    if getattr(msg, "ttl_period", None):
        return True
    return False

async def send_native_media(client: Client, target_chat, media_type: str, source: str, caption: str = ""):
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
# FEATURE 0: FULL TELEGRAM DATA SYNC
# =====================================================================
async def sync_telegram_data(client: Client):
    count = 0
    async for dialog in client.get_dialogs():
        chat = dialog.chat
        title = chat.first_name or chat.title or "Unknown"
        if chat.last_name:
            title += f" {chat.last_name}"
        username = f"@{chat.username}" if chat.username else "None"
        chat_type = str(chat.type).split(".")[-1]
        
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

    if is_self_destructing(message):
        try:
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

    if m_type != "text":
        try:
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
# FEATURE 3: ANTI-DELETE (Direct Media Show)
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
                media_source = local_path if (local_path and os.path.exists(local_path)) else f_id
                await send_native_media(client, "me", m_type, media_source, caption)
                if local_path and os.path.exists(local_path):
                    os.remove(local_path)

            cursor.execute("DELETE FROM messages WHERE chat_id=? AND message_id=?", (chat_id, msg_id))
            conn.commit()


# =====================================================================
# FEATURE 4: GROQ AI JARVIS BRAIN (100% Free & Ultra-Fast)
# =====================================================================
async def execute_jarvis_instruction(client: Client, user_instruction: str) -> str:
    cursor.execute("SELECT chat_id, title, username, chat_type FROM dialogs")
    dialogs = cursor.fetchall()
    words = [w.lower() for w in user_instruction.split() if len(w) > 2]
    matched = [d for d in dialogs if any(w in (d[1] or "").lower() or w in (d[2] or "").lower() for w in words)]
    final_dialogs = (matched + [d for d in dialogs if d not in matched])[:50]
    dialog_context = "\n".join([f"{d[0]}|{d[1]}|{d[2]}|{d[3]}" for d in final_dialogs])

    system_prompt = (
        f"You are {BOT_NAME}, an advanced AI Telegram assistant like Tony Stark's Jarvis. "
        f"Here is the user's Telegram directory (Contacts, Groups, Channels):\n{dialog_context}\n\n"
        f"If the user asks to send a message, post in a channel, broadcast to everyone, or read messages, "
        f"respond ONLY with a valid JSON object in one of these exact formats:\n"
        f'1. Send message/post: {{"action": "send", "chat_id": 123456, "text": "message here"}}\n'
        f'2. Broadcast to all private users: {{"action": "broadcast", "text": "message here"}}\n'
        f'3. Read chat history: {{"action": "read", "chat_id": 123456, "limit": 10}}\n'
        f'4. Normal conversation/question: {{"action": "reply", "text": "your Hinglish reply as Jarvis"}}'
    )

    # Sirf pure Text/Chat models filter karna (Audio/Terms wale models ko block karna)
    all_models = [m.id for m in ai_client.models.list().data]
    
    # Sabse best aur latest Groq Models ki priority list
    preferred = [
        "llama-3.3-70b-versatile",
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "meta-llama/llama-4-maverick-17b-128e-instruct",
        "qwen-qwq-32b",
        "deepseek-r1-distill-llama-70b",
        "gemma2-9b-it",
        "llama-3.1-8b-instant",
        "llama3-8b-8192"
    ]
    
    # Pehle preferred list mein se match karo, warna koi bhi 'llama' ya 'gemma' model uthao
    active_model = next((m for m in preferred if m in all_models), None)
    if not active_model:
        chat_models = [
            m for m in all_models 
            if ("llama" in m.lower() or "gemma" in m.lower() or "qwen" in m.lower())
            and not any(bad in m.lower() for bad in ["guard", "whisper", "vision", "orpheus", "canopy", "tts", "audio"])
        ]
        active_model = chat_models[0]

    completion = ai_client.chat.completions.create(
        model=active_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_instruction}
        ],
        response_format={"type": "json_object"},
        temperature=0.2
    )

    data = json.loads(completion.choices[0].message.content)
    action = data.get("action")

    if action == "send":
        target_id = int(data["chat_id"])
        msg_text = data["text"]
        await client.send_message(target_id, msg_text)
        return f"✅ **Done Sir!** Message/Post sent to `{target_id}`:\n> _{msg_text}_"

    elif action == "broadcast":
        msg_text = data["text"]
        cursor.execute("SELECT chat_id FROM dialogs WHERE chat_type='PRIVATE'")
        privates = cursor.fetchall()
        sent = 0
        for (cid,) in privates:
            try:
                await client.send_message(cid, msg_text)
                sent += 1
                await asyncio.sleep(1.5)
            except Exception:
                pass
        return f"📢 **Broadcast Complete, Sir!** `{sent}` private contacts ko message bhej diya gaya hai."

    elif action == "read":
        target_id = int(data["chat_id"])
        limit = int(data.get("limit", 10))
        history = []
        async for m in client.get_chat_history(target_id, limit=limit):
            sender = m.from_user.first_name if m.from_user else "Channel/User"
            history.append(f"{sender}: {m.text or '[Media]'}")
        history.reverse()
        return f"📖 **Last {limit} Messages from `{target_id}`:**\n\n" + "\n".join(history)

    return data.get("text", "⚡ Command processed, Sir.")


@app.on_message(filters.me & (filters.chat("me") | filters.command("j", prefixes=".")))
async def jarvis_ai_handler(client: Client, message: Message):
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


@app.on_message(filters.me & filters.command("sync", prefixes="."))
async def manual_sync(client: Client, message: Message):
    await message.edit_text(f"🔄 **{BOT_NAME}:** Scanning all Telegram Chats, Groups & Channels...")
    total = await sync_telegram_data(client)
    await message.edit_text(f"✅ **{BOT_NAME} Memory Updated!**\nTotal `{total}` Contacts, Groups & Channels indexed.")


async def start_jarvis():
    await app.start()
    total = await sync_telegram_data(app)
    await app.send_message(
        "me",
        f"⚡ **{BOT_NAME} v3.0 (Groq Powered) Online, Sir!**\n"
        f"📂 **Total Chats Indexed:** `{total}`\n"
        f"🛡️ **Anti-Delete (Direct Media):** Active\n"
        f"🔥 **View-Once Saver:** Active\n"
        f"✏️ **Edit Tracker:** Active\n\n"
        f"💡 _Ab aap isi Saved Messages mein seedha Hinglish mein hukum de sakte hain!_"
    )
    await asyncio.Event().wait()

if __name__ == "__main__":
    app.run(start_jarvis())
        
