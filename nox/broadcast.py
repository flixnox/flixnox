"""Owner broadcasts: text / media (copy) or forwarded posts. Throttled, resumable, cleans dead chats."""
import asyncio
import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from .state import bot, store

log = logging.getLogger("broadcast")
DEAD_HINTS = ("chat not found", "user is deactivated", "bot was kicked", "bot was blocked", "peer_id_invalid",
              "have no rights", "not enough rights", "chat_write_forbidden")


async def _send(doc, kind, cid):
    for _ in range(4):
        try:
            if doc["mode"] == "forward":
                sent = await bot.forward_message(cid, doc["from"], doc["mid"])
            else:
                sent = await bot.copy_message(cid, doc["from"], doc["mid"])
            doc["stats"]["ok"] += 1
            if doc["pin"] and kind == "groups":
                try:
                    await bot.pin_chat_message(cid, sent.message_id, disable_notification=True)
                except TelegramAPIError:
                    pass
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramForbiddenError:
            store.mark_dead(kind, cid)
            doc["stats"]["dead"] += 1
            return
        except TelegramBadRequest as e:
            if any(h in str(e).lower() for h in DEAD_HINTS):
                store.mark_dead(kind, cid)
                doc["stats"]["dead"] += 1
            else:
                doc["stats"]["fail"] += 1
            return
        except Exception:
            doc["stats"]["fail"] += 1
            return
    doc["stats"]["fail"] += 1


async def run(bc_id):
    doc = store.bcs.get(bc_id)
    if not doc:
        return
    try:
        while doc["status"] == "running" and doc["ki"] < len(doc["kinds"]):
            kind = doc["kinds"][doc["ki"]]
            ids = store.snapshot(kind)
            i = store.start_index(ids, doc["last"])
            n = 0
            while i < len(ids) and doc["status"] == "running":
                cid = ids[i]
                i += 1
                await _send(doc, kind, cid)
                doc["last"] = cid
                n += 1
                if n % 40 == 0:
                    store.bc_save(doc)
                await asyncio.sleep(0.045)          # ~22 messages per second, under Telegram's limit
            if doc["status"] == "running":
                doc["ki"] += 1
                doc["last"] = None
        if doc["status"] == "running":
            doc["status"] = "done"
    except Exception:
        log.exception("broadcast crashed")
        doc["status"] = "error"
    finally:
        store.bc_save(doc)
        s = doc["stats"]
        label = {"done": "✅ Broadcast finished", "cancelled": "⛔ Broadcast stopped", "error": "⚠️ Broadcast failed"}.get(
            doc["status"], "Broadcast paused")
        try:
            await bot.send_message(doc["owner"], f"{label}\nDelivered: <b>{s['ok']}</b>\nFailed: <b>{s['fail']}</b>\n"
                                                 f"Removed (blocked/left): <b>{s['dead']}</b>")
        except TelegramAPIError:
            pass
