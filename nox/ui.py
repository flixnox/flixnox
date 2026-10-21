"""Texts and keyboards. All bot-facing text is English."""
from html import escape as esc

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import config
from .security import encode_room


def btn(text, cb=None, url=None, style=None):
    kw = {"text": text}
    if cb:
        kw["callback_data"] = cb
    if url:
        kw["url"] = url
    if style:
        kw["style"] = style          # "primary" blue | "success" green | "danger" red (Bot API button styles)
    return InlineKeyboardButton(**kw)


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


def mmss(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


def join_url(chat_id):
    return f"https://t.me/{config.BOT_USERNAME}/{config.MINIAPP_SHORT}?startapp={encode_room(chat_id)}&mode=compact"


WELCOME = (
    "✦ <b>ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ sᴏɴɪᴄ ɴᴏx</b>\n\n"
    "Hey {name}! I turn your group into a live listening room, so everyone hears the same song at the same time.\n\n"
    "▸ Add me to a group and make me admin\n"
    "▸ Send /start there to open the room\n"
    "▸ Queue songs with <code>/play song name</code>"
)
HELP = (
    "<b>ʜᴏᴡ ɪᴛ ᴡᴏʀᴋs</b>\n"
    "1. Add me to your group and make me admin (Pin messages).\n"
    "2. An admin sends /start, and I post the room message.\n"
    "3. Anyone adds songs with <code>/play song name</code>, or from the room itself.\n"
    "4. Tap <b>Join Room</b> to listen together.\n\n"
    "<b>ᴄᴏᴍᴍᴀɴᴅs</b>\n"
    "/play, /queue, /settings\n"
    "Admins: /skip, /pause, /resume, /loop, /shuffle, /clear, /end"
)
THANKS = ('Thanks for adding me! Make me an admin with "Pin messages", then send /start to open the room.')


def welcome_kb():
    rows = [[btn("➕ Add to Group", url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true&admin=pin_messages+delete_messages",
                 style="primary")],
            [btn("📖 Help", cb="h")]]
    if config.SUPPORT_URL:
        rows[1].append(btn("💬 Support", url=config.SUPPORT_URL))
    return kb(*rows)


def panel_kb(chat_id):
    return kb(
        [btn("🎧 Join Room", url=join_url(chat_id), style="primary")],
        [btn("⏯ Pause / Resume", cb="pp", style="success"), btn("⏭ Skip", cb="sk", style="primary")],
        [btn("📜 Queue", cb="q"), btn("🔁 Loop", cb="lp"), btn("🔀 Shuffle", cb="sh")],
    )


def panel_caption(room):
    head = "🎧 <b>ɴᴏx ʀᴏᴏᴍ</b>\n"
    if room is None or room.cur is None:
        return head + "<i>Nothing is playing yet.</i>\nAdd a song with <code>/play song name</code>, then tap Join Room."
    t = room.cur
    icon = "⏸" if room.paused else "▶"
    lines = [head + "<i>Tap Join Room to listen together.</i>\n",
             f"{icon} <b>{esc(t['title'][:70])}</b> — {esc(t['artist'][:40])}",
             f"⏱ {mmss(t.get('dur'))} • added by {esc(str(t.get('by') or 'someone')[:30])} • {len(room.clients)} listening"]
    if room.queue:
        lines.append("\n<b>ᴜᴘ ɴᴇxᴛ</b>")
        for i, q in enumerate(room.queue[:5], 1):
            lines.append(f"{i}. {esc(q['title'][:45])} — {esc(q['artist'][:25])}")
        if len(room.queue) > 5:
            lines.append(f"+{len(room.queue) - 5} more")
    lines.append("\nAdd songs with <code>/play song name</code>")
    text = "\n".join(lines)
    return text if len(text) <= 1000 else text[:990] + "…"


def queue_text(room):
    if room is None or (room.cur is None and not room.queue):
        return "The queue is empty. Add a song with <code>/play song name</code>."
    out = []
    if room.cur:
        out.append(f"▶ <b>{esc(room.cur['title'][:70])}</b> — {esc(room.cur['artist'][:40])}")
    for i, q in enumerate(room.queue[:15], 1):
        out.append(f"{i}. {esc(q['title'][:55])} — {esc(q['artist'][:30])}")
    if len(room.queue) > 15:
        out.append(f"+{len(room.queue) - 15} more")
    return "\n".join(out)


def settings_text(g):
    return ("⚙️ <b>ɢʀᴏᴜᴘ sᴇᴛᴛɪɴɢs</b>\n\n"
            f"Who can use /play: <b>{'Everyone' if g['play'] == 'all' else 'Admins only'}</b>\n"
            f"Delete command messages: <b>{'On' if g['autodel'] else 'Off'}</b>")


def settings_kb(g):
    return kb(
        [btn(("✅ " if g["play"] == "all" else "") + "Everyone can /play", cb="set:play:all", style="success" if g["play"] == "all" else None)],
        [btn(("✅ " if g["play"] == "admins" else "") + "Only admins can /play", cb="set:play:admins", style="success" if g["play"] == "admins" else None)],
        [btn("🧹 Auto-delete commands: " + ("On" if g["autodel"] else "Off"), cb="set:autodel:" + ("0" if g["autodel"] else "1"))],
        [btn("🗑 Clear queue", cb="set:clear"), btn("✖ Close", cb="set:close")],
    )
