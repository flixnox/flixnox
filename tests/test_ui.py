import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k, v in dict(BOT_TOKEN="1:abc", PUBLIC_URL="https://x.example.com", PROXY_SECRET="p" * 32,
                 WEBHOOK_SECRET="w" * 32, OWNER_IDS="1").items():
    os.environ.setdefault(k, v)

from nox import ui  # noqa: E402


def room(**kw):
    r = types.SimpleNamespace(cur=None, paused=False, loop=False, autoplay=False, queue=[], clients={})
    r.__dict__.update(kw)
    return r


def trk(i, title="Song", artist="Artist"):
    return {"title": f"{title} {i}", "artist": artist, "dur": 200, "by": "Sam"}


class UiTests(unittest.TestCase):
    def test_caption_limits(self):
        long = trk(0, "T" * 300, "A" * 300)
        long["by"] = "B" * 300
        for r in (room(), room(cur=trk(1)), room(cur=long, paused=True, loop=True, autoplay=True,
                                                 queue=[trk(i, "Q" * 200, "Z" * 100) for i in range(30)],
                                                 clients={1: 1, 2: 2})):
            c = ui.panel_caption(r)
            self.assertLessEqual(len(c), 1024)
            self.assertEqual(c.count("<blockquote>"), c.count("</blockquote>"))

    def test_callbacks_kept(self):
        rows = ui.panel_kb(-100, room(cur=trk(1))).inline_keyboard
        got = {b.callback_data for r in rows for b in r if b.callback_data}
        self.assertEqual(got, {"pp", "sk", "q", "lp", "sh", "ap", "inv", "st"})
        self.assertTrue(all(len(r) <= 3 for r in rows))

    def test_texts(self):
        self.assertIn(ui.tc("starting now"), ui.added_text(trk(1), "start", "Sam"))
        self.assertLessEqual(len(ui.WELCOME.format(name="N" * 30)), 1024)
        self.assertIn("/invite", ui.HELP)
        self.assertEqual(ui.tc("welcome to sonic nox"), "Wᴇʟᴄᴏᴍᴇ Tᴏ Sᴏɴɪᴄ Nᴏx")
        w = ui.welcome_kb().inline_keyboard
        self.assertEqual(w[0][0].style, "success")
        self.assertIn("Aᴅᴅ Tᴏ Gʀᴏᴜᴘ", w[0][0].text)
        self.assertIn("Qᴜᴇᴜᴇ", ui.queue_text(room(cur=trk(1), queue=[trk(2)])))


if __name__ == "__main__":
    unittest.main()
