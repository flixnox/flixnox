"""Texts and keyboards. All bot-facing text is English, with ꜱᴍᴀʟʟ ᴄᴀᴘꜱ for labels and every button coloured."""
from html import escape as esc

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import config
from .security import encode_room

_SC = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ")


def sc(text):
    """'join room' -> 'ᴊᴏɪɴ ʀᴏᴏᴍ' (emoji and punctuation untouched)."""
    return text.lower().translate(_SC)


P, S, D = "primary", "success", "danger"      # blue, green, red  (the only colours Telegram allows)


def btn(text, cb=None, url=None, style=P, small=True):
    kw = {"text": sc(text) if small else text}
    if cb:
        kw["callback_data"] = cb
    if url:
        kw["url"] = url
    if style:
        kw["style"] = style
    return InlineKeyboardButton(**kw)


def kb(*rows):
    return InlineKeyboardMarkup(inline_keyboard=[list(r) for r in rows])


def mmss(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


def join_url(chat_id):
    return f"https://t.me/{config.BOT_USERNAME}/{config.MINIAPP_SHORT}?startapp={encode_room(chat_id)}&mode=compact"


WELCOME = (
    "✨ <b>" + sc("welcome to sonic nox") + "</b> ✨\n\n"
    "Hey {name}! I turn your group into a <b>live listening room</b>, so everyone hears the same song at the same time.\n\n"
    "<blockquote>1️⃣ Add me to a group and make me admin\n"
    "2️⃣ Send /start there to open the room\n"
    "3️⃣ Queue songs with <code>/play song name</code></blockquote>"
)
HELP = (
    "📖 <b>" + sc("how it works") + "</b>\n"
    "<blockquote>1. Add me to your group and make me admin (Pin messages).\n"
    "2. An admin sends /start and I post the room message.\n"
    "3. Anyone adds songs with <code>/play song name</code> or from the room itself.\n"
    "4. Tap <b>Join Room</b> to listen together.</blockquote>\n"
    "🎛 <b>" + sc("commands") + "</b>\n"
    "/play, /queue, /settings\n"
    "<i>Admins:</i> /skip, /pause, /resume, /loop, /shuffle, /autoplay, /clear, /end"
)
THANKS = ("🎉 <b>" + sc("thanks for adding me") + "</b>\nMake me an admin with \"Pin messages\", then send /start to open the room.")


def welcome_kb():
    rows = [[btn("➕ Add to Group", url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true&admin=pin_messages+delete_messages", style=S)],
            [btn("📖 Help", cb="h", style=P)]]
    if config.SUPPORT_URL:
        rows[1].append(btn("💬 Support", url=config.SUPPORT_URL, style=P))
    return kb(*rows)


def panel_kb(chat_id, room=None):
    paused = bool(room and room.paused)
    return kb(
        [btn("🎧 Join Room", url=join_url(chat_id), style=P)],
        [btn("▶ Resume" if paused else "⏸ Pause", cb="pp", style=S), btn("⏭ Skip", cb="sk", style=P)],
        [btn("📜 Queue", cb="q", style=P), btn("🔁 Loop", cb="lp", style=S), btn("🔀 Shuffle", cb="sh", style=P)],
        [btn("♾ Autoplay", cb="ap", style=S), btn("⚙ Settings", cb="st", style=P)],
    )


def panel_caption(room):
    if room is None or room.cur is None:
        return (f"🎧 <b>{sc('nox room')}</b>  ⚪ <i>{sc('idle')}</i>\n\n"
                "Nothing is playing yet.\n"
                f"Add a song with <code>/play song name</code>, then tap <b>{sc('join room')}</b>.")
    t = room.cur
    live = "🟢" if not room.paused else "⏸"
    lines = [f"🎧 <b>{sc('nox room')}</b>  {live} <i>{sc('live' if not room.paused else 'paused')}</i>\n",
             f"▶ <b>{esc(t['title'][:70])}</b>",
             f"<i>{esc(t['artist'][:50])}</i> • {mmss(t.get('dur'))}",
             f"👤 {sc('by')} {esc(str(t.get('by') or 'someone')[:28])}  •  🎧 {len(room.clients)} {sc('listening')}"
             + ("  •  🔁" if room.loop else "") + ("  •  ♾" if room.autoplay else "")]
    if room.queue:
        q = [f"<b>{sc('up next')}</b>"]
        for i, x in enumerate(room.queue[:4], 1):
            q.append(f"{i}. {esc(x['title'][:40])} — {esc(x['artist'][:22])}")
        if len(room.queue) > 4:
            q.append(f"+{len(room.queue) - 4} more")
        lines.append("<blockquote>" + "\n".join(q) + "</blockquote>")
    lines.append("💡 <code>/play song name</code>")
    text = "\n".join(lines)
    return text if len(text) <= 1000 else text[:990] + "…"


def queue_text(room):
    if room is None or (room.cur is None and not room.queue):
        return "🫥 The queue is empty. Add a song with <code>/play song name</code>."
    out = [f"🎶 <b>{sc('queue')}</b>"]
    if room.cur:
        out.append(f"▶ <b>{esc(room.cur['title'][:70])}</b> — {esc(room.cur['artist'][:40])}")
    rows = [f"{i}. {esc(q['title'][:55])} — {esc(q['artist'][:30])}" for i, q in enumerate(room.queue[:15], 1)]
    if rows:
        out.append("<blockquote>" + "\n".join(rows) + "</blockquote>")
    if len(room.queue) > 15:
        out.append(f"+{len(room.queue) - 15} more")
    return "\n".join(out)


def settings_text(g):
    return (f"⚙️ <b>{sc('group settings')}</b>\n\n"
            f"🎵 {sc('who can use /play')}: <b>{'Everyone' if g['play'] == 'all' else 'Admins only'}</b>\n"
            f"🧹 {sc('delete command messages')}: <b>{'On' if g['autodel'] else 'Off'}</b>")


def settings_kb(g):
    return kb(
        [btn(("✅ " if g["play"] == "all" else "") + "Everyone can /play", cb="set:play:all", style=S if g["play"] == "all" else P)],
        [btn(("✅ " if g["play"] == "admins" else "") + "Only admins can /play", cb="set:play:admins", style=S if g["play"] == "admins" else P)],
        [btn("🧹 Auto-delete: " + ("On" if g["autodel"] else "Off"), cb="set:autodel:" + ("0" if g["autodel"] else "1"), style=S if g["autodel"] else P)],
        [btn("🗑 Clear queue", cb="set:clear", style=D), btn("✖ Close", cb="set:close", style=P)],
    )
