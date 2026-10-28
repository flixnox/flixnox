"""Owner-only admin panel (private chat): stats, API health, ban/unban, maintenance, broadcast."""
import asyncio
import html
import time
import uuid

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from . import broadcast, config, music, ui
from .state import bot, rooms, store

router = Router(name="admin")
router.message.filter(F.chat.type == "private", F.from_user.id.in_(config.OWNER_IDS))
router.callback_query.filter(F.from_user.id.in_(config.OWNER_IDS), F.data.startswith("ad:"))


class S(StatesGroup):
    ban = State()
    unban = State()
    bc_msg = State()


def panel():
    m = bool(store.get_kv("maint", False))
    return ui.kb(
        [ui.btn("📊 Stats", cb="ad:stats", style=ui.P), ui.btn("🩺 API health", cb="ad:health", style=ui.P)],
        [ui.btn("📣 Broadcast", cb="ad:bc", style=ui.S)],
        [ui.btn("🚫 Ban", cb="ad:ban", style=ui.D), ui.btn("♻️ Unban", cb="ad:unban", style=ui.S)],
        [ui.btn("🛠 Maintenance: " + ("ON" if m else "OFF"), cb="ad:mt", style=ui.D if m else ui.S),
         ui.btn("🧹 Clear cache", cb="ad:cc", style=ui.P)],
    )


HEAD = "🛡 <b>ᴀᴅᴍɪɴ ᴘᴀɴᴇʟ</b>"


@router.message(Command("admin"))
async def admin_cmd(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(HEAD, reply_markup=panel())


@router.callback_query(F.data == "ad:home")
async def home(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(HEAD, reply_markup=panel())
    await cb.answer()


@router.callback_query(F.data == "ad:stats")
async def stats(cb: CallbackQuery):
    s = store.summary()
    listeners = sum(len(r.clients) for r in rooms.rooms.values())
    live = sum(1 for r in rooms.rooms.values() if r.cur)
    txt = (f"📊 <b>{ui.sc('stats')}</b>\nUsers: <b>{s['users']}</b> (blocked/left {s['users_dead']})\n"
           f"Groups with a room: <b>{s['groups']}</b> (removed {s['groups_dead']})\n"
           f"Rooms playing now: <b>{live}</b> • listeners: <b>{listeners}</b>\n"
           f"Plays today: <b>{s['plays_today']}</b> • total: <b>{s['plays_total']}</b>\nBanned: <b>{s['bans']}</b>")
    await cb.message.edit_text(txt, reply_markup=ui.kb([ui.btn("⬅ Back", cb="ad:home")]))
    await cb.answer()


@router.callback_query(F.data == "ad:health")
async def health(cb: CallbackQuery):
    await cb.answer("Checking…")
    rows = await music.health()
    txt = f"🩺 <b>{ui.sc('api health')}</b>\n" + "\n".join(
        f"{'✅' if ok else '❌'} {n}" + (f" ({ms} ms)" if ms is not None else "") for n, ok, ms in rows)
    await cb.message.edit_text(txt, reply_markup=ui.kb([ui.btn("⬅ Back", cb="ad:home")]))


@router.callback_query(F.data == "ad:mt")
async def maint(cb: CallbackQuery):
    store.set_kv("maint", not store.get_kv("maint", False))
    await cb.message.edit_reply_markup(reply_markup=panel())
    await cb.answer("Maintenance " + ("ON" if store.get_kv("maint") else "OFF"))


@router.callback_query(F.data == "ad:cc")
async def clear_cache(cb: CallbackQuery):
    music.clear_caches()
    await cb.answer("Caches cleared", show_alert=True)


# ---------------- ban / unban ----------------
def _parse_target(text):
    t = (text or "").strip().lower()
    kind = "u"
    if t.startswith("g:"):
        kind, t = "g", t[2:]
    try:
        return kind, int(t)
    except ValueError:
        return None


@router.callback_query(F.data.in_({"ad:ban", "ad:unban"}))
async def ask_ban(cb: CallbackQuery, state: FSMContext):
    await state.set_state(S.ban if cb.data == "ad:ban" else S.unban)
    await cb.message.edit_text("Send the numeric ID.\nFor a group, prefix with <code>g:</code> (example <code>g:-1001234567890</code>).",
                               reply_markup=ui.kb([ui.btn("✖ Cancel", cb="ad:home")]))
    await cb.answer()


@router.message(S.ban)
async def do_ban(m: Message, state: FSMContext):
    t = _parse_target(m.text)
    if not t:
        return await m.answer("That doesn't look like an ID. Try again or /admin.")
    kind, _id = t
    if _id in config.OWNER_IDS:
        return await m.answer("You can't ban an owner.")
    store.ban(kind, _id)
    if kind == "g":
        rooms.drop(_id)
        try:
            await bot.leave_chat(_id)
        except TelegramAPIError:
            pass
    await state.clear()
    await m.answer(f"🚫 Banned {'group' if kind == 'g' else 'user'} <code>{_id}</code>.", reply_markup=panel())


@router.message(S.unban)
async def do_unban(m: Message, state: FSMContext):
    t = _parse_target(m.text)
    if not t:
        return await m.answer("That doesn't look like an ID. Try again or /admin.")
    store.unban(*t)
    await state.clear()
    await m.answer(f"♻️ Unbanned <code>{t[1]}</code>.", reply_markup=panel())


# ---------------- broadcast ----------------
@router.callback_query(F.data == "ad:bc")
async def bc_start(cb: CallbackQuery):
    await cb.message.edit_text("📣 <b>Broadcast</b>\nWho should receive it?", reply_markup=ui.kb(
        [ui.btn("👤 Users", cb="ad:bca:users", style=ui.P), ui.btn("👥 Groups", cb="ad:bca:groups", style=ui.S)],
        [ui.btn("🌐 Both", cb="ad:bca:both", style=ui.P)], [ui.btn("⬅ Back", cb="ad:home")]))
    await cb.answer()


@router.callback_query(F.data.startswith("ad:bca:"))
async def bc_audience(cb: CallbackQuery, state: FSMContext):
    aud = cb.data.split(":")[2]
    if aud not in ("users", "groups", "both"):
        return await cb.answer()
    await state.update_data(aud=aud)
    await cb.message.edit_text(
        "How should it be sent?\n\n<b>Copy</b>: text or any media, no \"Forwarded from\" label.\n"
        "<b>Forward</b>: keeps the original source (e.g. the channel name).",
        reply_markup=ui.kb([ui.btn("📄 Copy", cb="ad:bcm:copy", style=ui.P), ui.btn("↪ Forward", cb="ad:bcm:forward", style=ui.S)],
                           [ui.btn("⬅ Back", cb="ad:bc")]))
    await cb.answer()


@router.callback_query(F.data.startswith("ad:bcm:"))
async def bc_mode(cb: CallbackQuery, state: FSMContext):
    mode = cb.data.split(":")[2]
    if mode not in ("copy", "forward"):
        return await cb.answer()
    await state.update_data(mode=mode)
    d = await state.get_data()
    if d.get("aud") in ("groups", "both"):
        await cb.message.edit_text("Pin the message in groups?", reply_markup=ui.kb(
            [ui.btn("📌 Yes, pin", cb="ad:bcp:1", style=ui.S), ui.btn("No", cb="ad:bcp:0", style=ui.P)]))
    else:
        await state.update_data(pin=False)
        await _await_msg(cb.message, state)
    await cb.answer()


@router.callback_query(F.data.startswith("ad:bcp:"))
async def bc_pin(cb: CallbackQuery, state: FSMContext):
    await state.update_data(pin=cb.data.endswith(":1"))
    await _await_msg(cb.message, state)
    await cb.answer()


async def _await_msg(msg, state):
    await state.set_state(S.bc_msg)
    d = await state.get_data()
    how = "forward the post to me" if d["mode"] == "forward" else "send the message (text, photo, video, file, anything)"
    await msg.edit_text(f"Now {how}.", reply_markup=ui.kb([ui.btn("✖ Cancel", cb="ad:home")]))


@router.message(S.bc_msg)
async def bc_preview(m: Message, state: FSMContext):
    d = await state.get_data()
    try:
        if d["mode"] == "forward":
            await bot.forward_message(m.chat.id, m.chat.id, m.message_id)
        else:
            await bot.copy_message(m.chat.id, m.chat.id, m.message_id)
    except TelegramAPIError as e:
        return await m.answer(f"I can't send this message ({str(e)[:120]}). Protected posts can't be copied or forwarded. Send another or /admin.")
    await state.update_data(mid=m.message_id)
    s = store.summary()
    n = {"users": s["users"], "groups": s["groups"], "both": s["users"] + s["groups"]}[d["aud"]]
    await m.answer(f"☝️ Preview. Send to about <b>{n}</b> chats ({d['aud']}, {d['mode']}{', pinned' if d.get('pin') else ''})?",
                   reply_markup=ui.kb([ui.btn("✅ Send now", cb="ad:bcgo", style=ui.S), ui.btn("✖ Cancel", cb="ad:home", style=ui.D)]))


@router.callback_query(F.data == "ad:bcgo")
async def bc_go(cb: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    if not d.get("mid"):
        return await cb.answer("Nothing staged", show_alert=True)
    bc_id = uuid.uuid4().hex[:10]
    doc = {"_id": bc_id, "kinds": ["users", "groups"] if d["aud"] == "both" else [d["aud"]], "mode": d["mode"],
           "pin": bool(d.get("pin")), "from": cb.from_user.id, "mid": d["mid"], "owner": cb.from_user.id,
           "status": "running", "ki": 0, "last": None, "stats": {"ok": 0, "fail": 0, "dead": 0}, "ts": int(time.time())}
    store.bc_save(doc)
    await state.clear()
    rooms.spawn(broadcast.run(bc_id))
    await cb.message.edit_text("📣 Broadcast started. I'll message you when it's done.",
                               reply_markup=ui.kb([ui.btn("⛔ Stop", cb=f"ad:bcs:{bc_id}", style=ui.D), ui.btn("⬅ Panel", cb="ad:home")]))
    await cb.answer()


@router.callback_query(F.data.startswith("ad:bcs:"))
async def bc_stop(cb: CallbackQuery):
    doc = store.bcs.get(cb.data.split(":")[2])
    if doc and doc["status"] == "running":
        doc["status"] = "cancelled"
    await cb.answer("Stopping…")


@router.message(Command("ytcheck"))
async def ytcheck(m: Message):
    wait = await m.answer("🔎 Checking YouTube… (results appear line by line, takes up to a minute)")
    last = {"t": ""}

    async def report(text):
        if text != last["t"]:
            last["t"] = text
            await wait.edit_text("<pre>" + html.escape(text) + "</pre>")

    try:
        await asyncio.wait_for(music.yt_diagnose(report), 90)
    except Exception as e:
        try:
            await report(last["t"] + "\n\n(stopped: " + type(e).__name__ + ")")
        except Exception:
            pass
