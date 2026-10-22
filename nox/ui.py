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


def cut(text, n):
    """Shorten without breaking words badly; always safe to escape afterwards."""
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _code(s):
    return f"<code>{s}</code>"


WELCOME = (
    "🎧 <b>" + sc("sonic nox") + "</b>\n"
    "<i>" + sc("live listening rooms for your group") + "</i>\n\n"
    "Hey <b>{name}</b>! I turn any group into a live room, so everyone hears the same song at the same moment.\n\n"
    "<blockquote>1️⃣  Add me to your group as admin\n"
    "2️⃣  Send /start there to open the room\n"
    "3️⃣  Queue songs with <code>/play song name</code></blockquote>\n"
    "Tap <b>" + sc("add to group") + "</b> to begin 👇"
)
HELP = (
    "📖 <b>" + sc("how it works") + "</b>\n"
    "<blockquote>1. Add me to your group and make me admin (Pin messages).\n"
    "2. An admin sends /start and I post the room.\n"
    "3. Anyone adds songs with <code>/play song name</code>.\n"
    "4. Tap <b>" + sc("join room") + "</b> to listen together.</blockquote>\n"
    "🎵 <b>" + sc("everyone") + "</b>\n"
    "/play · /queue · /invite · /join · /help\n\n"
    "🛡 <b>" + sc("admins") + "</b>\n"
    "/skip · /pause · /resume · /loop · /shuffle\n"
    "/autoplay · /clear · /end · /settings\n\n"
    "<i>Tip: reply to a friend's message with /invite to call them into the room.</i>"
)
THANKS = ("🎉 <b>" + sc("thanks for adding me") + "</b>\n"
          "<blockquote>Make me an admin with \"Pin messages\", then send /start to open the room.</blockquote>")


def welcome_kb():
    rows = [[btn("➕ Add to Group", url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true&admin=pin_messages+delete_messages", style=S)],
            [btn("📖 Help", cb="h", style=P)]]
    if config.SUPPORT_URL:
        rows[1].append(btn("💬 Support", url=config.SUPPORT_URL, style=P))
    return kb(*rows)


def panel_kb(chat_id, room=None):
    paused = bool(room and room.paused)
    loop_on = bool(room and room.loop)
    auto_on = bool(room and room.autoplay)
    return kb(
        [btn("🎧 Join Room", url=join_url(chat_id), style=P)],
        [btn("▶ Resume" if paused else "⏸ Pause", cb="pp", style=S), btn("⏭ Skip", cb="sk", style=P)],
        [btn("📜 Queue", cb="q", style=P), btn("🔁 Loop", cb="lp", style=S if loop_on else P), btn("🔀 Shuffle", cb="sh", style=P)],
        [btn("♾ Auto", cb="ap", style=S if auto_on else P), btn("📨 Invite", cb="inv", style=S), btn("⚙ Settings", cb="st", style=P)],
    )


def join_kb(chat_id, label="🎧 Join Room"):
    return kb([btn(label, url=join_url(chat_id), style=P)])


_HINT = "💡 " + _code("/play song name")


def panel_caption(room):
    if room is None or room.cur is None:
        return (f"🎧 <b>{sc('nox room')}</b>  •  ⚪ <i>{sc('idle')}</i>\n\n"
                "Nothing is playing yet.\n"
                f"Queue a song, then tap <b>{sc('join room')}</b> to listen together.\n\n"
                f"{_HINT}")
    t = room.cur
    paused = bool(room.paused)
    status = f"⏸ <i>{sc('paused')}</i>" if paused else f"🟢 <i>{sc('live')}</i>"
    flags = []
    if room.loop:
        flags.append(f"🔁 {sc('loop')}")
    if room.autoplay:
        flags.append(f"♾ {sc('auto')}")
    stats = f"🎧 {len(room.clients)} {sc('listening')}" + ("  ·  " + "  ·  ".join(flags) if flags else "")

    def build(n_queue):
        parts = [f"🎧 <b>{sc('nox room')}</b>  •  {status}", "",
                 f"{'⏸' if paused else '▶️'} <b>{esc(cut(t.get('title'), 70))}</b>",
                 f"<i>{esc(cut(t.get('artist'), 50))}</i>  ·  {mmss(t.get('dur'))}", "",
                 f"👤 {sc('added by')} <b>{esc(cut(t.get('by') or 'someone', 28))}</b>",
                 stats]
        if room.queue and n_queue:
            q = [f"<b>{sc('up next')}</b>"]
            for i, x in enumerate(room.queue[:n_queue], 1):
                q.append(f"{i}. {esc(cut(x.get('title'), 38))} — <i>{esc(cut(x.get('artist'), 22))}</i>")
            more = len(room.queue) - n_queue
            if more > 0:
                q.append(f"+{more} {sc('more')}")
            parts += ["", "<blockquote>" + "\n".join(q) + "</blockquote>"]
        parts += ["", _HINT]
        return "\n".join(parts)

    for n in (4, 3, 2, 1, 0):                  # drop queue lines (never cut HTML in half) if too long
        text = build(n)
        if len(text) <= 1000:
            return text
    return text


def added_text(t, pos, by=None):
    head = f"▶️ <b>{sc('starting now')}</b>" if pos == "start" else f"➕ <b>{sc('added to queue')}</b>  ·  #{pos}"
    out = [head, "", f"<b>{esc(cut(t.get('title'), 70))}</b>",
           f"<i>{esc(cut(t.get('artist'), 40))}</i>  ·  {mmss(t.get('dur'))}"]
    if by:
        out += ["", f"👤 {sc('added by')} <b>{esc(cut(by, 28))}</b>"]
    out += ["", f"Tap <b>{sc('join room')}</b> to listen 👇"]
    return "\n".join(out)


def invite_text(name, target=None, track=None):
    who = f"<b>{esc(cut(name, 28))}</b>"
    line = f"{who} is listening and wants you to join." if not target else f"{who} invited {target} to listen together."
    out = [f"📨 <b>{sc('room invite')}</b>", "", line]
    if track:
        out += ["", f"▶️ <b>{esc(cut(track.get('title'), 50))}</b>", f"<i>{esc(cut(track.get('artist'), 36))}</i>"]
    out += ["", f"Tap <b>{sc('join room')}</b> 👇"]
    return "\n".join(out)


def queue_text(room):
    if room is None or (room.cur is None and not room.queue):
        return f"🎶 <b>{sc('queue')}</b>\n\nIt's quiet here. Add a song with {_code('/play song name')}."
    total = len(room.queue) + (1 if room.cur else 0)
    out = [f"🎶 <b>{sc('queue')}</b>  •  {total} {sc('tracks')}", ""]
    if room.cur:
        out += [f"{'⏸' if room.paused else '▶️'} <b>{sc('now playing')}</b>",
                f"<b>{esc(cut(room.cur.get('title'), 60))}</b> — <i>{esc(cut(room.cur.get('artist'), 36))}</i>", ""]
    rows = [f"{i}. {esc(cut(q.get('title'), 50))} — <i>{esc(cut(q.get('artist'), 28))}</i>" for i, q in enumerate(room.queue[:15], 1)]
    if rows:
        out.append("<blockquote>" + "\n".join(rows) + "</blockquote>")
    if len(room.queue) > 15:
        out.append(f"+{len(room.queue) - 15} {sc('more')}")
    return "\n".join(out)


def settings_text(g):
    everyone = g["play"] == "all"
    return (f"⚙️ <b>{sc('group settings')}</b>\n\n"
            f"🎵 {sc('who can /play')}\n<b>{'Everyone' if everyone else 'Admins only'}</b>\n\n"
            f"🧹 {sc('auto-delete commands')}\n<b>{'On' if g['autodel'] else 'Off'}</b>")


def settings_kb(g):
    return kb(
        [btn(("✅ " if g["play"] == "all" else "") + "Everyone can /play", cb="set:play:all", style=S if g["play"] == "all" else P)],
        [btn(("✅ " if g["play"] == "admins" else "") + "Only admins can /play", cb="set:play:admins", style=S if g["play"] == "admins" else P)],
        [btn("🧹 Auto-delete: " + ("On" if g["autodel"] else "Off"), cb="set:autodel:" + ("0" if g["autodel"] else "1"), style=S if g["autodel"] else P)],
        [btn("🗑 Clear queue", cb="set:clear", style=D), btn("✖ Close", cb="set:close", style=P)],
    )
