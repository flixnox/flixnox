"""Small data layer: everything lives in memory and is written through to MongoDB Atlas (if configured)."""
import asyncio
import logging
import time
from bisect import bisect_right

from .security import clean_text

log = logging.getLogger("store")


def _day():
    return "d:" + time.strftime("%Y-%m-%d", time.gmtime())


class Store:
    def __init__(self):
        self.users, self.groups, self.bans, self.kv, self.bcs, self.stats = {}, {}, {}, {}, {}, {}
        self.db = None
        self._tasks = set()

    async def init(self, uri, name):
        if not uri:
            log.warning("MONGO_URI not set - data will NOT survive a restart")
            return
        from motor.motor_asyncio import AsyncIOMotorClient
        self.db = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=8000)[name]
        for coll in ("users", "groups", "bans", "kv", "bcs", "stats"):
            async for d in self.db[coll].find({}):
                getattr(self, coll)[d["_id"]] = d

    # --- persistence ---
    def _bg(self, coro):
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    def _put(self, coll, doc):
        if self.db is not None:
            self._bg(self._w(coll, doc))

    async def _w(self, coll, doc):
        try:
            await self.db[coll].replace_one({"_id": doc["_id"]}, doc, upsert=True)
        except Exception as e:
            log.warning("db write failed: %s", e)

    async def _d(self, coll, _id):
        try:
            await self.db[coll].delete_one({"_id": _id})
        except Exception as e:
            log.warning("db delete failed: %s", e)

    # --- users / groups ---
    def touch_user(self, u):
        d = self.users.get(u.id)
        if d is None or d.get("dead"):
            d = {"_id": u.id, "name": clean_text(u.full_name or "", 40), "ts": int(time.time()), "dead": False}
            self.users[u.id] = d
            self._put("users", d)
            return True
        return False

    def group(self, chat_id):
        g = self.groups.get(chat_id)
        if g is None:
            g = {"_id": chat_id, "title": "", "play": "all", "autodel": False, "panel": None,
                 "dead": False, "ts": int(time.time())}
            self.groups[chat_id] = g
        return g

    def touch_group(self, chat):
        g = self.group(chat.id)
        title = clean_text(chat.title or "", 60)
        if g.get("title") != title or g.get("dead"):
            g["title"], g["dead"] = title, False
            self._put("groups", g)

    def set_group(self, chat_id, **kw):
        g = self.group(chat_id)
        g.update(kw)
        self._put("groups", g)

    def mark_dead(self, kind, _id):
        d = (self.users if kind == "users" else self.groups).get(_id)
        if d and not d.get("dead"):
            d["dead"] = True
            self._put(kind, d)

    # --- bans ---
    def is_banned(self, kind, _id):
        return f"{kind}:{_id}" in self.bans

    def ban(self, kind, _id):
        k = f"{kind}:{_id}"
        self.bans[k] = {"_id": k, "ts": int(time.time())}
        self._put("bans", self.bans[k])

    def unban(self, kind, _id):
        k = f"{kind}:{_id}"
        if self.bans.pop(k, None) and self.db is not None:
            self._bg(self._d("bans", k))

    # --- misc ---
    def get_kv(self, k, default=None):
        return self.kv.get(k, {}).get("v", default)

    def set_kv(self, k, v):
        self.kv[k] = {"_id": k, "v": v}
        self._put("kv", self.kv[k])

    def inc(self, name, n=1):
        for key in ("total", _day()):
            d = self.stats.setdefault(key, {"_id": key})
            d[name] = d.get(name, 0) + n
            self._put("stats", d)

    def summary(self):
        day = self.stats.get(_day(), {})
        return {
            "users": sum(1 for d in self.users.values() if not d.get("dead")),
            "users_dead": sum(1 for d in self.users.values() if d.get("dead")),
            "groups": sum(1 for d in self.groups.values() if not d.get("dead") and d.get("panel")),
            "groups_dead": sum(1 for d in self.groups.values() if d.get("dead")),
            "bans": len(self.bans),
            "plays_today": day.get("plays", 0),
            "plays_total": self.stats.get("total", {}).get("plays", 0),
        }

    # --- broadcast ---
    def snapshot(self, kind):
        coll = self.users if kind == "users" else self.groups
        return sorted(i for i, d in coll.items() if not d.get("dead"))

    def start_index(self, ids, last):
        return 0 if last is None else bisect_right(ids, last)

    def bc_save(self, doc):
        self.bcs[doc["_id"]] = doc
        self._put("bcs", doc)

    def bc_running(self):
        return [d for d in self.bcs.values() if d.get("status") == "running"]
