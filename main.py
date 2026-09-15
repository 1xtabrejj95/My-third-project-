import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
import asyncio
import yt_dlp

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.types import MessageEntity
from pyrogram.enums import MessageEntityType
from pytgcalls import PyTgCalls
from pytgcalls.types import MediaStream

# ============================================
# CONFIG
# ============================================

API_ID = int(os.environ.get("API_ID", "38680007"))
API_HASH = os.environ.get("API_HASH", "cc233beb120c0bd019b2e295d07cb31b")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8735943404:AAGXitz_yEDs7SaIK4a2FxFs2B9-BNlq-S4")
SESSION_STRING = os.environ.get("BQJONccAV7uSh7ndaODzh5n0DY6Z6-0FR3HpEpBV8hmZHAU_fTAT6FYx-PWDsd9B5905B1ZE05eIi-4-8TyXvxdKI4pI0LuBINxZoFWvtfZUl_kGevn7unH_CpRIEgyc7gMLMygNLAQyXmm7ZNoljwouDoCdWYwsG0LgNdc97QpLpabvTCAHas5Go-oFtBBRX9qMB9TJ8-tZGhouE2lOoAPMTFPML025Sv7nnO1IFDnIUFcUt9RZjpxpAbgIegsE0s7543sraAdkXGdlHRS2qGGD6apQceR2EehOj9erzAMF0bvcaSAXF9dzM6idflSu_795bRRlROQ7XG2kurpCsV_x5iB8MgAAAAIWYXuSAA", "")

# Owner ID (hamesha admin)
OWNER_ID = int(os.environ.get("OWNER_ID", "8965421970"))

# Extra global admins (comma / space separated)
_raw_admins = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = {int(x) for x in _raw_admins.replace(",", " ").split() if x.strip().isdigit()}
ADMIN_IDS.add(OWNER_ID)

# Group admins ko allow karna hai ya nahi
ALLOW_GROUP_ADMINS = os.environ.get("ALLOW_GROUP_ADMINS", "true").lower() == "true"

# ============================================
# PREMIUM EMOJI CONFIG
# ============================================
# Yahan apne REAL custom_emoji_ids daalein.
# /getemoji command se nikal sakte ho.
# Agar aapke paas IDs nahi hain to ye default rahne do —
# fallback me normal emoji bhej dega, error nahi dega.

PREMIUM_EMOJIS = {
    # "emoji_char": "custom_emoji_id_as_string",
    # Example (replace karein):
    # "🎵": "5368324170671202286",
    # "🎶": "5368324170671202286",
    # "▶️": "5368324170671202286",
    # "⏸️": "5368324170671202286",
    # "⏭️": "5368324170671202286",
    # "⏹️": "5368324170671202286",
    # "📋": "5368324170671202286",
    # "ℹ️": "5368324170671202286",
    # "🏓": "5368324170671202286",
    # "✅": "5368324170671202286",
    # "❌": "5368324170671202286",
    # "🔎": "5368324170671202286",
}

# Premium emoji ON/OFF
USE_PREMIUM_EMOJI = os.environ.get("USE_PREMIUM_EMOJI", "true").lower() == "true"

# ============================================
# CLIENTS
# ============================================

bot = Client(
    "music_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

assistant = Client(
    "assistant",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

call = PyTgCalls(assistant)

# ============================================
# ADMIN FILTER (Global + Group Admins)
# ============================================

async def _admin_check(_, client, message):
    if message.from_user is None:
        return False

    user_id = message.from_user.id

    # 1) Global admins / owner → har jagah allowed
    if user_id in ADMIN_IDS:
        return True

    # 2) Private chat me sirf global admins
    if message.chat.type == "private":
        return False

    # 3) Group admins (agar enabled hai)
    if not ALLOW_GROUP_ADMINS:
        return False

    try:
        member = await client.get_chat_member(message.chat.id, user_id)
        if member.status in ("administrator", "creator"):
            return True
        if getattr(member, "is_anonymous", False):
            return True
    except Exception:
        pass

    return False

admin_filter = filters.create(_admin_check)

# ============================================
# PREMIUM EMOJI HELPERS
# ============================================

def parse_premium(text: str):
    """
    Text me jo bhi emoji PREMIUM_EMOJIS me hai uske liye
    custom_emoji MessageEntity auto-generate karta hai.
    Returns: (text, entities or None)
    """
    if not USE_PREMIUM_EMOJI or not PREMIUM_EMOJIS:
        return text, None

    entities = []
    offset = 0  # UTF-16 offset
    i = 0
    while i < len(text):
        matched = False
        # Pehle 2-char emoji (jaise ▶️, ⏸️) try karo, phir 1-char
        for length in (2, 1):
            chunk = text[i:i + length]
            if chunk in PREMIUM_EMOJIS:
                try:
                    entities.append(
                        MessageEntity(
                            type=MessageEntityType.CUSTOM_EMOJI,
                            offset=offset,
                            length=length,
                            custom_emoji_id=int(PREMIUM_EMOJIS[chunk]),
                        )
                    )
                except Exception:
                    pass
                offset += length
                i += length
                matched = True
                break
        if not matched:
            offset += 1
            i += 1

    return text, entities or None


async def send_premium(message, text: str, **kwargs):
    """Premium emoji wala reply bhejne ka helper."""
    new_text, entities = parse_premium(text)
    try:
        if entities:
            return await message.reply_text(new_text, entities=entities, **kwargs)
        return await message.reply_text(text, **kwargs)
    except Exception:
        return await message.reply_text(text, **kwargs)


async def edit_premium(status_msg, text: str, **kwargs):
    """Premium emoji wala edit helper."""
    new_text, entities = parse_premium(text)
    try:
        if entities:
            return await status_msg.edit_text(new_text, entities=entities, **kwargs)
        return await status_msg.edit_text(text, **kwargs)
    except Exception:
        return await status_msg.edit_text(text, **kwargs)


# ============================================
# QUEUE
# ============================================

queues = {}

def get_queue(chat_id):
    if chat_id not in queues:
        queues[chat_id] = []
    return queues[chat_id]

# ============================================
# YOUTUBE SEARCH
# ============================================

def youtube_search(query):
    options = {
        "quiet": True,
        "no_warnings": True,
        "default_search": "ytsearch",
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        data = ydl.extract_info(f"ytsearch1:{query}", download=False)

    if not data or not data.get("entries"):
        return None

    video = data["entries"][0]
    vid_id = video.get("id")
    url = video.get("webpage_url") or video.get("url") or f"https://www.youtube.com/watch?v={vid_id}"
    if not url.startswith("http"):
        url = f"https://www.youtube.com/watch?v={vid_id}"

    return {
        "title": video.get("title", "Unknown"),
        "webpage_url": url,
        "duration": video.get("duration") or 0,
    }

# ============================================
# GET AUDIO STREAM URL
# ============================================

def get_audio(url):
    options = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
        return info["url"]

# ============================================
# START / HELP
# ============================================

@bot.on_message(filters.command("start"))
async def start(_, message):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🎵 Help", callback_data="help")]])
    await send_premium(
        message,
        "🎵 **Music Bot Online!**\n\n"
        "Use: `/play song name`\n"
        "Example: `/play Tum Hi Ho`\n\n"
        "Bot ko group me **admin** banao aur voice chat start karo.\n"
        "⚠️ Sirf **admins** hi commands use kar sakte hain.",
        reply_markup=kb,
    )


@bot.on_message(filters.command("help"))
async def help_command(_, message):
    await send_premium(
        message,
        "🎵 **Commands** (sirf admins ke liye)\n\n"
        "▶️ `/play song`\n"
        "⏸️ `/pause`\n"
        "▶️ `/resume`\n"
        "⏭️ `/skip`\n"
        "⏹️ `/stop`\n"
        "📋 `/queue`\n"
        "ℹ️ `/current`\n"
        "🏓 `/ping`\n"
        "🎨 `/getemoji` — premium emoji ID nikalne ke liye"
    )

# ============================================
# PLAY
# ============================================

@bot.on_message(filters.command("play") & admin_filter)
async def play(_, message):
    if len(message.command) < 2:
        return await send_premium(message, "❌ Usage: `/play song name`")

    query = " ".join(message.command[1:])
    status = await message.reply_text("🔎 Searching...")

    try:
        result = await asyncio.to_thread(youtube_search, query)
        if not result:
            return await edit_premium(status, "❌ Song nahi mila.")

        chat_id = message.chat.id
        queue = get_queue(chat_id)
        queue.append(result)

        if len(queue) == 1:
            audio_url = await asyncio.to_thread(get_audio, result["webpage_url"])
            stream = MediaStream(audio_url)
            try:
                await call.play(chat_id, stream)
            except Exception:
                await call.change_stream(chat_id, stream)

            await edit_premium(
                status,
                f"🎵 **Now Playing**\n\n🎶 {result['title']}"
            )
        else:
            await edit_premium(
                status,
                f"✅ **Added to Queue**\n\n🎶 {result['title']}\n📋 Position: {len(queue)}"
            )

    except Exception as e:
        await edit_premium(status, f"❌ Error:\n`{str(e)[:400]}`")

# ============================================
# QUEUE / CURRENT
# ============================================

@bot.on_message(filters.command("queue"))
async def queue_command(_, message):
    q = get_queue(message.chat.id)
    if not q:
        return await send_premium(message, "📋 Queue empty.")
    text = "📋 **Music Queue**\n\n" + "\n".join(
        f"{i}. 🎵 {s['title']}" for i, s in enumerate(q, 1)
    )
    await send_premium(message, text)


@bot.on_message(filters.command("current"))
async def current(_, message):
    q = get_queue(message.chat.id)
    if not q:
        return await send_premium(message, "❌ Nothing playing.")
    await send_premium(message, f"🎵 **Currently Playing**\n\n🎶 {q[0]['title']}")

# ============================================
# PAUSE / RESUME
# ============================================

@bot.on_message(filters.command("pause") & admin_filter)
async def pause(_, message):
    try:
        await call.pause(message.chat.id)
        await send_premium(message, "⏸️ Paused.")
    except Exception as e:
        await send_premium(message, f"❌ `{str(e)[:200]}`")


@bot.on_message(filters.command("resume") & admin_filter)
async def resume(_, message):
    try:
        await call.resume(message.chat.id)
        await send_premium(message, "▶️ Resumed.")
    except Exception as e:
        await send_premium(message, f"❌ `{str(e)[:200]}`")

# ============================================
# STOP
# ============================================

@bot.on_message(filters.command("stop") & admin_filter)
async def stop(_, message):
    chat_id = message.chat.id
    try:
        await call.leave_call(chat_id)
    except Exception:
        pass
    queues.pop(chat_id, None)
    await send_premium(message, "⏹️ Stopped & queue cleared.")

# ============================================
# SKIP
# ============================================

@bot.on_message(filters.command("skip") & admin_filter)
async def skip(_, message):
    chat_id = message.chat.id
    q = get_queue(chat_id)

    if not q:
        return await send_premium(message, "❌ Queue empty.")

    q.pop(0)

    if not q:
        try:
            await call.leave_call(chat_id)
        except Exception:
            pass
        return await send_premium(message, "⏭️ Queue finished.")

    nxt = q[0]
    try:
        audio_url = await asyncio.to_thread(get_audio, nxt["webpage_url"])
        await call.change_stream(chat_id, MediaStream(audio_url))
        await send_premium(message, f"⏭️ **Next**\n\n🎶 {nxt['title']}")
    except Exception as e:
        await send_premium(message, f"❌ `{str(e)[:300]}`")

# ============================================
# GET PREMIUM EMOJI ID
# ============================================

@bot.on_message(filters.command("getemoji"))
async def get_emoji_id(_, message):
    """
    Kisi premium emoji wale message pe reply karke /getemoji bhejo,
    ya khud message me premium emoji bhejo — bot ID bata dega.
    """
    target = message.reply_to_message or message
    entities = target.entities or []
    found = []

    for e in entities:
        if e.type == MessageEntityType.CUSTOM_EMOJI:
            # actual emoji character nikalne ke liye
            try:
                raw = target.text or target.caption or ""
                emoji_char = raw[e.offset: e.offset + e.length]
            except Exception:
                emoji_char = "?"
            found.append(f"{emoji_char}  →  `{e.custom_emoji_id}`")

    if not found:
        return await message.reply_text(
            "❌ Koi premium emoji nahi mila.\n\n"
            "**Kaise use karein:**\n"
            "1️⃣ Kisi premium emoji wale message pe reply karo\n"
            "2️⃣ `/getemoji` bhejo\n"
            "3️⃣ Bot aapko ID de dega\n\n"
            "Ab wo ID `PREMIUM_EMOJIS` dict me daal do."
        )

    await message.reply_text(
        "✅ **Premium Emoji IDs mile:**\n\n"
        + "\n".join(found)
        + "\n\n**Ab inhe** `PREMIUM_EMOJIS` **dict me daalein.**"
    )

# ============================================
# CALLBACKS / PING
# ============================================

@bot.on_callback_query()
async def callbacks(_, query):
    if query.data == "help":
        await query.answer()
        try:
            await query.message.edit_text(
                "🎵 `/play /pause /resume /skip /stop /queue /current /ping /getemoji`\n\n"
                "⚠️ Sirf admins commands use kar sakte hain."
            )
        except Exception:
            pass


@bot.on_message(filters.command("ping"))
async def ping(_, message):
    await send_premium(message, "🏓 **PONG!** Bot online.")

# ============================================
# RUN
# ============================================

async def main():
    await bot.start()
    await assistant.start()
    await call.start()
    print("🎵 MUSIC BOT STARTED")
    print(f"👑 Owner ID          : {OWNER_ID}")
    print(f"🛡️ Global Admins     : {ADMIN_IDS}")
    print(f"👥 Group Admins ON   : {ALLOW_GROUP_ADMINS}")
    print(f"✨ Premium Emoji ON  : {USE_PREMIUM_EMOJI}")
    print(f"🎨 Premium Emojis Map: {len(PREMIUM_EMOJIS)} entries")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
