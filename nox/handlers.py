"""Chat commands and buttons (private chat + groups). Every button press is always answered, so nothing feels dead."""
import asyncio
import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, ChatMemberUpdated, FSInputFile, InputMediaPhoto, Message

from . import config, music, state, ui
from .security import clean_text
from .state import bot, cb_rl, cmd_rl, is_admin, penalty, rooms, store

log = logging.getLogger("handlers")
router = Router(name="main")
GROUPS = {"group", "supergroup"}
_banner_id = None


# ---------------- guards ----------------
async def _allowed(uid, chat, reply=None):
    if uid in config.OWNER_IDS:
        return True
    if store.get_kv("maint", False):
        if reply and chat.type == "private":
            await reply("🛠 Sonic Nox is under maintenance. Please try again soon.")
        return False
    if store.is_banned("u", uid) or (chat.id < 0 and store.is_banned("g", chat.id)) or penalty.blocked(uid):
        return False
    if not cmd_rl.allow(uid):
        penalty.strike(uid)
        return False
    return True


async def guard(m: Message):
    return bool(m.from_user) and await _allowed(m.from_user.id, m.chat, m.answer)


async def guard_cb(cb: CallbackQuery):
    """Always answers the tap when it refuses, so the button never spins forever."""
    uid = cb.from_user.id
    if not cb.message:
        await cb.answer("This message is too old. Send /start again.", show_alert=True)
        return False
    if uid in config.OWNER_IDS:
        return True
    if store.get_kv("maint", False):
        await cb.answer("🛠 Under maintenance. Try again soon.", show_alert=True)
        return False
    if store.is_banned("u", uid) or (cb.message.chat.id < 0 and store.is_banned("g", cb.message.chat.id)):
        await cb.answer()
        return False
    if not cb_rl.allow(uid):
        await cb.answer("Easy there, one moment…")
        return False
    return True


async def admin_of(m: Message):
    if m.sender_chat and m.sender_chat.id == m.chat.id:      # anonymous admin
        return True
    return bool(m.from_user) and await is_admin(m.chat.id, m.from_user.id)


async def _autodel(m: Message):
    if store.group(m.chat.id)["autodel"]:
        try:
            await m.delete()
        except TelegramAPIError:
            pass


def _temp(msg, secs=45):
    """Delete a helper message after a while so the group stays clean."""
    async def _go():
        await asyncio.sleep(secs)
        try:
            await msg.delete()
        except TelegramAPIError:
            pass
    rooms.spawn(_go())


async def send_banner(chat_id, caption, markup):
    global _banner_id
    try:
        src = _banner_id or FSInputFile("assets/banner.jpg")
        msg = await bot.send_photo(chat_id, src, caption=caption, reply_markup=markup)
        _banner_id = msg.photo[-1].file_id
        return msg
    except (FileNotFoundError, TelegramBadRequest):
        _banner_id = None
        return await bot.send_message(chat_id, caption, reply_markup=markup)


# ---------------- room message auto-update (debounced): album art + caption + buttons ----------------
_pending = {}
_shown_cover = {}          # chat_id -> cover url currently on the message (None = banner)


def panel_changed(chat_id):
    if chat_id not in _pending:
        _pending[chat_id] = asyncio.get_running_loop().create_task(_update_panel(chat_id))


async def _update_panel(chat_id):
    try:
        await asyncio.sleep(2.0)
        _pending.pop(chat_id, None)
        mid = store.group(chat_id).get("panel")
        if not mid:
            return
        room = rooms.get(chat_id, create=False)
        caption, markup = ui.panel_caption(room), ui.panel_kb(chat_id, room)
        cover = room.cur.get("cover") if room and room.cur else None
        if cover != _shown_cover.get(chat_id) and (cover or _banner_id):
            _shown_cover[chat_id] = cover                      # set first: never retry the same picture in a loop
            try:
                await bot.edit_message_media(chat_id=chat_id, message_id=mid, reply_markup=markup,
                                             media=InputMediaPhoto(media=cover or _banner_id, caption=caption))
                return
            except TelegramBadRequest as e:
                if "not modified" in str(e).lower():
                    return                                       # otherwise fall back to a caption-only edit
        try:
            await bot.edit_message_caption(chat_id=chat_id, message_id=mid, caption=caption, reply_markup=markup)
        except TelegramBadRequest as e:
            s = str(e).lower()
            if "no caption" in s:
                await bot.edit_message_text(caption, chat_id=chat_id, message_id=mid, reply_markup=markup)
            elif "not found" in s or "can't be edited" in s:
                store.set_group(chat_id, panel=None)
    except TelegramBadRequest:
        pass
    except Exception as e:
        log.debug("panel update failed: %s", e)
    finally:
        _pending.pop(chat_id, None)


def on_play(room, track):
    store.inc("plays")


def on_fail(room, track):
    async def _say():
        try:
            await bot.send_message(room.chat_id, f"⚠️ Couldn't load <b>{ui.esc(track['title'][:60])}</b>, skipped.")
        except TelegramAPIError:
            pass
    rooms.spawn(_say())


# ---------------- private chat ----------------
@router.message(CommandStart(), F.chat.type == "private")
async def start_private(m: Message):
    if not await guard(m):
        return
    store.touch_user(m.from_user)
    await send_banner(m.chat.id, ui.WELCOME.format(name=ui.esc(m.from_user.first_name[:30])), ui.welcome_kb())


@router.message(Command("help"))
async def cmd_help(m: Message):
    if await guard(m):
        await m.answer(ui.HELP)


@router.callback_query(F.data == "h")
async def cb_help(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    await cb.answer()
    await cb.message.answer(ui.HELP)


# ---------------- group: open the room ----------------
@router.message(CommandStart(), F.chat.type.in_(GROUPS))
async def start_group(m: Message):
    if not await guard(m):
        return
    store.touch_group(m.chat)
    if not await admin_of(m):
        return await m.reply("🔒 Only group admins can open the room. Ask an admin to send /start.")
    try:
        mine = await bot.get_chat_member(m.chat.id, state.me.id)
    except TelegramAPIError:
        return await m.reply("I can't check my permissions here. Please make me an admin and try again.")
    if mine.status != "administrator" or not getattr(mine, "can_pin_messages", False):
        return await m.reply('Please make me an admin with the "Pin messages" permission, then send /start again.')
    room = rooms.get(m.chat.id)
    if room is None:
        return await m.reply("I'm very busy right now. Please try again in a minute.")
    msg = await send_banner(m.chat.id, ui.panel_caption(room), ui.panel_kb(m.chat.id, room))
    store.set_group(m.chat.id, panel=msg.message_id, dead=False)
    _shown_cover[m.chat.id] = None
    try:
        await bot.pin_chat_message(m.chat.id, msg.message_id, disable_notification=True)
    except TelegramAPIError:
        await m.answer('I couldn\'t pin the message. Please give me the "Pin messages" permission.')
    await _autodel(m)
    if room.cur:
        panel_changed(m.chat.id)


@router.message(Command("join", "room"), F.chat.type.in_(GROUPS))
async def cmd_join(m: Message):
    if not await guard(m):
        return
    if not store.group(m.chat.id)["panel"]:
        return await m.reply("The room isn't open yet. Ask an admin to send /start first.")
    await m.reply("🎧 <b>" + ui.sc("tap to join the room") + "</b>", reply_markup=ui.kb([ui.btn("🎧 Join Room", url=ui.join_url(m.chat.id))]))


@router.message(Command("play"), F.chat.type.in_(GROUPS))
async def cmd_play(m: Message, command: CommandObject):
    if not await guard(m):
        return
    store.touch_group(m.chat)
    g = store.group(m.chat.id)
    if not g["panel"]:
        return await m.reply("The room isn't open yet. Ask an admin to send /start first.")
    if g["play"] == "admins" and not await admin_of(m):
        return await m.reply("🔒 Only admins can add songs in this group.")
    q = clean_text(command.args or "", 80)
    if len(q) < 2:
        return await m.reply("Usage: <code>/play song name</code>")
    results = await music.search(q, 5)
    if not results:
        return await m.reply("😕 No results. Try another name or add the artist.")
    room = rooms.get(m.chat.id)
    if room is None:
        return await m.reply("I'm very busy right now. Please try again in a minute.")
    t = results[0]
    t.update(by=clean_text(m.from_user.first_name if m.from_user else "Admin", 30), by_id=m.from_user.id if m.from_user else 0, src="g")
    pos = room.add(t)
    if pos is None:
        return await m.reply("The queue is full right now.")
    label = "▶ " + ui.sc("starting now") if pos == "start" else f"➕ {ui.sc('added at')} #{pos}"
    await m.reply(f"{label}\n<b>{ui.esc(t['title'][:70])}</b> — <i>{ui.esc(t['artist'][:40])}</i> • {ui.mmss(t['dur'])}\nTap <b>{ui.sc('join room')}</b> on the pinned message to listen.")
    await _autodel(m)


@router.message(Command("queue"), F.chat.type.in_(GROUPS))
async def cmd_queue(m: Message):
    if await guard(m):
        await m.reply(ui.queue_text(rooms.get(m.chat.id, create=False)))


# ---------------- group: admin controls ----------------
async def _ctl(m: Message, fn, txt):
    if not await guard(m):
        return
    if not await admin_of(m):
        return await m.reply("🔒 Only group admins can do this.")
    r = rooms.get(m.chat.id, create=False)
    if r is None or (r.cur is None and fn not in ("clear", "end", "toggle_autoplay")):
        return await m.reply("Nothing is playing right now.")
    r = r or rooms.get(m.chat.id)
    res = await getattr(r, fn)()
    await m.reply(txt(res) if callable(txt) else txt)
    await _autodel(m)


def _make(cmd, fn, txt):
    @router.message(Command(cmd), F.chat.type.in_(GROUPS))
    async def _h(m: Message):
        await _ctl(m, fn, txt)
    return _h


for _c, _f, _t in (("skip", "skip", "⏭ Skipped."), ("pause", "pause", "⏸ Paused."), ("resume", "resume", "▶ Resumed."),
                   ("shuffle", "shuffle", "🔀 Queue shuffled."), ("clear", "clear", "🧹 Queue cleared."),
                   ("end", "end", "⏹ Room stopped."),
                   ("loop", "toggle_loop", lambda on: "🔁 Loop on." if on else "➡ Loop off."),
                   ("autoplay", "toggle_autoplay", lambda on: "♾ Autoplay on, I'll keep similar songs coming." if on else "Autoplay off.")):
    _make(_c, _f, _t)


# ---------------- buttons on the room message ----------------
@router.callback_query(F.data.in_({"pp", "sk", "lp", "sh", "ap", "st"}))
async def cb_panel(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    chat = cb.message.chat
    if chat.type not in GROUPS:
        return await cb.answer()
    if not await is_admin(chat.id, cb.from_user.id):
        return await cb.answer("🔒 Only group admins can use this button.", show_alert=True)
    d = cb.data
    if d == "st":
        g = store.group(chat.id)
        await cb.answer()
        msg = await cb.message.answer(ui.settings_text(g), reply_markup=ui.settings_kb(g))
        return _temp(msg, 120)
    r = rooms.get(chat.id)
    if r is None:
        return await cb.answer("I'm busy right now, try again in a minute.", show_alert=True)
    if d == "ap":
        return await cb.answer("♾ Autoplay on" if await r.toggle_autoplay() else "Autoplay off")
    if r.cur is None:
        return await cb.answer("Nothing is playing right now. Use /play first.", show_alert=True)
    if d == "pp":
        was = r.paused
        await (r.resume() if was else r.pause())
        await cb.answer("▶ Resumed" if was else "⏸ Paused")
    elif d == "sk":
        await r.skip()
        await cb.answer("⏭ Skipped")
    elif d == "lp":
        await cb.answer("🔁 Loop on" if await r.toggle_loop() else "Loop off")
    else:
        await r.shuffle()
        await cb.answer("🔀 Shuffled")


@router.callback_query(F.data == "q")
async def cb_queue(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    await cb.answer()
    _temp(await cb.message.reply(ui.queue_text(rooms.get(cb.message.chat.id, create=False))), 45)


# ---------------- settings (group admins) ----------------
@router.message(Command("settings"), F.chat.type.in_(GROUPS))
async def cmd_settings(m: Message):
    if not await guard(m):
        return
    if not await admin_of(m):
        return await m.reply("🔒 Only group admins can change settings.")
    g = store.group(m.chat.id)
    await m.answer(ui.settings_text(g), reply_markup=ui.settings_kb(g))
    await _autodel(m)


@router.callback_query(F.data.startswith("set:"))
async def cb_settings(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    chat = cb.message.chat
    if chat.type not in GROUPS or not await is_admin(chat.id, cb.from_user.id):
        return await cb.answer("🔒 Only group admins can change settings.", show_alert=True)
    parts = cb.data.split(":")
    if parts[1] == "play" and len(parts) == 3 and parts[2] in ("all", "admins"):
        store.set_group(chat.id, play=parts[2])
    elif parts[1] == "autodel" and len(parts) == 3 and parts[2] in ("0", "1"):
        store.set_group(chat.id, autodel=parts[2] == "1")
    elif parts[1] == "clear":
        r = rooms.get(chat.id, create=False)
        if r:
            await r.clear()
        return await cb.answer("🧹 Queue cleared")
    elif parts[1] == "close":
        try:
            await cb.message.delete()
        except TelegramAPIError:
            pass
        return await cb.answer()
    g = store.group(chat.id)
    try:
        await cb.message.edit_text(ui.settings_text(g), reply_markup=ui.settings_kb(g))
    except TelegramBadRequest:
        pass
    await cb.answer("✅ Saved")


# ---------------- added to / removed from chats ----------------
@router.my_chat_member()
async def my_member(ev: ChatMemberUpdated):
    new, old = ev.new_chat_member.status, ev.old_chat_member.status
    if ev.chat.type in GROUPS:
        if new in ("member", "administrator"):
            if store.is_banned("g", ev.chat.id):
                try:
                    await bot.leave_chat(ev.chat.id)
                except TelegramAPIError:
                    pass
                return
            store.touch_group(ev.chat)
            if old in ("left", "kicked"):
                try:
                    await bot.send_message(ev.chat.id, ui.THANKS)
                except TelegramAPIError:
                    pass
        elif new in ("left", "kicked"):
            store.mark_dead("groups", ev.chat.id)
            store.set_group(ev.chat.id, panel=None)
            rooms.drop(ev.chat.id)
    elif ev.chat.type == "private":
        if new == "kicked":
            store.mark_dead("users", ev.chat.id)
        elif new == "member":
            u = ev.from_user
            if u:
                store.touch_user(u)
