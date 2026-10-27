"""Offline tests for the YouTube / Shruti sources and the signed stream proxy.  Run:  python -m unittest discover -s tests"""
import asyncio
import os
import sys
import time
import unittest
from urllib.parse import parse_qs, urlsplit

os.environ.update(BOT_TOKEN="123:TEST", PUBLIC_URL="https://w.example.workers.dev", OWNER_IDS="1",
                  PROXY_SECRET="p" * 32, WEBHOOK_SECRET="w" * 32)
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from nox import music, stream  # noqa: E402

GV = "https://rr1---sn-abc.googlevideo.com/videoplayback?id=1&sig=2"


def run(coro):
    return asyncio.run(coro)


class StreamTests(unittest.TestCase):
    def test_signed_link_roundtrip(self):
        link = stream.proxy_url(GV)
        q = parse_qs(urlsplit(link).query)
        self.assertEqual(q["url"][0], GV)
        self.assertEqual(q["sig"][0], stream._sig(GV, int(q["exp"][0])))
        self.assertEqual(stream.unwrap(link), GV)

    def test_signature_is_bound_to_url_and_expiry(self):
        exp = int(time.time()) + 100
        self.assertNotEqual(stream._sig(GV, exp), stream._sig(GV + "x", exp))
        self.assertNotEqual(stream._sig(GV, exp), stream._sig(GV, exp + 1))

    def test_only_youtube_https_hosts(self):
        self.assertTrue(stream.allowed(GV))
        for bad in ("http://rr1.googlevideo.com/x", "https://evil.com/googlevideo.com", "https://googlevideo.com.evil.com/x",
                    "https://127.0.0.1/x", "ftp://x.googlevideo.com/", ""):
            self.assertFalse(stream.allowed(bad), bad)

    def test_unwrap_ignores_foreign_links(self):
        self.assertIsNone(stream.unwrap("https://other.example.com/api/ytstream?url=" + GV))
        self.assertIsNone(stream.unwrap("https://w.example.workers.dev/api/ytstream?url=https%3A%2F%2Fevil.com%2Fx"))


class ParsingTests(unittest.TestCase):
    def test_yt_track(self):
        vr = {"videoId": "dQw4w9WgXcQ", "title": {"runs": [{"text": "Never Gonna "}, {"text": "Give You Up"}]},
              "lengthText": {"simpleText": "3:33"}, "ownerText": {"runs": [{"text": "Rick Astley - Topic"}]}}
        t = music._yt_track(vr)
        self.assertEqual((t["id"], t["sid"], t["prov"], t["dur"]), ("yt:dQw4w9WgXcQ", "dQw4w9WgXcQ", "yt", 213))
        self.assertEqual((t["title"], t["artist"]), ("Never Gonna Give You Up", "Rick Astley"))
        self.assertTrue(t["cover"].startswith("https://i.ytimg.com/"))

    def test_yt_track_rejects_live_and_bad_ids(self):
        self.assertIsNone(music._yt_track({"videoId": "dQw4w9WgXcQ", "title": {"runs": [{"text": "Live"}]}}))
        self.assertIsNone(music._yt_track({"videoId": "../../x", "title": {"runs": [{"text": "x"}]}, "lengthText": {"simpleText": "1:00"}}))

    def test_best_audio_prefers_m4a_near_wanted_bitrate(self):
        fm = {"adaptiveFormats": [
            {"mimeType": 'audio/webm; codecs="opus"', "bitrate": 160000, "url": "https://a.googlevideo.com/webm"},
            {"mimeType": 'audio/mp4; codecs="mp4a.40.2"', "bitrate": 130000, "url": "https://a.googlevideo.com/m4a128"},
            {"mimeType": 'audio/mp4; codecs="mp4a.40.5"', "bitrate": 50000, "url": "https://a.googlevideo.com/m4a48"},
            {"mimeType": "video/mp4", "bitrate": 900000, "url": "https://a.googlevideo.com/video"},
            {"mimeType": 'audio/mp4; codecs="mp4a.40.2"', "bitrate": 250000, "signatureCipher": "x"}]}
        self.assertEqual(music._yt_best_audio(fm), "https://a.googlevideo.com/m4a128")

    def test_shruti_track_is_tolerant(self):
        t = music._shruti_track({"id": 7, "title": "Song", "artists": [{"name": "A"}, {"name": "B"}], "duration": "200"})
        self.assertEqual((t["id"], t["prov"], t["artist"], t["dur"]), ("sh:7", "shruti", "A, B", 200))
        self.assertIsNone(music._shruti_track({"title": "no id"}))
        self.assertEqual(len(music._shruti_rows({"data": {"results": [{"id": 1}, "junk"]}})), 1)


class FlowTests(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(music, k) for k in ("_songs", "_artists", "_yt_search", "_yt_resolve", "_resolve_saavn")}
        music._SEARCH.clear()
        music._YT.clear()

    def tearDown(self):
        for k, v in self._saved.items():
            setattr(music, k, v)

    def test_search_falls_back_to_youtube_when_jiosaavn_is_empty(self):
        async def empty(*a, **k):
            return []

        async def yt(q, n=10):
            return [{"id": "yt:abcdefghijk", "sid": "abcdefghijk", "prov": "yt", "title": "T", "artist": "C", "dur": 100, "cover": None, "aud": {}}]
        music._songs, music._artists, music._yt_search = empty, empty, yt
        songs, artists = run(music.search_all("anything goes", 5, 0))
        self.assertEqual([s["prov"] for s in songs], ["yt"])

    def test_resolve_yt_wraps_the_link_in_the_signed_proxy(self):
        async def fake(vid):
            return GV
        music._yt_resolve = fake
        r = run(music.resolve({"id": "yt:abcdefghijk", "sid": "abcdefghijk", "prov": "yt", "cover": "c"}))
        self.assertTrue(r["url"].startswith("https://w.example.workers.dev/api/ytstream?url="))
        self.assertFalse(r["preview"])

    def test_failed_saavn_track_is_retried_on_youtube_and_remembered(self):
        async def nope(t):
            return None

        async def yt(q, n=10):
            return [{"id": "yt:abcdefghijk", "sid": "abcdefghijk", "prov": "yt", "title": "T", "artist": "C", "dur": 200, "cover": "c", "aud": {}}]

        async def fake(vid):
            return GV
        music._resolve_saavn, music._yt_search, music._yt_resolve = nope, yt, fake
        track = {"id": "js:1", "sid": "1", "prov": "saavn", "title": "T", "artist": "C", "dur": 205}
        r = run(music.resolve(track))
        self.assertIsNotNone(r)
        self.assertEqual((track["prov"], track["sid"]), ("yt", "abcdefghijk"))

    def test_resolve_never_raises(self):
        async def boom(t):
            raise RuntimeError("x")
        music._resolve_saavn = boom
        self.assertIsNone(run(music.resolve({"id": "js:1", "sid": "1", "prov": "saavn", "title": "a", "artist": "b"})))


if __name__ == "__main__":
    unittest.main()
