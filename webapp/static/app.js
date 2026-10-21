"use strict";
(function () {
  var tg = window.Telegram && window.Telegram.WebApp;
  var $ = function (id) { return document.getElementById(id); };
  var au = $("au");
  var ws = null, st = null, admin = false, off = 0, bestRtt = 1e9, localOff = false;
  var closing = false, dead = false, backoff = 1000, hb = null, searchTimer = null, prevQ = -1;

  function h(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function hap(k) { try { tg.HapticFeedback.impactOccurred(k || "light"); } catch (e) {} }
  function fmt(s) { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
  function send(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
  function nowS() { return Date.now() / 1000 + off; }
  function want() {
    if (!st || !st.track) return 0;
    return st.paused ? st.pos : st.pos + (nowS() - st.st);
  }
  var tt;
  function toast(x) {
    var e = $("toast");
    e.textContent = x; e.classList.add("show");
    clearTimeout(tt); tt = setTimeout(function () { e.classList.remove("show"); }, 2600);
  }
  function fatal(msg) {
    dead = true; $("fatalmsg").textContent = msg; $("fatal").hidden = false;
    try { if (ws) ws.close(); } catch (e) {}
    au.pause();
  }
  function cover(el, url, isArt) {
    if (url) {
      if (isArt) { el.style.setProperty("--cv", 'url("' + url + '")'); el.classList.add("cover"); }
      else el.style.backgroundImage = 'url("' + url + '")';
    } else if (isArt) { el.classList.remove("cover"); }
  }

  // ---------- Telegram chrome ----------
  try {
    tg.ready(); tg.expand();
    if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    if (tg.setHeaderColor) tg.setHeaderColor("#f7faff");
    if (tg.setBackgroundColor) tg.setBackgroundColor("#f7faff");
    tg.BackButton.show(); tg.BackButton.onClick(askLeave);
  } catch (e) {}

  // ---------- sheets ----------
  function sheet(build) {
    var c = $("sc"); c.replaceChildren(); build(c);
    $("sheet").hidden = false;
    requestAnimationFrame(function () { $("sheet").classList.add("open"); });
  }
  function closeSheet() {
    $("sheet").classList.remove("open");
    setTimeout(function () { $("sheet").hidden = true; }, 260);
  }
  $("sheetbg").onclick = closeSheet;
  function leave() {
    closing = true;
    try { if (ws) ws.close(); } catch (e) {}
    au.pause();
    if (tg) tg.close(); else window.close();
  }
  function askLeave() {
    sheet(function (c) {
      c.appendChild(h("h3", null, "Leave the room?"));
      c.appendChild(h("p", null, "Music stops on your phone. The room keeps playing for everyone else, and you can rejoin any time."));
      var b = h("div", "btns"), stay = h("button", null, "Stay"), go = h("button", "go", "Leave");
      stay.onclick = closeSheet; go.onclick = leave;
      b.appendChild(stay); b.appendChild(go); c.appendChild(b);
    });
  }
  $("back").onclick = askLeave;

  // ---------- audio sync ----------
  function seekTo(t) { try { if (au.readyState >= 1) au.currentTime = Math.max(0, t); } catch (e) {} }
  function play() {
    if (localOff || !st || st.paused) return;
    var p = au.play();
    if (p && p.catch) p.catch(function () { $("tap").hidden = false; });
  }
  $("tapbtn").onclick = function () { $("tap").hidden = true; localOff = false; seekTo(want()); play(); render(); };
  function loadTrack() {
    au.onloadedmetadata = function () {
      send({ t: "meta", seq: st.seq, dur: au.duration });
      seekTo(want()); play();
    };
    au.src = st.url;
  }
  function syncAudio() {
    if (!st || !st.track || !au.src) return;
    if (st.paused || localOff) { if (!au.paused) au.pause(); return; }
    if (au.paused && au.readyState >= 2 && $("tap").hidden) play();
    if (au.readyState >= 1 && Math.abs(au.currentTime - want()) > 0.7) seekTo(want());
  }
  au.onended = function () { if (st) send({ t: "ended", seq: st.seq }); };
  au.onerror = function () { if (st && st.track) send({ t: "bad", seq: st.seq }); };

  function onState(m) {
    var isNew = !st || st.seq !== m.seq;
    st = m;
    render();
    if (!m.track) { au.pause(); au.removeAttribute("src"); return; }
    if (isNew) loadTrack(); else syncAudio();
  }

  // ---------- render ----------
  function row(s, i, anim) {
    var r = h("div", "row glass" + (anim ? "" : " old"));
    r.style.setProperty("--i", i);
    var th = h("div", "thumb"); th.style.setProperty("--h", 206 + (i * 9) % 60); cover(th, s.cover, false);
    var t = h("div", "t"); t.appendChild(h("b", null, s.title));
    t.appendChild(h("span", null, s.artist + " – added by " + (s.by || "someone")));
    r.appendChild(th); r.appendChild(t);
    r.appendChild(h("div", "src" + (s.src === "g" ? " g" : ""), s.src === "g" ? "Group" : "App"));
    r.appendChild(h("em", null, s.dur ? fmt(s.dur) : ""));
    return r;
  }
  function render() {
    var t = st && st.track;
    $("title").textContent = t ? t.title : "Nothing playing";
    $("artist").textContent = t ? t.artist : "Add a song below or send /play in the group";
    var by = $("by"); by.hidden = !t;
    if (t) by.textContent = "added by " + (t.by || "someone") + (st.preview ? " (30 s preview)" : "");
    $("n").textContent = st ? st.n : 0;
    cover($("art"), t && t.cover, true);
    var paused = !t || st.paused || localOff;
    $("app").classList.toggle("paused", paused);
    var list = $("list"), q = st ? st.queue : [];
    list.replaceChildren();
    q.forEach(function (s, i) { list.appendChild(row(s, i, prevQ < 0 || i >= prevQ)); });
    if (st && st.qn > q.length) list.appendChild(h("div", "row glass more", "+" + (st.qn - q.length) + " more"));
    prevQ = q.length;
    $("qc").textContent = st && st.qn ? st.qn + (st.qn === 1 ? " song" : " songs") : "empty";
    ["shuf", "skip", "loop"].forEach(function (id) { $(id).classList.toggle("lock", !admin); });
    $("loop").classList.toggle("on", !!(st && st.loop));
    $("adm").hidden = !admin;
    media();
  }
  function draw() {
    if (!st || !st.track) { $("fill").style.setProperty("--p", "0%"); $("cur").textContent = "0:00"; $("dur").textContent = "0:00"; return; }
    var d = isFinite(au.duration) && au.duration > 0 ? au.duration : (st.track.dur || 0);
    var p = want();
    $("fill").style.setProperty("--p", (d ? Math.min(100, p / d * 100) : 0) + "%");
    $("cur").textContent = fmt(p); $("dur").textContent = d ? fmt(d) : "--:--";
  }
  function media() {
    try {
      if (!("mediaSession" in navigator) || !st || !st.track) return;
      navigator.mediaSession.metadata = new MediaMetadata({
        title: st.track.title, artist: st.track.artist,
        artwork: st.track.cover ? [{ src: st.track.cover, sizes: "512x512" }] : []
      });
    } catch (e) {}
  }
  setInterval(function () { syncAudio(); draw(); }, 500);
  document.addEventListener("visibilitychange", function () { if (!document.hidden) { syncAudio(); if (!ws || ws.readyState > 1) connect(); } });

  // ---------- controls ----------
  $("pp").onclick = function () {
    hap();
    if (!st || !st.track) return toast("Nothing is playing");
    if (admin) { send({ t: st.paused ? "resume" : "pause" }); return; }
    localOff = !localOff;                       // listeners can only mute themselves
    if (localOff) au.pause(); else { seekTo(want()); play(); }
    render();
  };
  function adminOnly(type) {
    return function () { hap(); if (!admin) return toast("Only group admins can do this"); send({ t: type }); };
  }
  $("skip").onclick = adminOnly("skip"); $("shuf").onclick = adminOnly("shuffle"); $("loop").onclick = adminOnly("loop");
  $("lyr").onclick = function () { hap(); send({ t: "lyrics" }); };

  // ---------- search / add ----------
  function closeResults() { $("res").classList.remove("open"); $("res").replaceChildren(); }
  $("q").oninput = function () {
    clearTimeout(searchTimer);
    var v = $("q").value.trim();
    if (v.length < 2) return closeResults();
    searchTimer = setTimeout(function () { send({ t: "search", q: v }); }, 400);
  };
  function onResults(m) {
    if (m.q !== $("q").value.trim()) return;
    var box = $("res"); box.replaceChildren();
    (m.items || []).slice(0, 6).forEach(function (it, i) {
      var b = h("button", "sg"), th = h("i", "thumb"), tx = h("span", "tx");
      th.style.setProperty("--h", 204 + i * 10); cover(th, it.cover, false);
      tx.appendChild(h("b", null, it.title)); tx.appendChild(h("small", null, it.artist));
      b.appendChild(th); b.appendChild(tx);
      b.onclick = function () { hap(); send({ t: "add", token: it.token }); $("q").value = ""; closeResults(); };
      box.appendChild(b);
    });
    box.classList.toggle("open", box.children.length > 0);
    if (!box.children.length) toast("No results");
  }
  function addFirst() { var b = $("res").querySelector(".sg"); if (b) b.click(); }
  $("addbtn").onclick = addFirst;
  $("q").addEventListener("keydown", function (e) { if (e.key === "Enter") addFirst(); });

  // ---------- network ----------
  function setConn(x) { $("conn").textContent = x || ""; }
  function handle(m) {
    switch (m.t) {
      case "hello":
        admin = !!m.admin; backoff = 1000; setConn(""); $("room").textContent = m.room || "live room";
        clearInterval(hb); send({ t: "ping", c: Date.now() });
        setTimeout(function () { send({ t: "ping", c: Date.now() }); }, 600);
        hb = setInterval(function () { send({ t: "ping", c: Date.now() }); }, 20000);
        break;
      case "state": onState(m); break;
      case "pong":
        var rtt = Date.now() - m.c;
        if (rtt <= bestRtt + 30) { bestRtt = Math.min(bestRtt, rtt); off = m.st - (Date.now() - rtt / 2) / 1000; }
        if (admin !== !!m.adm) { admin = !!m.adm; render(); }
        break;
      case "results": onResults(m); break;
      case "ok": toast(m.m); break;
      case "err": toast(m.m); break;
      case "lyrics":
        sheet(function (c) {
          c.appendChild(h("h3", null, m.title || "Lyrics"));
          if (m.text) c.appendChild(h("pre", null, m.text)); else c.appendChild(h("p", null, "No lyrics found for this song."));
        });
        break;
      case "fatal": fatal(m.m); break;
    }
  }
  function connect() {
    if (dead || closing) return;
    setConn(backoff > 1000 ? "Reconnecting…" : "Connecting…");
    ws = new WebSocket("wss://" + location.host + "/ws");
    ws.onopen = function () { send({ t: "auth", initData: tg.initData }); };
    ws.onmessage = function (e) { var m; try { m = JSON.parse(e.data); } catch (x) { return; } handle(m); };
    ws.onclose = function () {
      clearInterval(hb);
      if (dead || closing) return;
      setConn("Reconnecting…");
      setTimeout(connect, backoff); backoff = Math.min(backoff * 1.6, 10000);
    };
  }
  if (!tg || !tg.initData) fatal("Open this room from the pinned message in your Telegram group.");
  else connect();
})();
