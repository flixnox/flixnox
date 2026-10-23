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

    async def test_private_player_waits_for_its_listener(self):
        solo = self.mgr.get(555)                       # positive id = a user's private player
        solo.add(self.track("one"))
        await self.settle()
        self.assertEqual(solo.cur["title"], "one")
        self.assertTrue(solo.paused)                   # nobody has opened the Mini App yet: it waits at 0:00
        a = FakeClient(555)
        await solo.join(a)
        self.assertFalse(solo.paused)                  # opening the Mini App starts the song
        await solo.leave(a)
        self.assertTrue(solo.paused)                   # leaving pauses it again
        self.assertEqual(round(solo.position()), 0)

    async def test_group_room_keeps_running_when_empty(self):
        a = FakeClient(1)
        await self.room.join(a)
        self.room.add(self.track("one"))
        await self.settle()
        await self.room.leave(a)
        self.assertFalse(self.room.paused)             # a group room runs until /end

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

    async def test_empty_room_keeps_running(self):
        a = FakeClient(1)
        await self.room.join(a)
        self.room.add(self.track("one"))
        await self.settle()
        await self.room.leave(a)                               # everyone left: the room goes on until /end
        self.assertFalse(self.room.paused)
        self.assertEqual(self.room.cur["title"], "one")

    async def test_autoplay_stops_after_three_in_an_empty_room(self):
        n = 0

        async def related(cur, played):
            nonlocal n
            n += 1
            return [self.track(f"auto{n}")]
        sys.modules["nox.music"].related = related
        self.room.autoplay = True
        self.room.add(self.track("one"))
        await self.settle()
        for _ in range(6):
            await self.room._finish(self.room.seq)
        self.assertIsNone(self.room.cur)                       # nobody listening -> stopped after ~3 songs
        self.assertLessEqual(self.room.empty_plays, 3)
        a = FakeClient(1)
        await self.room.join(a)
        self.room.add(self.track("two"))
        await self.settle()
        await self.room._finish(self.room.seq)
        self.assertIsNotNone(self.room.cur)                    # with a listener autoplay keeps going

    async def test_next_song_is_prefetched(self):
        from nox.rooms import Room
        self.room.add(self.track("one"))
        self.room.add(self.track("two"))
        await self.settle()
        await asyncio.sleep(0.05)
        nxt = self.room.queue[0]
        self.assertIsNotNone(Room._fresh(nxt))                     # resolved in the background
        self.assertEqual(self.room.state()["nxt"], Room._fresh(nxt)["url"])
        url = Room._fresh(nxt)["url"]
        await self.room._finish(self.room.seq)
        self.assertEqual(self.room.url, url)                       # the change used the ready URL
        self.assertNotIn("_r", self.room.cur)

    async def test_people_list(self):
        a = FakeClient(1)
        a.name, a.photo, a.adm, a.v, a.m, a.s = "Zed", None, True, True, True, False
        b = FakeClient(2)
        b.name, b.photo, b.adm, b.v, b.m, b.s = "Amy", None, False, False, False, False
        await self.room.join(b)
        await self.room.join(a)
        msg = self.room.people_msg()
        self.assertEqual([r["id"] for r in msg["list"]], [1, 2])      # voice users first
        self.assertEqual(msg["n"], 2)

    async def test_stale_reports_ignored(self):
        self.room.add(self.track("one"))
        await self.settle()
        await self.room.vote_end(1, self.room.seq - 1)
        await self.room.vote_bad(1, self.room.seq + 5)
        self.assertEqual(self.room.cur["title"], "one")


SAMPLE_SONG = {
    "id": "3IoDK8qI", "name": "Kesariya (From &quot;Brahmastra&quot;)", "type": "song", "year": "2022", "duration": 268,
    "album": {"id": "1", "name": "Brahmastra"},
    "artists": {"primary": [{"id": "459320", "name": "Arijit Singh"}, {"id": "2", "name": "Pritam"}], "featured": [], "all": []},
    "image": [{"quality": "50x50", "url": "http://c.saavncdn.com/x-50x50.jpg"}, {"quality": "500x500", "url": "https://c.saavncdn.com/x-500x500.jpg"}],
    "downloadUrl": [{"quality": "96kbps", "url": "https://aac.saavncdn.com/a_96.mp4"},
                    {"quality": "160kbps", "url": "http://aac.saavncdn.com/a_160.mp4"},
                    {"quality": "320kbps", "url": "https://aac.saavncdn.com/a_320.mp4"}],
}


class MusicTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import importlib
        import nox
        sys.modules.pop("nox.music", None)
        if hasattr(nox, "music"):
            delattr(nox, "music")
        sys.modules.setdefault("httpx", types.ModuleType("httpx"))      # network is never touched in these tests
        music = importlib.import_module("nox.music")        # the real module, not the fake used by the room tests
        self.music = music
        music.clear_caches()

    def test_song_parsing(self):
        m = self.music
        s = m.song(SAMPLE_SONG)
        self.assertEqual(s["title"], 'Kesariya (From "Brahmastra")')           # HTML entities cleaned
        self.assertEqual(s["artist"], "Arijit Singh, Pritam")
        self.assertEqual((s["dur"], s["album"], s["sid"]), (268, "Brahmastra", "3IoDK8qI"))
        self.assertTrue(s["cover"].endswith("500x500.jpg"))
        self.assertEqual(m.pick_url(s), "https://aac.saavncdn.com/a_160.mp4")   # 160 kbps preferred, http upgraded to https
        self.assertEqual(m.pick_url(s, 320), "https://aac.saavncdn.com/a_320.mp4")
        self.assertEqual(m.pick_url(s, 12), "https://aac.saavncdn.com/a_96.mp4")  # nothing lower: closest above
        self.assertIsNone(m.song({"id": "1"}))
        self.assertIsNone(m.song("nope"))

    async def test_search_and_artists(self):
        m = self.music
        calls = []

        async def fake_api(name, path, params=None, base=None, timeout=7.0):
            calls.append(path)
            if path == "/search/songs":
                return {"success": True, "data": {"results": [SAMPLE_SONG, SAMPLE_SONG]}}      # duplicate gets removed
            if path == "/search/artists":
                return {"success": True, "data": {"results": [{"id": "9", "name": "Arijit Singh", "image": [{"quality": "150x150", "url": "https://c.saavncdn.com/a-150x150.jpg"}]}]}}
            return None
        m._api = fake_api
        songs, artists = await m.search_all("arijit singh", 10, 4)
        self.assertEqual(len(songs), 1)
        self.assertEqual(artists[0]["name"], "Arijit Singh")
        self.assertTrue(artists[0]["cover"].endswith("500x500.jpg"))
        await m.search_all("arijit singh", 10, 4)                                          # second call comes from cache
        self.assertEqual(len(calls), 2)
        tok = m.stash(7, songs)[0]["token"]
        self.assertIsNone(m.take(tok, 8))                                                  # other users cannot use my token
        self.assertEqual(m.take(tok, 7)["sid"], "3IoDK8qI")
        r = await m.resolve(songs[0])
        self.assertTrue(r["url"].startswith("https://aac.saavncdn.com/"))

    async def test_fallback_global_search(self):
        m = self.music

        async def fake_api(name, path, params=None, base=None, timeout=7.0):
            if path == "/search":
                return {"success": True, "data": {"songs": {"results": [SAMPLE_SONG]}}}
            return {"success": False}
        m._api = fake_api
        songs, _ = await m.search_all("anything", 5, 0)
        self.assertEqual(len(songs), 1)


class AutoplayTests(unittest.IsolatedAsyncioTestCase):
    async def test_autoplay_refills_queue(self):
        import nox
        fake = types.ModuleType("nox.music")

        async def resolve(t):
            return {"url": "https://cdn.example.com/" + t["title"] + ".mp3", "preview": False}

        async def related(track, exclude=()):
            return [{"id": "r1", "title": "similar", "artist": "x", "dur": 100, "cover": None}]
        fake.resolve, fake.related = resolve, related
        nox.music = fake
        sys.modules["nox.music"] = fake
        from nox.rooms import Manager
        room = Manager().get(-200)
        await room.toggle_autoplay()
        room.add({"id": "a", "title": "one", "artist": "x", "dur": 100, "by": "u", "src": "g"})
        for _ in range(10):
            await asyncio.sleep(0)
        await room.skip()                                            # queue is empty -> autoplay picks a similar song
        for _ in range(10):
            await asyncio.sleep(0)
        self.assertEqual(room.cur["title"], "similar")
        self.assertEqual(room.cur["src"], "auto")


if __name__ == "__main__":
    unittest.main()
