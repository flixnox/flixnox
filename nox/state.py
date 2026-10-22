"""Shared singletons and chat-membership helpers."""
import time

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from . import config
from .rooms import Manager
from .security import Penalty, RateLimiter
from .store import Store

bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
store = Store()
rooms = Manager()
cmd_rl = RateLimiter(0.5, 4)        # chat commands
cb_rl = RateLimiter(3, 10)          # button taps (generous, so buttons never feel dead)
ws_rl = RateLimiter(10, 25)         # websocket messages per user
search_rl = RateLimiter(1.5, 6)     # searches per user
conn_rl = RateLimiter(0.3, 8)       # new websocket connections per IP
penalty = Penalty()
me = None                           # filled in at startup (bot.get_me())

_cache = {}


async def _status(chat_id, user_id):
    k = (chat_id, user_id)
    v = _cache.get(k)
    if v and v[1] > time.monotonic():
        return v[0]
    try:
        m = await bot.get_chat_member(chat_id, user_id)
        s = (m.status, bool(getattr(m, "is_member", True)))
    except TelegramAPIError:
        s = ("left", False)
    if len(_cache) > 20000:
        _cache.clear()
    _cache[k] = (s, time.monotonic() + 30)
    return s


async def is_admin(chat_id, user_id):
    if user_id in config.OWNER_IDS:
        return True
    return (await _status(chat_id, user_id))[0] in ("creator", "administrator")


async def is_member(chat_id, user_id):
    if user_id in config.OWNER_IDS:
        return True
    st, joined = await _status(chat_id, user_id)
    return st in ("creator", "administrator", "member") or (st == "restricted" and joined)
