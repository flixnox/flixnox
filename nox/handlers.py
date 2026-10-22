import asyncio
from aiogram import Router, F
from aiogram.types import Message, InputMediaPhoto
from aiogram.filters import Command

from . import ui, rooms, store, state, security
from .state import bot


router = Router()


@router.message(Command("start"))
async def cmd_start(m: Message):
    welcome_text = ui.welcome_text()
    keyboard = ui.welcome_kb()
    
    try:
        await m.reply_photo(
            photo="https://i.pinimg.com/564x/placeholder.jpg",
            caption=welcome_text,
            reply_markup=keyboard,
            parse_mode="HTML",
            has_spoiler=True
        )
    except:
        await m.reply(welcome_text, reply_markup=keyboard, parse_mode="HTML")


async def panel_changed(room):
    chat_id = room.chat_id
    mid = store.group(chat_id).get("panel")
    text = ui.control_panel_text(room)
    keyboard = ui.control_kb(chat_id)
    
    if not mid:
        try:
            msg = await bot.send_message(chat_id=chat_id, text=text, reply_markup=keyboard, parse_mode="HTML")
            store.set_group(chat_id, panel=msg.message_id)
            await msg.pin(disable_notification=True)
        except:
            pass
    else:
        try:
            await bot.edit_message_text(text=text, chat_id=chat_id, message_id=mid, reply_markup=keyboard, parse_mode="HTML")
        except:
            pass


_qmsgs = {}

def _delete_msgs(chat_id, ids, delay=0):
    if not ids:
        return
    async def _go():
        if delay:
            await asyncio.sleep(delay)
        for mid in ids:
            try:
                await bot.delete_message(chat_id, mid)
            except:
                pass
    rooms.spawn(_go())


def on_play(room, track):
    store.inc("plays")
    _delete_msgs(room.chat_id, _qmsgs.pop(room.chat_id, []))
    track["started"] = True
    _delete_msgs(room.chat_id, track.pop("msgs", []), 20 if track.get("instant") else 0)


def on_drop(room, track):
    _delete_msgs(room.chat_id, track.pop("msgs", []))


def on_fail(room, track):
    pass


@router.callback_query(F.data == "pause")
async def cb_pause(q):
    room = rooms.get(q.message.chat.id, create=False)
    if room:
        await room.pause()
    await q.answer("⏸ Paused")


@router.callback_query(F.data == "skip")
async def cb_skip(q):
    room = rooms.get(q.message.chat.id, create=False)
    if room:
        await room.skip()
    await q.answer("⏭ Skipped")


@router.callback_query(F.data == "loop")
async def cb_loop(q):
    room = rooms.get(q.message.chat.id, create=False)
    if room:
        room.toggle_loop()
    await q.answer("🔁 Loop toggled")


@router.callback_query(F.data == "shuffle")
async def cb_shuffle(q):
    room = rooms.get(q.message.chat.id, create=False)
    if room:
        room.shuffle()
    await q.answer("🔀 Queue shuffled")


@router.callback_query(F.data == "queue")
async def cb_queue(q):
    room = rooms.get(q.message.chat.id, create=False)
    text = ui.queue_text(room)
    reply = await q.message.reply(text, parse_mode="HTML")
    ids = _qmsgs.setdefault(q.message.chat.id, [])
    ids[:] = (ids + [reply.message_id, q.message.message_id])[-20:]
    await q.answer("📝 Queue")


@router.callback_query(F.data == "autoplay")
async def cb_autoplay(q):
    room = rooms.get(q.message.chat.id, create=False)
    if room:
        room.toggle_autoplay()
    await q.answer("♾ Autoplay toggled")


@router.callback_query(F.data == "invite")
async def cb_invite(q):
    chat_id = q.message.chat.id
    room_link = f"https://t.me/{state.config.BOT_USERNAME}/{state.config.MINIAPP_SHORT}?startapp={security.encode_room(chat_id)}"
    await q.message.reply(f"🎧 <b>Share This Link</b>\n\n<a href='{room_link}'>▶️ Join Room</a>", parse_mode="HTML")
    await q.answer("📨 Shared")


@router.callback_query(F.data == "more")
async def cb_more(q):
    await q.answer("More options coming soon", show_alert=True)


@router.callback_query(F.data == "menu")
async def cb_menu(q):
    await q.answer("Menu", show_alert=True)
