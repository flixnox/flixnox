"""Offline tests for the security and room logic.  Run:  python -m unittest discover -s tests"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import types
import unittest
from urllib.parse import urlencode

os.environ.update(BOT_TOKEN="123:TEST", PUBLIC_URL="https://w.example.workers.dev", OWNER_IDS="1",
                  PROXY_SECRET="p" * 32, WEBHOOK_SECRET="w" * 32)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from nox import config, security  # noqa: E402


def make_init(user, start="n1001234567890", age=0, token="123:TEST", tamper=False):
    d = {"auth_date": str(int(time.time()) - age), "user": json.dumps(user), "start_param": start}
    check = "\n".join(f"{k}={d[k]}" for k in sorted(d))
    key = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    d["hash"] = hmac.new(key, check.encode(), hashlib.sha256).hexdigest()
    if tamper:
        d["start_param"] = "n1009999999999"
    return urlencode(d)


class SecurityTests(unittest.TestCase):
    def test_init_data(self):
        u = {"id": 42, "first_name": "A"}
        self.assertEqual(security.verify_init_data(make_init(u), "123:TEST")["user"]["id"], 42)
        self.assertIsNone(security.verify_init_data(make_init(u, tamper=True), "123:TEST"))
        self.assertIsNone(security.verify_init_data(make_init(u), "999:OTHER"))
        self.assertIsNone(security.verify_init_data(make_init(u, age=999999), "123:TEST"))
        self.assertIsNone(security.verify_init_data(make_init({"id": 1, "is_bot": True}), "123:TEST"))
        self.assertIsNone(security.verify_init_data("", "123:TEST"))
        self.assertIsNone(security.verify_init_data("a=b&a=c&hash=x", "123:TEST"))

    def test_room_codec(self):
        self.assertEqual(security.decode_room(security.encode_room(-1001234567890)), -1001234567890)
        for bad in ("", "x1", "n", "1;drop", "n" + "9" * 30, None):
            self.assertIsNone(security.decode_room(bad))

    def test_urls_and_text(self):
        self.assertTrue(security.safe_https_url("https://cdn.example.com/a.mp3"))
        for bad in ("http://a.com/x", "https://127.0.0.1/x", "https://localhost/x", "https://u:p@a.com/x",
                    'https://a.com/x"onload=1', "javascript:alert(1)", "https://intranet/x"):
            self.assertIsNone(security.safe_https_url(bad), bad)
        self.assertEqual(security.clean_text("a\u202eb\x00  c\n\nd", 50), "ab c d")

    def test_rate_limit_and_penalty(self):
        rl = security.RateLimiter(0.0001, 3)
        self.assertEqual([rl.allow("k") for _ in range(5)], [True, True, True, False, False])
        p = security.Penalty(limit=3)
        for _ in range(3):
            p.strike("x")
        self.assertTrue(p.blocked("x"))


class FakeClient:
    def __init__(self, uid):
        self.uid, self.msgs = uid, []

    async def send(self, m):
        self.msgs.append(m)
        return True

    async def close(self):
        pass


class RoomTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import nox
        fake = types.ModuleType("nox.music")

        async def resolve(t):
            return None if t["title"] == "broken" else {"url": "https://cdn.example.com/" + t["title"] + ".mp3", "preview": False}
        fake.resolve = resolve
        nox.music = fake
        sys.modules["nox.music"] = fake
        from nox.rooms import Manager
        self.mgr = Manager()
        self.room = self.mgr.get(-100)

    def track(self, title, dur=100):
        return {"id": title, "title": title, "artist": "x", "dur": dur, "by": "u", "src": "g"}

    async def settle(self):
        for _ in range(10):
            await asyncio.sleep(0)

    async def test_flow(self):
        a, b = FakeClient(1), FakeClient(2)
        await self.room.join(a)
        await self.room.join(b)
        self.assertEqual(self.room.add(self.track("one")), "start")
        await self.settle()
        self.assertEqual(self.room.cur["title"], "one")
        self.assertEqual(self.room.add(self.track("two")), 1)
        self.room.add(self.track("broken"))
        self.room.add(self.track("three"))
        await self.settle()
        seq = self.room.seq
        await self.room.vote_end(1, seq)                 # too early: ignored
        self.assertEqual(self.room.cur["title"], "one")
        self.room.t0 -= 95                               # pretend 95 s passed
        await self.room.vote_end(1, seq)                 # 1 of 2 listeners: no majority yet
        self.assertEqual(self.room.cur["title"], "one")
        await self.room.vote_end(2, seq)                 # 2 of 2: song ends
        self.assertEqual(self.room.cur["title"], "two")

    async def test_skip_and_broken(self):
        self.room.add(self.track("one"))
        await self.settle()
        self.room.add(self.track("broken"))
        self.room.add(self.track("three"))
        await self.settle()
        await self.room.skip()
        self.assertEqual(self.room.cur["title"], "three")     # the broken one was skipped
        await self.room.skip()
        self.assertIsNone(self.room.cur)

    async def test_pause_resume_and_empty_room(self):
        a = FakeClient(1)
        await self.room.join(a)
        self.room.add(self.track("one"))
        await self.settle()
        await self.room.leave(a)                               # last listener leaves -> auto pause
        self.assertTrue(self.room.paused)
        await self.room.join(FakeClient(2))                    # someone returns -> auto resume
        self.assertFalse(self.room.paused)

    async def test_stale_reports_ignored(self):
        self.room.add(self.track("one"))
        await self.settle()
        await self.room.vote_end(1, self.room.seq - 1)
        await self.room.vote_bad(1, self.room.seq + 5)
        self.assertEqual(self.room.cur["title"], "one")


class NormalizeTests(unittest.TestCase):
    def test_shapes(self):
        sys.modules.pop("nox.music", None)
        sys.modules.setdefault("httpx", types.ModuleType("httpx"))
        from nox import music
        d = music.normalize({"id": 1, "title": "Song", "artist": {"name": "Art"}, "duration": 200,
                             "album": {"cover_big": "https://c.example.com/x.jpg"}, "preview": "https://p.example.com/p.mp3"}, "deezer")
        self.assertEqual((d["title"], d["artist"], d["dur"]), ("Song", "Art", 200))
        i = music.normalize({"trackName": "T", "artistName": "A", "trackTimeMillis": 215000,
                             "artworkUrl100": "https://a.example.com/100x100bb.jpg"}, "itunes")
        self.assertEqual((i["dur"], i["cover"].endswith("600x600bb.jpg")), (215, True))
        self.assertEqual(music._secs("4.7 min"), 282)
        self.assertEqual(music._secs("4:42"), 282)


if __name__ == "__main__":
    unittest.main()
