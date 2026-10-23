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
DIVW = "★" + "▬" * 16 + "★"          # wider line for the audio card: makes its bubble as wide as the buttons


def head(icon_title, status=""):
    """Boxed title line, e.g. <blockquote>🎧 Nᴏx Rᴏᴏᴍ • 🟢 Lɪᴠᴇ</blockquote>"""
    return "<blockquote>" + icon_title + ("  •  " + status if status else "") + "</blockquote>"


P, S, D = "primary", "success", "danger"      # blue, green, red  (the only colours Telegram allows)


def spread(label):
    """'pause' -> 'ᴘ ᴀ ᴜ ꜱ ᴇ' with thin spaces, so the label fills the button instead of floating in the middle."""
    return "\u2003".join("\u2009".join(sc(w)) for w in str(label).split(" ") if w)


def wide(text, full=False):
    """'⏸ Pause' -> '⏸ ᴘ ᴀ ᴜ ꜱ ᴇ'. Full-width buttons also get ≡ bars at both ends."""
    parts = str(text).split(" ", 1)
    icon, label = (parts[0], parts[1]) if len(parts) == 2 and not parts[0].isalpha() else ("", str(text))
    core = (icon + " " if icon else "") + spread(label)
    return f"≡ {core} ≡" if full else core


def btn(text, cb=None, url=None, style=P, small=True, fill=None):
    kw = {"text": wide(text, full=(fill == "full")) if fill else (tc(text) if small else text)}
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
    "🎧 <b>" + tc("alone?") + "</b> " + tc("send a song name here in my chat") + "\n"
    "👇 <i>Tap a page below. Tap any command button to see what it does.</i>"
)

# page -> (title, intro, [(icon, command, what it does)])
HELP_PAGES = {
    "all": ("🎵 everyone", "commands for every member", [
        ("🎵", "/play", "add a song to the queue"),
        ("📜", "/queue", "see what plays now and next"),
        ("📨", "/invite", "call friends into the room"),
        ("🎧", "/join", "get the button to enter the live room"),
        ("📖", "/help", "open this guide"),
    ]),
    "adm": ("🛡 admins", "only group admins can use these", [
        ("⏭", "/skip", "jump to the next song"),
        ("⏸", "/pause", "pause the music for everyone"),
        ("▶️", "/resume", "continue the music"),
        ("🔁", "/loop", "repeat the current song"),
        ("🔀", "/shuffle", "mix up the queue"),
        ("♾", "/autoplay", "keep similar songs coming when the queue ends"),
        ("🧹", "/clear", "empty the queue"),
        ("⏹", "/end", "close the room"),
        ("⚙", "/settings", "who can add songs, auto delete and more"),
    ]),
    "me": ("🎧 private player", "listen alone, right here in my chat", [
        ("✍️", "song name", "send any song or artist name"),
        ("📲", "open player", "listen in the mini app"),
        ("🎵", "in chat", "get the song as audio in this chat"),
        ("🎛", "pause · skip · loop · auto", "control it from the player card"),
        ("📜", "queue", "see the songs lined up"),
        ("⏹", "stop", "close your player"),
    ]),
}


def _sent(text):
    """'pause the music' -> 'Pᴀᴜsᴇ ᴛʜᴇ ᴍᴜsɪᴄ' (only the first letter is big)."""
    w = str(text).split(" ", 1)
    return tc(w[0]) + (" " + sc(w[1]) if len(w) > 1 else "")


def help_text(page="home"):
    if page == "home" or page not in HELP_PAGES:
        return HELP
    title, intro, cmds = HELP_PAGES[page]
    icon, name = title.split(" ", 1)
    body = []
    for ic, cmd, desc in cmds:
        c = cmd if cmd.startswith("/") else "<b>" + tc(cmd) + "</b>"
        body.append(f"{ic} {c}\n    ╰ <i>{_sent(desc)}</i>")
    return "\n".join([head(icon + " <b>" + tc(name) + "</b>"), DIV, "✨ <i>" + _sent(intro) + "</i>", DIV] + ["\n".join(body[i:i + 1]) for i in range(len(body))]
                      + [DIV, "💡 " + _sent("tap a page below to switch")])


def help_kb(page="home"):
    """Navigation only: pages (blue / green / blue rows). The page you are on is marked."""
    mark = lambda k, label: label + (" ✔" if page == k else "")
    return kb([btn(mark("all", "🎵 Everyone"), cb="hp:all", style=P, fill="half"), btn(mark("adm", "🛡 Admins"), cb="hp:adm", style=P, fill="half")],
              [btn(mark("me", "🎧 Private Player"), cb="hp:me", style=S, fill="full")],
              [btn("🏠 Back", cb="hb", style=P, fill="full")])


THANKS = (head("🎉 <b>" + tc("thanks for adding me") + "</b>") + "\n" + DIV + "\n"
          "🛡 " + tc("make me admin with pin messages") + "\n"
          "▶️ " + tc("then send /start to open the room"))


def welcome_kb():
    rows = [[btn("≡ ➕ Add To Group ≡", url=f"https://t.me/{config.BOT_USERNAME}?startgroup=true&admin=pin_messages+delete_messages", style=P)],
            [btn("📖 Help", cb="h", style=S)]]
    if config.SUPPORT_URL:
        rows[1].append(btn("💬 Support", url=config.SUPPORT_URL, style=S))
    return kb(*rows)


def _on(label, on):
    return label + (" ✔" if on else "")


def panel_kb(chat_id, room=None):
    """Rows alternate blue / green / blue / green / blue."""
    paused = bool(room and room.paused)
    loop_on = bool(room and room.loop)
    auto_on = bool(room and room.autoplay)
    return kb(
        [btn("🎧 Join Room", url=join_url(chat_id), style=P, fill="full")],
        [btn("▶ Resume" if paused else "⏸ Pause", cb="pp", style=S, fill="half"), btn("⏭ Skip", cb="sk", style=S, fill="half")],
        [btn("📜 Queue", cb="q", style=P, fill="half"), btn(_on("🔁 Loop", loop_on), cb="lp", style=P, fill="half")],
        [btn("🔀 Shuffle", cb="sh", style=S, fill="half"), btn(_on("♾ Auto", auto_on), cb="ap", style=S, fill="half")],
        [btn("📨 Invite", cb="inv", style=P, fill="half"), btn("⚙ More", cb="st", style=P, fill="half")],
    )


def join_kb(chat_id, label="🎧 Join Room"):
    return kb([btn(label, url=join_url(chat_id), style=P, fill="full")])


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


# ---------------- your private player (search in the bot, listen alone in the Mini App) ----------------
_NUM = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣"]


def solo_caption(room, audio=False):
    """The private player card (also the caption of the audio message in chat mode)."""
    if room is None or room.cur is None:
        return "\n".join([head("🎧 <b>" + tc("your player") + "</b>", "⚪ <b>" + tc("idle") + "</b>"), DIV,
                           "🔎 <b>" + tc("send a song name to search") + "</b>", DIV, "💡 " + _code("shape of you")])
    t = room.cur
    DV = DIVW if audio else DIV
    if audio:
        status = "💿 <b>" + tc("in chat") + "</b>"
    else:
        status = ("⏸ <b>" + tc("paused") + "</b>") if room.paused else ("🟢 <b>" + tc("playing") + "</b>")
    lines = [head("🎧 <b>" + tc("your player") + "</b>", status), DV,
             f"🎵 <b>{esc(tc(cut(t.get('title'), 60)))}</b>",
             f"🎤 {esc(tc(cut(t.get('artist'), 44)))}"]
    if t.get("album"):
        lines.append(f"💿 <i>{esc(tc(cut(t.get('album'), 40)))}</i>")
    lines.append(f"⏱ <b>{mmss(t.get('dur'))}</b>")
    if room.queue:
        q = ["⏭ <b>" + tc("up next") + "</b>"] + [f"{i}. {esc(tc(cut(x['title'], 30)))} — {esc(sc(cut(x['artist'], 16)))}" for i, x in enumerate(room.queue[:3], 1)]
        if len(room.queue) > 3:
            q.append(f"+{len(room.queue) - 3} " + sc("more"))
        lines += [DV, "<blockquote>" + "\n".join(q) + "</blockquote>"]
    flags = (["🔁 " + tc("loop")] if room.loop else []) + (["♾ " + tc("auto")] if room.autoplay else [])
    lines += [DV, ("  •  ".join(flags) + "\n" if flags else "") + "🔎 <i>" + _sent("send a song name to add more") + "</i>"]
    text = "\n".join(lines)
    return text if len(text) <= 1000 else text[:990] + "…"


def solo_kb(uid, room=None, audio=False):
    """Blue / green / blue / green rows. Listen in the Mini App (Open Player) or right here in the chat (In Chat)."""
    paused = bool(room and room.paused)
    loop_on = bool(room and room.loop)
    auto_on = bool(room and room.autoplay)
    if audio:                                     # the song itself is in this message, so no pause button
        return kb(
            [btn("📲 Open Player", url=join_url(uid), style=P, fill="half"), btn("📜 Queue", cb="q", style=P, fill="half")],
            [btn("⏭ Next", cb="sk", style=S, fill="half"), btn(_on("🔁 Loop", loop_on), cb="lp", style=S, fill="half")],
            [btn(_on("♾ Auto", auto_on), cb="ap", style=P, fill="half"), btn("⏹ Stop", cb="sx", style=P, fill="half")],
        )
    return kb(
        [btn("📲 Open Player", url=join_url(uid), style=P, fill="half"), btn("🎵 In Chat", cb="sa", style=P, fill="half")],
        [btn("▶ Resume" if paused else "⏸ Pause", cb="pp", style=S, fill="half"), btn("⏭ Skip", cb="sk", style=S, fill="half")],
        [btn("📜 Queue", cb="q", style=P, fill="half"), btn(_on("🔁 Loop", loop_on), cb="lp", style=P, fill="half")],
        [btn(_on("♾ Auto", auto_on), cb="ap", style=S, fill="half"), btn("⏹ Stop", cb="sx", style=S, fill="half")],
    )


def results_text(q, items=()):
    return "\n".join([head("🔎 <b>" + tc("search results") + "</b>"), DIV, f"🎶 <b>{esc(tc(cut(q, 50)))}</b>", DIV,
                      "👇 <i>" + _sent("tap a song to play it") + "</i>"])


def results_kb(items, uid):
    """One song per button, in small caps. Rows alternate blue / green."""
    rows = []
    for i, it in enumerate(items[:8]):
        artist = str(it.get("artist") or "").split(",")[0].strip()
        label = f"🎵 {tc(cut(it['title'], 22))} · {sc(cut(artist, 11))}"
        rows.append([InlineKeyboardButton(text=label, callback_data="ps:" + it["token"], style=P if i % 2 == 0 else S)])
    rows.append([btn("📲 Open Player", url=join_url(uid), style=P if len(rows) % 2 == 0 else S, fill="full")])
    return kb(*rows)


def solo_closed():
    return "\n".join([head("⏹ <b>" + tc("player stopped") + "</b>"), DIV, "Send me a song name whenever you want to listen again."])
