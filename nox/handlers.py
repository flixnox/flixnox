"""Chat commands and buttons (private chat + groups). Every button press is always answered, so nothing feels dead."""
import asyncio
import logging
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, ChatMemberUpdated, FSInputFile, InputMediaAudio, InputMediaPhoto, Message

from . import config, moviebox, music, state, ui
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


async def send_banner(chat_id, caption, markup, spoiler=True, photo=None):
    """Picture + caption + buttons. The picture is hidden behind a spoiler until someone taps it."""
    global _banner_id
    if photo:
        try:
            return await bot.send_photo(chat_id, photo, caption=caption, reply_markup=markup, has_spoiler=spoiler)
        except TelegramAPIError:
            pass                                          # cover not reachable: fall back to the banner
    try:
        src = _banner_id or FSInputFile("assets/banner.jpg")
        msg = await bot.send_photo(chat_id, src, caption=caption, reply_markup=markup, has_spoiler=spoiler)
        _banner_id = msg.photo[-1].file_id
        return msg
    except (FileNotFoundError, TelegramBadRequest):
        _banner_id = None
        return await bot.send_message(chat_id, caption, reply_markup=markup)


# ---------------- room message auto-update (debounced): album art + caption + buttons ----------------
_pending = {}
_solo = {}                 # user id -> message id of their private player card
_solo_kind = {}            # user id -> "audio" (the card IS the song, one music message) or missing (photo card)
_solo_key = {}             # user id -> which song the audio card holds
_audio_fid = {}            # song key -> Telegram file_id (re-sending is then instant)
_shown_cover = {}          # chat_id -> cover url currently on the message (None = banner)


def panel_changed(chat_id):
    if chat_id not in _pending:
        _pending[chat_id] = asyncio.get_running_loop().create_task(_update_panel(chat_id))


async def _update_panel(chat_id, delay=2.0):
    try:
        if delay:
            await asyncio.sleep(delay)
        _pending.pop(chat_id, None)
        solo = chat_id > 0                                     # a private player, not a group room
        mid = _solo.get(chat_id) if solo else store.group(chat_id).get("panel")
        if not mid:
            return
        room = rooms.get(chat_id, create=False)
        audio = solo and _solo_kind.get(chat_id) == "audio"
        if audio:
            cap, kbd = ui.solo_caption(room, True), ui.solo_kb(chat_id, room, True)
            if room is not None and room.cur is not None and room.url and _tkey(room.cur) != _solo_key.get(chat_id):
                if await edit_audio_card(chat_id, mid, room, cap, kbd) is None:     # the same message turns into the next song
                    await send_audio_card(chat_id, room)
                return
            try:
                await bot.edit_message_caption(chat_id=chat_id, message_id=mid, caption=cap, reply_markup=kbd)
            except TelegramBadRequest as e:
                if "not modified" not in str(e).lower():
                    _solo.pop(chat_id, None)
            return
        caption = ui.solo_caption(room, audio) if solo else ui.panel_caption(room)
        markup = ui.solo_kb(chat_id, room, audio) if solo else ui.panel_kb(chat_id, room)
        cover = room.cur.get("cover") if room and room.cur else None
        if cover != _shown_cover.get(chat_id) and (cover or _banner_id):
            _shown_cover[chat_id] = cover                      # set first: never retry the same picture in a loop
            try:
                await bot.edit_message_media(chat_id=chat_id, message_id=mid, reply_markup=markup,
                                             media=InputMediaPhoto(media=cover or _banner_id, caption=caption, has_spoiler=True))
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
                if solo:
                    _solo.pop(chat_id, None)
                else:
                    store.set_group(chat_id, panel=None)
    except TelegramBadRequest:
        pass
    except Exception as e:
        log.debug("panel update failed: %s", e)
    finally:
        _pending.pop(chat_id, None)


# ---------------- tidy chat: a request's messages disappear once its song is on air ----------------
_qmsgs = {}                # chat_id -> message ids of /queue replies (stale as soon as the song changes)


def _delete_msgs(chat_id, ids, delay=0):
    if not ids:
        return

    async def _go():
        if delay:
            await asyncio.sleep(delay)
        for mid in ids:
            try:
                await bot.delete_message(chat_id, mid)
            except TelegramAPIError:
                pass                                   # no delete right, or already gone
    rooms.spawn(_go())


def on_play(room, track):
    store.inc("plays")
    _delete_msgs(room.chat_id, _qmsgs.pop(room.chat_id, []))
    track["started"] = True
    _delete_msgs(room.chat_id, track.pop("msgs", []), 20 if track.get("instant") else 0)


def on_drop(room, track):
    _delete_msgs(room.chat_id, track.pop("msgs", []))


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
    await send_banner(m.chat.id, ui.WELCOME.format(name=ui.esc(m.from_user.first_name[:30])), ui.welcome_kb(), spoiler=True)


async def _edit_card(cb, text, markup):
    """Edit the message the button sits on (photo caption or plain text) instead of sending a new one."""
    try:
        if cb.message.photo:
            await cb.message.edit_caption(caption=text, reply_markup=markup)
        else:
            await cb.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            await cb.message.answer(text, reply_markup=markup)


@router.message(Command("help"))
async def cmd_help(m: Message):
    if await guard(m):
        await m.answer(ui.help_text(), reply_markup=ui.help_kb())


@router.callback_query(F.data == "h")
async def cb_help(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    await cb.answer()
    await _edit_card(cb, ui.help_text(), ui.help_kb())


@router.callback_query(F.data.startswith("hp:"))
async def cb_help_page(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    page = cb.data[3:]
    await cb.answer()
    await _edit_card(cb, ui.help_text(page), ui.help_kb(page))


@router.callback_query(F.data == "hb")
async def cb_help_back(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    await cb.answer()
    if cb.message.chat.type == "private":
        return await _edit_card(cb, ui.WELCOME.format(name=ui.esc(cb.from_user.first_name[:30])), ui.welcome_kb())
    try:
        await cb.message.delete()
    except TelegramAPIError:
        pass


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
    msg = await send_banner(m.chat.id, ui.panel_caption(room), ui.panel_kb(m.chat.id, room), spoiler=True)
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
    await m.reply("🎧 <b>" + ui.tc("tap to join the room") + "</b>", reply_markup=ui.join_kb(m.chat.id))


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
    reply = await m.reply(ui.added_text(t, pos, t["by"]), reply_markup=ui.join_kb(m.chat.id))
    await _autodel(m)
    msgs = [reply.message_id] + ([] if store.group(m.chat.id)["autodel"] else [m.message_id])
    t["instant"] = pos == "start"
    if t.get("started"):
        _delete_msgs(m.chat.id, msgs, 20 if t["instant"] else 0)
    else:
        t["msgs"] = msgs                                  # removed when this song starts playing


@router.message(Command("queue"), F.chat.type.in_(GROUPS))
async def cmd_queue(m: Message):
    if await guard(m):
        r = await m.reply(ui.queue_text(rooms.get(m.chat.id, create=False)))
        ids = _qmsgs.setdefault(m.chat.id, [])
        ids[:] = (ids + [r.message_id, m.message_id])[-20:]


# ---------------- MovieBox: /search + detail + episode + download (group) ----------------
_mb_last_results = {}   # user_id -> list of normalised movie dicts (for "back to results")


@router.message(Command("search"), F.chat.type.in_(GROUPS))
async def cmd_movie_search(m: Message, command: CommandObject):
    if not await guard(m):
        return
    q = clean_text(command.args or "", 80)
    if len(q) < 2:
        t = await m.reply("Usage: <code>/search movie name</code>")
        _temp(t)
        return
    wait = await m.reply("🔎 Searching…")
    results = await moviebox.search(q, limit=8)
    try:
        await wait.delete()
    except TelegramAPIError:
        pass
    if not results:
        t = await m.reply("😕 No movies found. Try a different title.")
        _temp(t)
        return
    uid = m.from_user.id
    # stash each result and attach token for secure callbacks
    for r in results:
        r["token"] = moviebox.stash(uid, r)
    _mb_last_results[uid] = results
    t = await m.reply(
        ui.moviebox_results_text(q),
        reply_markup=ui.moviebox_results_kb(results, uid),
    )
    _temp(t, secs=300)   # results live 5 minutes then auto-delete
    await _autodel(m)


@router.callback_query(F.data.startswith("mb:"))
async def cb_movie_detail(cb: CallbackQuery):
    """User tapped a search-result button → show full detail in group."""
    if not await guard_cb(cb):
        return
    await cb.answer()
    token = cb.data[3:]
    uid   = cb.from_user.id
    hit   = moviebox.take(token, uid)
    if not hit:
        await cb.answer("This result has expired. Search again.", show_alert=True)
        return
    wait = await cb.message.answer("⏳ Loading…")
    movie = await moviebox.details(hit["id"])
    if not movie:
        movie = hit               # fallback: use the search-result data we already have
    eps = []
    mtype = (movie.get("type") or "").lower()
    if any(k in mtype for k in ("series", "tv", "show")):
        eps = await moviebox.episodes(hit["id"])
    try:
        await wait.delete()
    except TelegramAPIError:
        pass
    # stash the full detail so download/episode callbacks can retrieve it safely
    movie["token"] = moviebox.stash(uid, movie)
    for ep in eps:
        ep["token"] = moviebox.stash_ep(uid, ep)

    await send_banner(
        cb.message.chat.id,
        ui.moviebox_detail_text(movie),
        ui.moviebox_detail_kb(movie, eps),
        spoiler=False,
        photo=movie.get("poster"),
    )


@router.callback_query(F.data.startswith("mbp:"))
async def cb_movie_ep_page(cb: CallbackQuery):
    """Paginate episode list: mbp:{movie_id}:{page}"""
    if not await guard_cb(cb):
        return
    await cb.answer()
    parts = cb.data[4:].rsplit(":", 1)
    if len(parts) != 2:
        return
    movie_id, page_str = parts
    try:
        page = int(page_str)
    except ValueError:
        return
    uid = cb.from_user.id
    eps   = await moviebox.episodes(movie_id)
    movie = await moviebox.details(movie_id)
    if not movie:
        return
    movie["token"] = moviebox.stash(uid, movie)
    for ep in eps:
        ep["token"] = moviebox.stash_ep(uid, ep)
    try:
        if cb.message.photo:
            await cb.message.edit_caption(
                caption=ui.moviebox_detail_text(movie),
                reply_markup=ui.moviebox_detail_kb(movie, eps, page),
            )
        else:
            await cb.message.edit_reply_markup(reply_markup=ui.moviebox_detail_kb(movie, eps, page))
    except TelegramBadRequest:
        pass


@router.callback_query(F.data == "mbr")
async def cb_movie_back(cb: CallbackQuery):
    """Back to the previous results list."""
    if not await guard_cb(cb):
        return
    await cb.answer()
    uid     = cb.from_user.id
    results = _mb_last_results.get(uid)
    if not results:
        try:
            await cb.message.delete()
        except TelegramAPIError:
            pass
        return
    # re-stash so tokens are fresh
    for r in results:
        r["token"] = moviebox.stash(uid, r)
    try:
        if cb.message.photo:
            await cb.message.delete()
        else:
            await cb.message.edit_text(
                ui.moviebox_results_text(""),
                reply_markup=ui.moviebox_results_kb(results, uid),
            )
    except TelegramAPIError:
        pass
    await cb.message.answer(
        ui.moviebox_results_text("your recent search"),
        reply_markup=ui.moviebox_results_kb(results, uid),
    )


@router.callback_query(F.data.startswith("mbd:"))
async def cb_movie_download(cb: CallbackQuery):
    """Download button on a plain movie → DM the user the stream link."""
    if not await guard_cb(cb):
        return
    await cb.answer()
    token = cb.data[4:]
    uid   = cb.from_user.id
    movie = moviebox.take(token, uid)
    if not movie:
        await cb.answer("Link expired. Open the detail again.", show_alert=True)
        return
    await _send_movie_to_pvt(cb, uid, movie)


@router.callback_query(F.data.startswith("mbe:"))
async def cb_episode_download(cb: CallbackQuery):
    """Download button on an episode → DM the user."""
    if not await guard_cb(cb):
        return
    await cb.answer()
    token = cb.data[4:]
    uid   = cb.from_user.id
    ep    = moviebox.take_ep(token, uid)
    if not ep:
        await cb.answer("Link expired. Open the detail again.", show_alert=True)
        return
    # retrieve the parent movie title from stash via movie detail
    movie = {"title": "Series", "type": "series"}   # fallback; detail lookup is optional
    await _send_movie_to_pvt(cb, uid, movie, ep=ep)


async def _send_movie_to_pvt(cb: CallbackQuery, uid: int, movie: dict, ep=None):
    """DM the user their stream link; show a brief in-group notice."""
    stream_url = None
    if ep:
        stream_url = ep.get("url") or ""
    else:
        streams = movie.get("streams") or []
        if streams:
            first = streams[0]
            stream_url = (first.get("url") or first.get("link") or first) if isinstance(first, dict) else str(first)

    caption = ui.moviebox_pvt_text(movie, ep)
    try:
        if stream_url:
            await bot.send_message(
                uid,
                caption + f'\n\n<a href="{ui.esc(str(stream_url))}">⬇ Click here to download / stream</a>',
                disable_web_page_preview=False,
            )
        else:
            # no direct stream URL in API data — send the detail page URL instead
            detail_url = f"{config.MOVIEBOX_BASE}/movie/{movie.get('id', '')}"
            await bot.send_message(
                uid,
                caption + f'\n\n<a href="{ui.esc(detail_url)}">🎬 Open on MovieBox</a>',
                disable_web_page_preview=False,
            )
        # brief notice in the group (auto-deleted)
        name = ui.esc(cb.from_user.first_name[:24] if cb.from_user.first_name else "")
        notice = await cb.message.answer(
            f"📨 {name}, check your private chat — I sent the download link there!"
        )
        _temp(notice, secs=30)
    except TelegramAPIError as e:
        if "bot was blocked" in str(e).lower() or "chat not found" in str(e).lower() or "forbidden" in str(e).lower():
            bot_link = f"https://t.me/{config.BOT_USERNAME}?start=dl"
            notice = await cb.message.answer(
                f"⚠️ <a href='{bot_link}'>Start me in private first</a>, then tap Download again.",
                disable_web_page_preview=True,
            )
            _temp(notice, secs=60)
        else:
            raise


# ---------------- invite: anyone in the room can call the rest of the group ----------------
_inv_last = {}             # chat_id -> monotonic time of the last invite (stops spam)
INVITE_COOLDOWN = 90


async def invite_group(chat_id, name, target=None):
    """Posts one invite message with a Join Room button. Returns the message, or None when on cooldown.
    Used by the chat button, /invite and the Mini App (which has already checked membership)."""
    now = time.monotonic()
    if now - _inv_last.get(chat_id, -1e9) < INVITE_COOLDOWN:
        return None
    _inv_last[chat_id] = now
    room = rooms.get(chat_id, create=False)
    try:
        msg = await bot.send_message(chat_id, ui.invite_text(clean_text(name or "Someone", 30), target, room.cur if room else None),
                                     reply_markup=ui.join_kb(chat_id))
    except TelegramAPIError:
        _inv_last.pop(chat_id, None)
        return None
    _temp(msg, 300)
    return msg


@router.message(Command("invite"), F.chat.type.in_(GROUPS))
async def cmd_invite(m: Message):
    if not await guard(m):
        return
    if not store.group(m.chat.id)["panel"]:
        return await m.reply("The room isn't open yet. Ask an admin to send /start first.")
    target = None
    rp = m.reply_to_message
    if rp and rp.from_user and not rp.from_user.is_bot and rp.from_user.id != m.from_user.id:
        target = f'<a href="tg://user?id={rp.from_user.id}">{ui.esc(clean_text(rp.from_user.first_name or "friend", 30))}</a>'
    if await invite_group(m.chat.id, m.from_user.first_name, target) is None:
        _temp(await m.reply("📨 An invite was just sent. Please wait a moment before sending another."), 15)
    await _autodel(m)


@router.callback_query(F.data == "inv")
async def cb_invite(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    chat = cb.message.chat
    if chat.type not in GROUPS:
        return await cb.answer()
    if await invite_group(chat.id, cb.from_user.first_name) is None:
        return await cb.answer("📨 An invite was just sent. Try again in a minute.", show_alert=True)
    await cb.answer("📨 Invite sent to the group")


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



@router.message(Command("vplay"), F.chat.type.in_(GROUPS))
async def cmd_vplay(m: Message, command: CommandObject):
    if not await guard(m):
        return
    store.touch_group(m.chat)
    g = store.group(m.chat.id)
    if not g["panel"]:
        return await m.reply("The room isn't open yet. Ask an admin to send /start first.")
    if g["play"] == "admins" and not await admin_of(m):
        return await m.reply("🔒 Only admins can add videos in this group.")
    q = clean_text(command.args or "", 80)
    if len(q) < 2:
        return await m.reply("Usage: <code>/vplay video name</code>")
    
    # Force YouTube search for videos
    results = await music._yt_search(q, 1)
    if not results:
        return await m.reply("😕 No videos found on YouTube.")
        
    room = rooms.get(m.chat.id)
    if room is None:
        return await m.reply("I'm very busy right now. Please try again in a minute.")
        
    t = results[0]
    t.update(by=clean_text(m.from_user.first_name if m.from_user else "Admin", 30), by_id=m.from_user.id if m.from_user else 0, src="g")
    
    pos = room.add(t)
    if pos is None:
        return await m.reply("The queue is full right now.")
    reply = await m.reply(ui.added_text(t, pos, t["by"]), reply_markup=ui.join_kb(m.chat.id))
    await _autodel(m)
    msgs = [reply.message_id] + ([] if store.group(m.chat.id)["autodel"] else [m.message_id])
    t["instant"] = pos == "start"
    if t.get("started"):
        _delete_msgs(m.chat.id, msgs, 20 if t["instant"] else 0)
    else:
        t["msgs"] = msgs


for _c, _f, _t in (("skip", "skip", "⏭ Skipped."), ("pause", "pause", "⏸ Paused."), ("resume", "resume", "▶ Resumed."),
                   ("shuffle", "shuffle", "🔀 Queue shuffled."), ("clear", "clear", "🧹 Queue cleared."),
                   ("loop", "toggle_loop", lambda on: "🔁 Loop on." if on else "➡ Loop off."),
                   ("autoplay", "toggle_autoplay", lambda on: "♾ Autoplay on, I'll keep similar songs coming." if on else "Autoplay off.")):
    _make(_c, _f, _t)


# ---------------- /end: the room lives from /start until an admin ends it ----------------
async def close_solo(uid):
    """Stop button in a private chat: music stops, the Mini App closes, the card says so."""
    room = rooms.get(uid, create=False)
    mid = _solo.pop(uid, None)
    _solo_kind.pop(uid, None)
    _solo_key.pop(uid, None)
    if room is not None:
        await room.end()
        for c in list(room.clients.values()):
            await c.send({"t": "fatal", "m": "Your player was stopped. Send a song name to the bot to start again."})
            await c.close()
        rooms.drop(uid)
    _shown_cover.pop(uid, None)
    if mid:
        try:
            await bot.edit_message_caption(chat_id=uid, message_id=mid, caption=ui.solo_closed(), reply_markup=None)
        except TelegramAPIError:
            pass


async def close_room(chat_id):
    if chat_id > 0:
        return await close_solo(chat_id)
    mid = store.group(chat_id).get("panel")
    room = rooms.get(chat_id, create=False)
    store.set_group(chat_id, panel=None)                  # first: /play and new joins are refused from now on
    if room is not None:
        await room.end()
        for c in list(room.clients.values()):
            await c.send({"t": "fatal", "m": "The room was ended by an admin."})
            await c.close()
        rooms.drop(chat_id)
    _qmsgs.pop(chat_id, None)
    if mid:
        try:
            await bot.edit_message_caption(chat_id=chat_id, message_id=mid, caption=ui.closed_caption(), reply_markup=None)
        except TelegramBadRequest:
            try:
                await bot.edit_message_text(ui.closed_caption(), chat_id=chat_id, message_id=mid, reply_markup=None)
            except TelegramAPIError:
                pass
        except TelegramAPIError:
            pass
        try:
            await bot.unpin_chat_message(chat_id, mid)
        except TelegramAPIError:
            pass


@router.message(Command("end"), F.chat.type.in_(GROUPS))
async def cmd_end(m: Message):
    if not await guard(m):
        return
    if not await admin_of(m):
        return await m.reply("🔒 Only group admins can do this.")
    if not store.group(m.chat.id)["panel"]:
        return await m.reply("The room isn't open. Send /start to open it.")
    await close_room(m.chat.id)
    await m.reply(ui.ended_text())
    await _autodel(m)


# ---------------- buttons on the room message ----------------
@router.callback_query(F.data.in_({"pp", "sk", "lp", "sh", "ap", "st", "sx"}))
async def cb_panel(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    chat = cb.message.chat
    solo = chat.type == "private"
    if chat.type not in GROUPS and not solo:
        return await cb.answer()
    if not solo and not await is_admin(chat.id, cb.from_user.id):
        return await cb.answer("🔒 Only group admins can use this button.", show_alert=True)
    d = cb.data
    if d == "sx":
        if not solo:
            return await cb.answer()
        await close_solo(chat.id)
        return await cb.answer("⏹ Stopped")
    if d == "st":
        if solo:
            return await cb.answer()
        g = store.group(chat.id)
        await cb.answer()
        msg = await cb.message.answer(ui.settings_text(g), reply_markup=ui.settings_kb(g))
        return _temp(msg, 120)
    r = rooms.get(chat.id, create=False) if solo else rooms.get(chat.id)
    if r is None:
        return await cb.answer("Your player isn't running. Send a song name to start it." if solo else "I'm busy right now, try again in a minute.", show_alert=True)
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
    r = await cb.message.reply(ui.queue_text(rooms.get(cb.message.chat.id, create=False)))
    ids = _qmsgs.setdefault(cb.message.chat.id, [])
    ids[:] = (ids + [r.message_id])[-20:]
    _temp(r, 45)


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


# ---------------- private chat: search songs here, listen alone in your own Mini App ----------------
async def private_search(m: Message, q: str):
    q = clean_text(q or "", 80)
    if len(q) < 2:
        return await m.answer("🔎 <b>" + ui.tc("send me a song or artist name") + "</b>\n<i>For example:</i> <code>kesariya</code>")
    songs = await music.search(q, 8)
    if not songs:
        return await m.answer("😕 No results. Try the artist name too.")
    items = music.stash(m.from_user.id, songs)
    await m.answer(ui.results_text(q, items), reply_markup=ui.results_kb(items, m.from_user.id))


async def cmd_play_private(m: Message, command: CommandObject):
    if await guard(m):
        store.touch_user(m.from_user)
        await private_search(m, command.args)


async def text_private(m: Message):
    if await guard(m):
        store.touch_user(m.from_user)
        await private_search(m, m.text)


async def send_solo_card(uid, room, cover):
    """One player card, always the newest message: old one is removed, the new one shows the album art."""
    old = _solo.pop(uid, None)
    if old:
        try:
            await bot.delete_message(uid, old)
        except TelegramAPIError:
            pass
    audio = _solo_kind.get(uid) == "audio"
    msg = await send_banner(uid, ui.solo_caption(room, audio), ui.solo_kb(uid, room, audio), spoiler=True, photo=cover)
    _solo[uid] = msg.message_id
    _shown_cover[uid] = cover if msg.photo and cover else None


def _tkey(t):
    return (t.get("sid") or "") + "|" + (t.get("title") or "")


async def _fetch(url, limit, timeout=40):
    try:
        r = await music.client().get(url, timeout=timeout)
        if r.status_code == 200 and 1000 < len(r.content) < limit:
            return r.content
    except Exception as e:
        log.debug("fetch failed: %s", e)
    return None


async def _audio_source(t, url):
    """(file to send, cover thumbnail). A remembered file_id is instant; otherwise the song is downloaded and uploaded."""
    key = _tkey(t)
    if key in _audio_fid:
        return _audio_fid[key], None
    data = await _fetch(url, 45_000_000)
    if not data:
        return url, None                                         # last resort: let Telegram fetch the link
    ext = ".mp3" if url.split("?")[0].lower().endswith(".mp3") else ".m4a"
    name = ("".join(c for c in (t.get("title") or "song") if c.isalnum() or c in " -_")[:40].strip() or "song") + ext
    thumb = None
    if t.get("cover"):
        img = await _fetch(t["cover"], 200_000, 8)
        thumb = BufferedInputFile(img, filename="cover.jpg") if img else None
    return BufferedInputFile(data, filename=name), thumb


def _remember(t, msg):
    audio = getattr(msg, "audio", None)
    if audio:
        if len(_audio_fid) > 300:
            _audio_fid.pop(next(iter(_audio_fid)))
        _audio_fid[_tkey(t)] = audio.file_id


def _audio_meta(t):
    return dict(title=(t.get("title") or "")[:64], performer=(t.get("artist") or "")[:64], duration=int(t.get("dur") or 0) or None)


async def send_audio_card(uid, room):
    """Chat mode: ONE message that is the song itself (Telegram's own music player) with the caption and buttons under it.
    It replaces the photo card; the next song replaces the song inside this same message."""
    t, url = room.cur, room.url
    if t is None or not url:
        return None
    try:
        await bot.send_chat_action(uid, "upload_voice")
        src, thumb = await _audio_source(t, url)
        kw = dict(caption=ui.solo_caption(room, True), reply_markup=ui.solo_kb(uid, room, True), **_audio_meta(t))
        try:
            msg = await bot.send_audio(uid, src, thumbnail=thumb, **kw)
        except TelegramBadRequest:
            msg = await bot.send_audio(uid, src, **kw)
    except TelegramAPIError as e:
        log.warning("audio send failed: %s", e)
        return None
    _remember(t, msg)
    old = _solo.get(uid)
    _solo[uid], _solo_kind[uid], _solo_key[uid] = msg.message_id, "audio", _tkey(t)
    _shown_cover[uid] = None
    if old and old != msg.message_id:
        try:
            await bot.delete_message(uid, old)
        except TelegramAPIError:
            pass
    return msg


async def edit_audio_card(uid, mid, room, caption, markup):
    """Swap the song inside the existing audio message (no new message), caption and buttons follow."""
    t, url = room.cur, room.url
    try:
        src, thumb = await _audio_source(t, url)
        try:
            res = await bot.edit_message_media(chat_id=uid, message_id=mid, reply_markup=markup,
                                               media=InputMediaAudio(media=src, thumbnail=thumb, caption=caption, **_audio_meta(t)))
        except TelegramBadRequest as e:
            if "not modified" in str(e).lower():
                _solo_key[uid] = _tkey(t)
                return True
            res = await bot.edit_message_media(chat_id=uid, message_id=mid, reply_markup=markup,
                                               media=InputMediaAudio(media=src, caption=caption, **_audio_meta(t)))
    except TelegramAPIError as e:
        log.warning("audio edit failed: %s", e)
        return None
    _remember(t, res)
    _solo_key[uid] = _tkey(t)
    return True


async def cb_pick(cb: CallbackQuery):
    if not await guard_cb(cb):
        return
    uid = cb.from_user.id
    t = music.take(cb.data[3:], uid)
    if t is None:
        return await cb.answer("These results expired. Search again.", show_alert=True)
    room = rooms.get(uid)
    if room is None:
        return await cb.answer("I'm busy right now, try again in a minute.", show_alert=True)
    t.update(by=clean_text(cb.from_user.first_name, 30), by_id=uid, src="p")
    pos = room.add(t)
    if pos is None:
        return await cb.answer("The queue is full.", show_alert=True)
    await cb.answer("▶ Starting…" if pos == "start" else f"➕ Added at #{pos}")
    for _ in range(25):                                     # wait for the first song to be picked up (about a second)
        if room.cur is not None and (_solo_kind.get(uid) != "audio" or room.url):
            break
        await asyncio.sleep(0.2)
    if _solo_kind.get(uid) == "audio":                      # chat mode stays chat mode: the same music message turns into the new song
        if _solo.get(uid):
            return await _update_panel(uid, 0)
        if await send_audio_card(uid, room) is not None:
            return
    await send_solo_card(uid, room, (room.cur or t).get("cover"))


@router.callback_query(F.data == "sa")
async def cb_send_audio(cb: CallbackQuery):
    """In Chat: the player card turns into the song itself (one real music message, buttons under it)."""
    if not await guard_cb(cb):
        return
    uid = cb.from_user.id
    room = rooms.get(uid, create=False)
    if room is None or room.cur is None or not room.url:
        return await cb.answer("Nothing is playing. Send a song name first.", show_alert=True)
    await cb.answer("🎵 Sending the song…")
    if await send_audio_card(uid, room) is None:
        return await cb.message.answer("😕 Couldn't send this song in chat. Try the Open Player button.")


async def text_private(m: Message):
    if await guard(m):
        store.touch_user(m.from_user)
        await private_search(m, m.text)

async def cmd_play_private(m: Message, command: CommandObject):
    if await guard(m):
        store.touch_user(m.from_user)
        await private_search(m, command.args)


# ==========================================
# PRIVATE CHAT (DM) AUDIO LOGIC
# ==========================================
import hashlib
import httpx
from aiogram.enums import ChatAction
from aiogram.types import BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

MAX_BYTES = 49 * 1024 * 1024
RANGE_STEP = 8 * 1024 * 1024
RESULTS = 8

_UA_WEB = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
_UA_ANDROID = "com.google.android.youtube/19.09.37 (Linux; U; Android 11) gzip"

def _fmt_dur(sec) -> str:
    try:
        sec = int(sec)
    except Exception:
        return ""
    if sec <= 0:
        return ""
    return f"{sec // 60}:{sec % 60:02d}"

def _is_yt(track: dict, url: str = "") -> bool:
    return track.get("src") == "youtube" or "googlevideo.com" in (url or "")

def _ext(ctype: str, url: str) -> str:
    c = (ctype or "").lower()
    if "mpeg" in c or url.split("?")[0].lower().endswith(".mp3"):
        return "mp3"
    if "webm" in c:
        return "webm"
    return "m4a"

def _safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n]+', "", s).strip()[:80] or "track"

async def _fetch_plain(c: httpx.AsyncClient, url: str, headers: dict):
    async with c.stream("GET", url, headers=headers) as r:
        r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        clen = int(r.headers.get("content-length") or 0)
        if clen > MAX_BYTES:
            raise ValueError("file too large")
        buf = bytearray()
        async for chunk in r.aiter_bytes(64 * 1024):
            buf += chunk
            if len(buf) > MAX_BYTES:
                raise ValueError("file too large")
        return bytes(buf), ctype

async def _fetch_ranged(c: httpx.AsyncClient, url: str, headers: dict):
    buf = bytearray()
    start = 0
    ctype = ""
    while True:
        r = await c.get(url, headers={**headers, "Range": f"bytes={start}-{start + RANGE_STEP - 1}"})
        if not ctype:
            ctype = r.headers.get("content-type", "")
        if r.status_code == 200:
            if len(r.content) > MAX_BYTES:
                raise ValueError("file too large")
            return r.content, ctype
        if r.status_code != 206:
            r.raise_for_status()
            raise RuntimeError(f"unexpected status {r.status_code}")

        buf += r.content
        if len(buf) > MAX_BYTES:
            raise ValueError("file too large")

        m = re.match(r"bytes (\d+)-(\d+)/(\d+|\*)", r.headers.get("content-range", ""))
        if not m:
            break
        last = int(m.group(2))
        total = None if m.group(3) == "*" else int(m.group(3))
        start = last + 1
        if total is not None and start >= total:
            break
        if total is None and len(r.content) < RANGE_STEP:
            break
    return bytes(buf), ctype

async def _fetch(url: str, yt: bool = False):
    headers = {"Accept": "*/*", "Accept-Encoding": "identity"}
    if yt:
        headers.update({"User-Agent": _UA_ANDROID, "Referer": "https://www.youtube.com/"})
    else:
        headers["User-Agent"] = _UA_WEB
    timeout = httpx.Timeout(connect=15.0, read=60.0, write=15.0, pool=15.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as c:
        if yt:
            return await _fetch_ranged(c, url, headers)
        return await _fetch_plain(c, url, headers)

async def _fetch_thumb(url: str):
    if not url: return None
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": _UA_WEB})
            r.raise_for_status()
        ctype = r.headers.get("content-type", "")
        if "jpeg" in ctype or "jpg" in ctype:
            if 0 < len(r.content) <= 200 * 1024:
                return BufferedInputFile(r.content, filename="cover.jpg")
    except Exception:
        pass
    return None

async def send_audio_card(bot, uid: int, track: dict) -> bool:
    title = track.get("title") or "Unknown"
    artist = track.get("artist") or ""
    try:
        await bot.send_chat_action(uid, ChatAction.UPLOAD_VOICE)
        try:
            url = await asyncio.wait_for(music.resolve(track), 40)
        except Exception:
            url = None
        if not url:
            await bot.send_message(uid, "❌ Couldn't load that track. Try another result.")
            return False

        data, ctype = await _fetch(url, yt=_is_yt(track, url))
        if not data:
            raise RuntimeError("empty download")

        filename = f"{_safe_name(f'{artist} - {title}' if artist else title)}.{_ext(ctype, url)}"
        file = BufferedInputFile(data, filename=filename)
        thumb = await _fetch_thumb(track.get("img", ""))

        caption = f"🎵 <b>{html.escape(title)}</b>"
        if artist:
            caption += f"\n👤 {html.escape(artist)}"
        dur = _fmt_dur(track.get("dur"))
        if dur:
            caption += f"\n⏱ {dur}"

        await bot.send_chat_action(uid, ChatAction.UPLOAD_VOICE)
        await bot.send_audio(
            uid,
            file,
            title=title,
            performer=artist or None,
            duration=int(track.get("dur") or 0) or None,
            thumbnail=thumb,
            caption=caption,
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        log.exception(f"send_audio_card crashed: {e}")
        await bot.send_message(uid, "❌ Something went wrong.")
        return False

async def private_search(m: Message, q: str):
    q = clean_text(q or "", 80)
    if len(q) < 2:
        return await m.answer("🔎 <b>Send me a song or artist name</b>")
    tracks = await music.search(q, RESULTS)
    if not tracks:
        return await m.answer("😕 No results. Try the artist name too.")

    kb = InlineKeyboardBuilder()
    for t in tracks:
        if len(f"ps:{t.get('id', '')}".encode()) > 64:
            t = {**t, "id": hashlib.sha1(str(t.get("id")).encode()).hexdigest()[:16]}
        key = music.stash(t)
        dur = _fmt_dur(t.get("dur"))
        label = f"{t.get('title', '?')} — {t.get('artist', '')}".strip(" —")
        if dur:
            label += f" · {dur}"
        kb.button(text=label[:60], callback_data=f"ps:{key}")
    kb.adjust(1)

    await m.answer(f"🔎 <b>Results for</b> “{html.escape(q[:60])}”\n\nTap a song to get it:", reply_markup=kb.as_markup(), parse_mode="HTML")

@router.callback_query(F.data.startswith("ps:"))
async def cb_pick(cb: CallbackQuery):
    if not await guard_cb(cb): return
    key = cb.data[3:]
    track = music.take(key)
    if not track:
        return await cb.answer("This search expired. Please search again.", show_alert=True)
    await cb.answer("⏳ Getting your song…")
    uid = cb.from_user.id
    room = rooms.get(uid)
    if room is None:
        room = rooms.get(uid)
    await send_audio_card(bot, uid, track)
