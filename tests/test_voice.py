import asyncio
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in dict(BOT_TOKEN="1:abc", PUBLIC_URL="https://x.example.com", PROXY_SECRET="p" * 32,
                 WEBHOOK_SECRET="w" * 32, OWNER_IDS="1").items():
    os.environ.setdefault(k, v)


class C:
    def __init__(self, uid):
        self.uid, self.msgs = uid, []
        self.name, self.photo, self.adm, self.joined = f"U{uid}", None, False, 1
        self.v = self.m = self.s = False

    async def send(self, m):
        self.msgs.append(m)
        return True


class VoiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from nox import main
        from nox.rooms import Manager
        self.main = main
        self.room = Manager().get(-5)
        self.a, self.b = C(10), C(11)
        self.room.clients = {10: self.a, 11: self.b}

    async def call(self, c, t, **js):
        js["t"] = t
        await self.main.handle(t, js, self.room, c, -5, c.uid, c.name)

    async def test_offer_needs_voice_flag(self):
        sdp = {"o": 1, "s": {"type": "offer", "sdp": "v=0"}}
        await self.call(self.a, "rtc", to=11, k="mic", d=sdp)
        self.assertEqual(self.b.msgs, [])                       # not in voice -> dropped
        await self.call(self.a, "vstate", v=1, m=0, s=0)
        await self.call(self.a, "rtc", to=11, k="mic", d=dict(sdp, evil="x"))
        self.assertEqual(self.b.msgs[0]["from"], 10)
        self.assertNotIn("evil", self.b.msgs[0]["d"])

    async def test_bad_targets_and_kinds(self):
        self.a.v = True
        d = {"o": 1, "s": {"type": "offer", "sdp": "v=0"}}
        for kw in (dict(to=99, k="mic"), dict(to=10, k="mic"), dict(to=11, k="video"), dict(to="11", k="mic")):
            await self.call(self.a, "rtc", d=d, **kw)
        self.assertEqual(self.b.msgs, [])
        await self.call(self.a, "rtc", to=11, k="mic", d={"o": 1, "c": {"candidate": "x" * 900}})
        self.assertEqual(self.b.msgs, [])

    async def test_limits(self):
        for i in range(self.main.MAX_SPEAKERS):
            c = C(100 + i)
            c.v = True
            self.room.clients[c.uid] = c
        await self.call(self.a, "vstate", v=1)
        self.assertEqual(self.a.msgs[-1]["t"], "vdeny")
        self.assertFalse(self.a.v)
        await self.call(self.b, "vstate", s=1)
        await self.call(self.a, "vstate", s=1)
        self.assertEqual(self.a.msgs[-1]["k"], "s")             # one screen share at a time
        self.assertTrue(self.b.s)

    async def test_people_after_flags(self):
        await self.call(self.a, "vstate", v=1, m=1)
        row = [r for r in self.room.people_msg()["list"] if r["id"] == 10][0]
        self.assertEqual((row["v"], row["m"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
