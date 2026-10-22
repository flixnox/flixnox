from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from . import config, security


FONT_MAP = {
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ', 'g': 'ɢ',
    'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ', 'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ',
    'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ᴛ', 'r': 'ʀ', 's': 's', 't': 'ᴛ', 'u': 'ᴜ',
    'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ'
}


def to_small_caps(text):
    return ''.join(FONT_MAP.get(c.lower(), c) for c in text)


def control_panel_text(room):
    if not room.current:
        return f"🎧 {to_small_caps('Nox Room')}  •  🟢 {to_small_caps('Live')}"
    
    current = room.current
    title = current.get("title", "Unknown")[:50]
    artist = current.get("artist", "Unknown artist")[:40]
    duration = current.get("duration", "0:00")
    listeners = len(room.clients)
    
    queue_preview = ""
    if room.queue:
        queue_preview = f"\n⏭ {to_small_caps('Up Next')}\n"
        for i, song in enumerate(room.queue[:1], 1):
            song_title = song.get("title", "Unknown")[:35]
            queue_preview += f"{i}. {song_title}\n"
        if len(room.queue) > 1:
            queue_preview += f"  ... +{len(room.queue) - 1} more\n"
    
    panel = (
        f"🎧 {to_small_caps('Nox Room')}  •  🟢 {to_small_caps('Live')}\n"
        "★▬▬▬▬▬▬▬▬▬▬▬▬★\n"
        f"🎵 <b>{title}</b>\n"
        f"🎤 {artist}\n"
        f"⏱ {duration}   👤 {to_small_caps('Autoplay')}\n"
        "★▬▬▬▬▬▬▬▬▬▬▬▬★\n"
        f"🎧 {listeners} {to_small_caps('Listening')}  •  ♾ {to_small_caps('Auto')}\n"
        "★▬▬▬▬▬▬▬▬▬▬▬▬★"
    )
    
    if queue_preview:
        panel += queue_preview + "★▬▬▬▬▬▬▬▬▬▬▬▬★\n"
    
    panel += f"\n💡 /play song_name"
    return panel


def control_kb(chat_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🎧 JOIN ROOM", url=f"https://t.me/{config.BOT_USERNAME}/{config.MINIAPP_SHORT}?startapp={security.encode_room(chat_id)}"),
            InlineKeyboardButton(text="⋮", callback_data="menu")
        ],
        [
            InlineKeyboardButton(text="⏸ PAUSE", callback_data="pause"),
            InlineKeyboardButton(text="⏭ SKIP", callback_data="skip")
        ],
        [
            InlineKeyboardButton(text="📝 QUEUE", callback_data="queue"),
            InlineKeyboardButton(text="🔁 LOOP", callback_data="loop"),
            InlineKeyboardButton(text="🔀 SHUFFLE", callback_data="shuffle")
        ],
        [
            InlineKeyboardButton(text="♾ AUTO", callback_data="autoplay"),
            InlineKeyboardButton(text="📨 INVITE", callback_data="invite"),
            InlineKeyboardButton(text="⚙ MORE", callback_data="more")
        ]
    ])


def welcome_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 UPDATES", url="https://t.me/VelynNetwork"),
            InlineKeyboardButton(text="👨‍💻 DEVELOPERS", url="https://t.me/Eshalesthetics")
        ]
    ])


def welcome_text():
    return "🎧 <b>SONIC NOX</b>\n\n<i>Welcome to live music rooms!</i>\n\nStart a room with /start\nJoin live sessions anytime"


def added_text(track, pos, by):
    title = track.get("title", "Unknown")[:40]
    return f"✅ <b>{title}</b>\n\nAdded at position <b>{pos}</b>\nBy: {by}"


def queue_text(room):
    if not room or not room.queue:
        return "📝 <b>Queue</b>\n\n<i>No songs in queue</i>"
    text = f"📝 <b>Queue ({len(room.queue)} songs)</b>\n\n"
    for i, song in enumerate(room.queue[:10], 1):
        title = song.get("title", "Unknown")[:35]
        text += f"{i}. {title}\n"
    if len(room.queue) > 10:
        text += f"\n... +{len(room.queue) - 10} more"
    return text


def join_kb(chat_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🎧 Join Room", url=f"https://t.me/{config.BOT_USERNAME}/{config.MINIAPP_SHORT}?startapp={security.encode_room(chat_id)}")]])


def closed_caption():
    return "🎧 <b>Nox Room Closed</b>\n\n🌙 The room has ended\nThanks for listening!\n\n▶️ Admins: send /start to open a new room"


def ended_text():
    return "⏹ <b>Room Closed</b>\n\n▶️ Send /start to open it again"
