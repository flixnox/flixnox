import asyncio
from aiogram import Router, F
from aiogram.types import Message, InputMediaPhoto
from aiogram.filters import Command

from . import ui, rooms, store, state, admin, security
from .state import bot


router = Router()


# Welcome command with spoiler banner + buttons
@router.message(Command("start"))
async def cmd_start(m: Message):
    """Welcome message with spoiler image and update/developer buttons"""
    
    welcome_text = ui.welcome_text()
    keyboard = ui.welcome_kb()
    
    # Banner image URL (configure in config)
    banner_url = "https://i.pinimg.com/564x/placeholder.jpg"  # Replace with actual
    
    try:
        await m.reply_photo(
            photo=banner_url,
            caption=welcome_text,
            reply_markup=keyboard,
            parse_mode="HTML",
            has_spoiler=True
        )
    except:
        # Fallback if image not available
        await m.reply(welcome_text, reply_markup=keyboard, parse_mode="HTML")


# Panel changed - room display with spoiler image
async def panel_changed(room):
    """Update room panel with spoiler image and new buttons"""
    
    chat_id = room.chat_id
    mid = store.group(chat_id).get("panel")
    
    text = ui.control_panel_text(room)
    keyboard = ui.control_kb(chat_id)
    
    # Album art (spoiler)
    album_art = room.current.get("image") if room.current else None
    
    if not mid:
        # Create new panel
        try:
            if album_art:
                msg = await bot.send_photo(
                    chat_id=chat_id,
                    photo=album_art,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    has_spoiler=True
                )
            else:
                msg = await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            
            store.set_group(chat_id, panel=msg.message_id)
            await msg.pin(disable_notification=True)
        except:
            pass
    else:
        # Update existing panel
        try:
            if album_art:
                await bot.edit_message_media(
                    chat_id=chat_id,
                    message_id=mid,
                    media=InputMediaPhoto(
                        media=album_art,
                        caption=text,
                        parse_mode="HTML"
                    ),
                    reply_markup=keyboard
                )
            else:
                await bot.edit_message_text(
                    text=text,
                    chat_id=chat_id,
                    message_id=mid,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
        except:
            pass


# Message cleanup on play
_qmsgs = {}

def _delete_msgs(chat_id, ids, delay=0):
    """Delete messages with optional delay"""
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
    """Track started playing"""
    store.inc("plays")
    _delete_msgs(room.chat_id, _qmsgs.pop(room.chat_id, []))
    track["started"] = True
    _delete_msgs(room.chat_id, track.pop("msgs", []), 20 if track.get("instant") else 0)


def on_drop(room, track):
    """Track skipped/dropped"""
    _delete_msgs(room.chat_id, track.pop("msgs", []))


def on_fail(room, track):
    """Track failed to play"""
    pass


# Callback handlers
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
    
    await q.answer("📝 Queue updated")


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
    
    await q.message.reply(
        f"🎧 <b>Share This Link</b>\n\n"
        f"<a href='{room_link}'>▶️ Join Room</a>",
        parse_mode="HTML"
    )
    await q.answer("📨 Share link sent")


@router.callback_query(F.data == "more")
async def cb_more(q):
    await q.answer("⚙ More options coming soon", show_alert=True)


@router.callback_query(F.data == "menu")
async def cb_menu(q):
    await q.answer("📋 Menu options", show_alert=True)


# Admin commands
@router.message(Command("end"))
async def cmd_end(m: Message):
    """End the room (admin only)"""
    
    if not await state.is_admin(m.chat.id, m.from_user.id):
        return await m.reply("❌ Admin only")
    
    await close_room(m.chat.id)
    await m.reply("✅ Room ended")


async def close_room(chat_id):
    """Close room and notify clients"""
    
    mid = store.group(chat_id).get("panel")
    room = rooms.get(chat_id, create=False)
    
    store.set_group(chat_id, panel=None)
    
    if room:
        await room.end()
        for c in list(room.clients.values()):
            try:
                await c.send({"t": "fatal", "m": "Room ended by admin"})
                await c.close()
            except:
                pass
        rooms.drop(chat_id)
    
    _qmsgs.pop(chat_id, None)
    
    if mid:
        try:
            await bot.edit_message_text(
                ui.closed_caption(),
                chat_id=chat_id,
                message_id=mid,
                parse_mode="HTML",
                reply_markup=None
            )
        except:
            pass
        
        try:
            await bot.unpin_chat_message(chat_id, mid)
        except:
            pass
