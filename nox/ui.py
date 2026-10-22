"""Texts and keyboards. All bot-facing text is English, with ꜱᴍᴀʟʟ ᴄᴀᴘꜱ for labels and every button coloured."""
from html import escape as esc

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import config
from .security import encode_room

_SC = str.maketrans("abcdefghijklmnopqrstuvwxyz", "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀsᴛᴜᴠᴡxʏᴢ")


def sc(text):
    """'join room' -> 'ᴊᴏɪɴ ʀᴏᴏᴍ' (emoji and punctuation untouched)."""
    return text.lower().translate(_SC)


def tc(text):
    """'join room' -> 'Jᴏɪɴ Rᴏᴏᴍ' (first letter big, rest small caps; emoji and punctuation untouched)."""
    out = []
    for w in str(text).split(" "):
        if w.startswith("/"):                 # keep /commands plain so Telegram makes them tappable
            out.append(w)
            continue
        i = next((k for k, ch in enumerate(w) if ch.isalpha()), None)
        out.append(w if i is None else w[:i] + w[i].upper() + sc(w[i + 1:]))
    return " ".join(out)


DIV = "★▬▬▬▬▬▬▬▬▬▬▬▬★"


def head(icon_title, status=""):
    """Boxed title line, e.g. <blockquote>🎧 Nᴏx Rᴏᴏᴍ • 🟢 Lɪᴠᴇ</blockquote>"""
    return "<blockquote>" + icon_title + ("  •  " + status if status else "") + "</blockquote>"


P, S, D = "primary", "success", "danger"      # blue, green, red  (the only colours Telegram allows)


def btn(text, cb=None, url=None, style=P, small=True):
    kw = {"text": tc(text) if small else text}
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


def _code(x):
    return f"<code>{x}</code>"


_HINT = "💡 " + _code("/play song name")

WELCOME = (
    head("🎧 <b>" + tc("welcome to sonic nox") + "</b>") + "\n" + DIV + "\n"
    "👋 Hey <b>{name}</b>!\n"
    "🎶 <b>" + tc("live listening rooms for your group") + "</b>\n" + DIV + "\n"
    "1️⃣ <b>" + tc("add me to your group") + "</b>\n"
    "2️⃣ <b>" + tc("make me admin (pin messages)") + "</b>\n"
    "3️⃣ <b>" + tc("send /start to open the room") + "</b>\n"
    "4️⃣ <b>" + tc("queue songs") + "</b> : " + _code("/play song name") + "\n" + DIV + "\n"
    "👥 <b>" + tc("invite friends") + "</b> : /invite\n"
    "🎧 <b>" + tc("everyone hears the same song") + "</b>"
)
HELP = (
    head("📖 <b>" + tc("how it works") + "</b>") + "\n" + DIV + "\n"
    "1️⃣ " + tc("add me & make me admin") + "\n"
    "2️⃣ " + tc("admin sends /start") + "\n"
    "3️⃣ " + tc("anyone adds songs") + " : " + _code("/play song name") + "\n"
    "4️⃣ " + tc("tap join room to listen") + "\n" + DIV + "\n"
    "🎵 <b>" + tc("everyone") + "</b>\n"
    "/play · /queue · /invite · /join · /help\n" + DIV + "\n"
    "🛡 <b>" + tc("admins") + "</b>\n"
    "/skip · /pause · /resume · /loop · /shuffle\n"
    "/autoplay · /clear · /end · /settings\n" + DIV + "\n"
    "💡 <i>Reply to a friend with /invite to call them in.</i>"
)
THANKS = (head("🎉 <b>" + tc("thanks for adding me") + "</b>") + "\n" + DIV + "\n"
          "🛡 " + tc("make me admin with pin messages") + "\n"
          "▶️ " + tc("then send /start to open the room"))


def welcome_kb():
    rows = [[btn("≡ ➕ Add To Group ≡", url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true&admin=pin_messages+delete_messages", style=S)],
            [btn("📖 Help", cb="h", style=P)]]
    if config.SUPPORT_URL:
        rows[1].append(btn("💬 Support", url=config.SUPPORT_URL, style=P))
    return kb(*rows)


def panel_kb(chat_id, room=None):
    paused = bool(room and room.paused)
    loop_on = bool(room and room.loop)
    auto_on = bool(room and room.autoplay)
    return kb(
        [btn("≡ 🎧 Join Room ≡", url=join_url(chat_id), style=P)],
        [btn("▶ Resume" if paused else "⏸ Pause", cb="pp", style=S), btn("⏭ Skip", cb="sk", style=P)],
        [btn("📜 Queue", cb="q", style=P), btn("🔁 Loop", cb="lp", style=S if loop_on else P), btn("🔀 Shuffle", cb="sh", style=P)],
        [btn("♾ Auto", cb="ap", style=S if auto_on else P), btn("📨 Invite", cb="inv", style=S), btn("⚙ More", cb="st", style=P)],
    )


def join_kb(chat_id, label="≡ 🎧 Join Room ≡"):
    return kb([btn(label, url=join_url(chat_id), style=P)])


def _track_lines(t, show_by=True):
    line = f"⏱ {mmss(t.get('dur'))}"
    if show_by and t.get("by"):
        line += f"   👤 <b>{esc(cut(t.get('by'), 24))}</b>"
    return [f"🎵 <b>{esc(cut(t.get('title'), 70))}</b>", f"🎤 {esc(cut(t.get('artist'), 50))}", line]


def panel_caption(room):
    if room is None or room.cur is None:
        return "\n".join([head("🎧 <b>" + tc("nox room") + "</b>", "⚪ <b>" + tc("idle") + "</b>"), DIV,
                           "🎙 <b>" + tc("the stage is empty") + "</b>",
                           tc("queue a song, then tap join room"), DIV, _HINT])
    t = room.cur
    paused = bool(room.paused)
    status = ("⏸ <b>" + tc("paused") + "</b>") if paused else ("🟢 <b>" + tc("live") + "</b>")
    flags = [f"🎧 {len(room.clients)} <b>{tc('listening')}</b>"]
    if room.loop:
        flags.append("🔁 <b>" + tc("loop") + "</b>")
    if room.autoplay:
        flags.append("♾ <b>" + tc("auto") + "</b>")

    def build(n):
        parts = [head("🎧 <b>" + tc("nox room") + "</b>", status), DIV, *_track_lines(t), DIV, "  •  ".join(flags)]
        if room.queue and n:
            q = [f"⏭ <b>{tc('up next')}</b>"]
            q += [f"{i}. {esc(cut(x.get('title'), 38))} — {esc(cut(x.get('artist'), 22))}" for i, x in enumerate(room.queue[:n], 1)]
            if len(room.queue) > n:
                q.append(f"+{len(room.queue) - n} {tc('more')}")
            parts += [DIV, "<blockquote>" + "\n".join(q) + "</blockquote>"]
        parts += [DIV, _HINT]
        return "\n".join(parts)

    for n in (4, 3, 2, 1, 0):                  # drop queue lines (never cut HTML in half) if too long
        text = build(n)
        if len(text) <= 1000:
            return text
    return text


def added_text(t, pos, by=None):
    title = ("▶️ <b>" + tc("starting now") + "</b>") if pos == "start" else (f"➕ <b>{tc('added to queue')}</b>  •  #{pos}")
    return "\n".join([head(title), DIV, *_track_lines(t, show_by=False)] +
                      ([f"👤 {tc('added by')} <b>{esc(cut(by, 24))}</b>"] if by else []) +
                      [DIV, "🎧 <b>" + tc("tap join room to listen") + "</b> 👇"])


def invite_text(name, target=None, track=None):
    who = f"<b>{esc(cut(name, 24))}</b>"
    line = f"👤 {who} is listening" + (f" and invited {target}" if target else " and wants you to join")
    out = [head("📨 <b>" + tc("room invite") + "</b>"), DIV, line]
    if track:
        out += [f"🎵 <b>{esc(cut(track.get('title'), 50))}</b>", f"🎤 {esc(cut(track.get('artist'), 36))}"]
    out += [DIV, "🎧 <b>" + tc("tap join room") + "</b> 👇"]
    return "\n".join(out)


def queue_text(room):
    if room is None or (room.cur is None and not room.queue):
        return "\n".join([head("🎶 <b>" + tc("queue") + "</b>"), DIV, "🎙 <b>" + tc("the stage is empty") + "</b>", _HINT])
    total = len(room.queue) + (1 if room.cur else 0)
    out = [head("🎶 <b>" + tc("queue") + "</b>", f"{total} <b>{tc('tracks')}</b>"), DIV]
    if room.cur:
        out += [("⏸" if room.paused else "▶️") + f" <b>{tc('now playing')}</b>",
                f"🎵 {esc(cut(room.cur.get('title'), 60))} — {esc(cut(room.cur.get('artist'), 36))}", DIV]
    rows = [f"{i}. {esc(cut(q.get('title'), 50))} — {esc(cut(q.get('artist'), 28))}" for i, q in enumerate(room.queue[:15], 1)]
    if rows:
        if len(room.queue) > 15:
            rows.append(f"+{len(room.queue) - 15} {tc('more')}")
        out.append("<blockquote>" + "\n".join(rows) + "</blockquote>")
    return "\n".join(out)


def settings_text(g):
    everyone = g["play"] == "all"
    return "\n".join([head("⚙️ <b>" + tc("group settings") + "</b>"), DIV,
                       f"🎵 <b>{tc('who can /play')}</b> : {'Everyone' if everyone else 'Admins only'}",
                       f"🧹 <b>{tc('auto-delete commands')}</b> : {'On' if g['autodel'] else 'Off'}"])


def settings_kb(g):
    return kb(
        [btn(("✅ " if g["play"] == "all" else "") + "Everyone can /play", cb="set:play:all", style=S if g["play"] == "all" else P)],
        [btn(("✅ " if g["play"] == "admins" else "") + "Only admins can /play", cb="set:play:admins", style=S if g["play"] == "admins" else P)],
        [btn("🧹 Auto-delete: " + ("On" if g["autodel"] else "Off"), cb="set:autodel:" + ("0" if g["autodel"] else "1"), style=S if g["autodel"] else P)],
        [btn("🗑 Clear queue", cb="set:clear", style=D), btn("✖ Close", cb="set:close", style=P)],
    )


def closed_caption():
    return "\n".join([head("🎧 <b>" + tc("nox room") + "</b>", "🔴 <b>" + tc("closed") + "</b>"), DIV,
                       "🌙 <b>" + tc("the room has ended") + "</b>", tc("thanks for listening"), DIV,
                       "▶️ " + tc("admins: send /start to open a new room")])


def ended_text():
    return "\n".join([head("⏹ <b>" + tc("room closed") + "</b>"), DIV, "▶️ " + tc("send /start to open it again")])
