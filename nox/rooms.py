"""Room state. The server owns the clock: clients only follow it, so nobody can drive a room by themselves."""
import asyncio
import random
import time

from . import config

PUB = ("title", "artist", "dur", "cover", "by", "src")


def pub(t):
    return {k: t.get(k) for k in PUB}


class Room:
    def __init__(self, chat_id, mgr):
        self.chat_id, self.mgr = chat_id, mgr
        self.queue, self.cur, self.url, self.preview = [], None, None, False
        self.pos0, self.t0 = 0.0, time.time()
        self.paused = self.auto_paused = self.loop = False
        self.seq = 0
        self.clients = {}                 # user_id -> client
        self.lock = asyncio.Lock()
        self.touched = time.time()
        self._wd = None
        self._kicking = False
        self.ended_votes, self.bad_votes, self.durs = set(), set(), {}

    # ---- state ----
    def position(self):
        return self.pos0 if self.paused else self.pos0 + (time.time() - self.t0)

    def state(self):
        return {"t": "state", "seq": self.seq, "track": pub(self.cur) if self.cur else None,
                "url": self.url if self.cur else None, "preview": self.preview,
                "pos": round(self.position(), 2), "paused": self.paused, "st": time.time(),
                "loop": self.loop, "queue": [pub(x) for x in self.queue[:50]], "qn": len(self.queue),
                "n": len(self.clients)}

    async def push(self, only=None):
        self.touched = time.time()
        msg = self.state()
        targets = [only] if only else list(self.clients.values())
        results = await asyncio.gather(*[c.send(msg) for c in targets], return_exceptions=True)
        for c, ok in zip(targets, results):
            if ok is not True and self.clients.get(c.uid) is c:
                del self.clients[c.uid]
        if only is None:
            self.mgr.panel_changed(self.chat_id)

    # ---- clients ----
    async def join(self, client):
        old = self.clients.get(client.uid)
        self.clients[client.uid] = client
        if old is not None and old is not client:
            await old.close()
        if self.auto_paused:
            await self.resume()
        await self.push()

    async def leave(self, client):
        if self.clients.get(client.uid) is client:
            del self.clients[client.uid]
        if not self.clients:
            await self.pause(auto=True)      # nobody listening -> the room clock stops
        else:
            await self.push()

    # ---- queue ----
    def add(self, track):
        """Returns None (full), 'start' (will start now) or the queue position."""
        if len(self.queue) >= config.MAX_QUEUE:
            return None
        self.queue.append(track)
        self.touched = time.time()
        if self.cur is None and not self._kicking:
            self._kicking = True
            self.mgr.spawn(self._kick())
            return "start"
        self.mgr.spawn(self.push())
        return len(self.queue)

    async def _kick(self):
        try:
            async with self.lock:
                if self.cur is None:
                    await self._advance()
        finally:
            self._kicking = False
        await self.push()

    async def _advance(self):
        """Move to the next playable track. Caller must hold the lock."""
        from . import music
        self._cancel_wd()
        for _ in range(6):
            if not self.queue:
                break
            t = self.queue.pop(0)
            try:
                r = await asyncio.wait_for(music.resolve(t), 50)
            except Exception:
                r = None
            if r:
                self.cur, self.url, self.preview = t, r["url"], r["preview"]
                self.pos0, self.t0, self.paused, self.auto_paused = 0.0, time.time(), False, False
                self.seq += 1
                self.ended_votes, self.bad_votes, self.durs = set(), set(), {}
                self._arm_wd()
                self.mgr.on_play(self, t)
                return True
            self.mgr.on_fail(self, t)
        self.cur, self.url = None, None
        self.seq += 1
        return False

    # ---- controls (callers check admin rights) ----
    async def skip(self):
        async with self.lock:
            if self.cur is None:
                return False
            await self._advance()
        await self.push()
        return True

    async def pause(self, auto=False):
        async with self.lock:
            if self.cur is None or self.paused:
                return False
            self.pos0, self.paused, self.auto_paused = self.position(), True, auto
            self._cancel_wd()
        await self.push()
        return True

    async def resume(self):
        async with self.lock:
            if self.cur is None or not self.paused:
                return False
            self.t0, self.paused, self.auto_paused = time.time(), False, False
            self._arm_wd()
        await self.push()
        return True

    async def shuffle(self):
        random.shuffle(self.queue)
        await self.push()
        return True

    async def clear(self):
        self.queue.clear()
        await self.push()
        return True

    async def toggle_loop(self):
        self.loop = not self.loop
        await self.push()
        return self.loop

    async def end(self):
        async with self.lock:
            self.queue.clear()
            self.cur, self.url, self.paused = None, None, False
            self.seq += 1
            self._cancel_wd()
        await self.push()
        return True

    async def remove(self, idx):
        if isinstance(idx, int) and 0 <= idx < len(self.queue):
            self.queue.pop(idx)
            await self.push()
            return True
        return False

    # ---- listener reports (quorum protected, so one client cannot skip songs) ----
    def report_dur(self, uid, seq, d):
        if seq == self.seq and isinstance(d, (int, float)) and 5 <= d <= 14400:
            self.durs[uid] = float(d)
            self._arm_wd()

    async def vote_end(self, uid, seq):
        if seq != self.seq or self.cur is None or self.paused:
            return
        dur = self.cur.get("dur") or (max(self.durs.values()) if self.durs else None)
        if (dur and self.position() < 0.85 * dur) or (not dur and self.position() < 30):
            return
        self.ended_votes.add(uid)
        if len(self.ended_votes) >= len(self.clients) // 2 + 1:      # strict majority
            await self._finish(seq)

    async def vote_bad(self, uid, seq):
        if seq != self.seq or self.cur is None:
            return
        self.bad_votes.add(uid)
        if len(self.bad_votes) >= len(self.clients) // 2 + 1:        # strict majority
            async with self.lock:
                if seq == self.seq:
                    await self._advance()
            await self.push()

    async def _finish(self, seq):
        async with self.lock:
            if seq != self.seq or self.cur is None:
                return
            if self.loop:
                self.pos0, self.t0 = 0.0, time.time()
                self.seq += 1
                self.ended_votes, self.bad_votes = set(), set()
                self._arm_wd()
            else:
                await self._advance()
        await self.push()

    # ---- watchdog: moves on even if no client reports the end ----
    def _cancel_wd(self):
        if self._wd is not None and self._wd is not asyncio.current_task():
            self._wd.cancel()
        self._wd = None

    def _arm_wd(self):
        self._cancel_wd()
        dur = max(self.durs.values()) if self.durs else ((self.cur or {}).get("dur") or 900)
        self._wd = self.mgr.spawn(self._watch(self.seq, max(5, dur - self.position()) + 40))

    async def _watch(self, seq, delay):
        try:
            await asyncio.sleep(delay)
            await self._finish(seq)
        except asyncio.CancelledError:
            pass


class Manager:
    def __init__(self):
        self.rooms, self.tasks = {}, set()
        self.on_play = lambda room, track: None
        self.on_fail = lambda room, track: None
        self.panel_changed = lambda chat_id: None

    def spawn(self, coro):
        t = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)
        return t

    def get(self, chat_id, create=True):
        r = self.rooms.get(chat_id)
        if r is None and create and len(self.rooms) < 400:
            r = self.rooms[chat_id] = Room(chat_id, self)
        return r

    def drop(self, chat_id):
        r = self.rooms.pop(chat_id, None)
        if r:
            r._cancel_wd()

    async def sweeper(self):
        while True:
            await asyncio.sleep(300)
            now = time.time()
            for cid, r in list(self.rooms.items()):
                idle = now - r.touched
                if not r.clients and ((r.cur is None and not r.queue and idle > 1800) or idle > 21600):
                    self.drop(cid)
