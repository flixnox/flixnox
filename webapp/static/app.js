"use strict";
(function () {
  const tg = window.Telegram && window.Telegram.WebApp;
  const $ = (id) => document.getElementById(id);
  const au = $("au"), pre = new Audio();
  pre.preload = "none";
  const TABS = ["now", "search", "queue", "people"];
  const TAGS = [["Arijit Singh", "c-blue"], ["Lo-fi chill", "c-violet"], ["Punjabi hits", "c-mint"], ["Shreya Ghoshal", "c-sky"],
    ["Taylor Swift", "c-amber"], ["Diljit Dosanjh", "c-teal"], ["Old is gold", "c-violet"], ["Gym workout", "c-blue"]];

  let ws = null, st = null, admin = false, roomLink = "", meId = 0, ice = [{ urls: ["stun:stun.l.google.com:19302"] }], off = 0, bestRtt = 1e9, localOff = false;
  let closing = false, dead = false, backoff = 1000, hb = null, tab = "now", searchTimer = null;
  let reqId = 0, lastReq = null, badSent = -1, nxtUrl = "", lyrOpen = false, qsig = "", lastCover = "", hinted = false;
  const cache = new Map(), pending = [];

  // ---------- tiny helpers ----------
  function h(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function ico(name) {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"), u = document.createElementNS("http://www.w3.org/2000/svg", "use");
    s.setAttribute("class", "i"); u.setAttribute("href", "#i-" + name); s.appendChild(u);
    return s;
  }
  const cssUrl = (u) => 'url("' + String(u).replace(/["\\\n\r]/g, "") + '")';
  function bg(el, url) { if (url) el.style.backgroundImage = cssUrl(url); }
  function hap(k) { try { tg.HapticFeedback.impactOccurred(k || "light"); } catch (e) {} }
  function fmt(s) { s = Math.max(0, Math.floor(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); }
  function send(o) { if (ws && ws.readyState === 1) { ws.send(JSON.stringify(o)); return true; } return false; }
  const nowS = () => Date.now() / 1000 + off;
  function want() { return !st || !st.track ? 0 : (st.paused ? st.pos : st.pos + (nowS() - st.st)); }
  let tt;
  function toast(x, kind) {
    const e = $("toast");
    e.dataset.k = kind || "info"; $("toastx").textContent = x; e.classList.add("show");
    clearTimeout(tt); tt = setTimeout(() => e.classList.remove("show"), 2600);
  }
  function fatal(msg) {
    dead = true; $("fatalmsg").textContent = msg; $("fatal").hidden = false;
    try { if (tg && tg.disableClosingConfirmation) tg.disableClosingConfirmation(); } catch (e) {}
    try { if (ws) ws.close(); } catch (e) {}
    au.pause();
  }

  // ---------- Telegram chrome ----------
  try {
    tg.ready(); tg.expand();
    if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
    if (tg.setHeaderColor) tg.setHeaderColor("#f4f8ff");
    if (tg.setBackgroundColor) tg.setBackgroundColor("#f4f8ff");
    if (tg.setBottomBarColor) tg.setBottomBarColor("#f4f8ff");
    tg.BackButton.show(); tg.BackButton.onClick(goBack);
    if (tg.enableClosingConfirmation) tg.enableClosingConfirmation();      // a stray swipe or back can't drop you out of the room
  } catch (e) {}

  // ---------- sheets ----------
  function sheet(build) {
    const c = $("sc"); c.replaceChildren(); build(c);
    $("sheet").hidden = false;
    requestAnimationFrame(() => $("sheet").classList.add("open"));
  }
  function closeSheet() {
    lyrOpen = false; $("sheet").classList.remove("open");
    setTimeout(() => { if (!$("sheet").classList.contains("open")) $("sheet").hidden = true; }, 380);
  }
  $("sheetbg").onclick = closeSheet;
  function confirmSheet(title, text, yesLabel, color, onYes, noLabel) {
    sheet((c) => {
      c.appendChild(h("h3", null, title)); c.appendChild(h("p", null, text));
      const b = h("div", "btns"), no = h("button", "bx c-blue", noLabel || "Cancel"), go = h("button", "bx " + color, yesLabel);
      no.onclick = closeSheet;
      go.onclick = () => { closeSheet(); onYes(); };
      b.append(no, go); c.appendChild(b);
    });
  }
  function leave() {
    closing = true;
    try { if (ws) ws.close(); } catch (e) {}
    au.pause();
    if (tg) tg.close(); else window.close();
  }
  function askLeave() {
    hap();
    confirmSheet("Leave the room?", "Music stops on your phone. The room keeps playing for everyone else, and you can rejoin any time.", "Leave", "c-rose", leave, "Stay");
  }
  function goBack() { if (dead) return leave(); if (!$("sheet").hidden) closeSheet(); else if (tab !== "now") setTab("now"); else askLeave(); }
  $("back").onclick = goBack;
  $("fclose").onclick = leave;
  $("fretry").onclick = () => location.reload();

  // ---------- invite ----------
  $("inv").onclick = () => {
    hap();
    sheet((c) => {
      c.appendChild(h("h3", null, "Invite to the room"));
      c.appendChild(h("p", null, "Ping the whole group with a Join button, or share the room link with someone in this group."));
      const b = h("div", "btns"), grp = h("button", "bx c-blue", "Notify group"), shr = h("button", "bx c-teal", "Share link");
      grp.onclick = () => { closeSheet(); if (!send({ t: "invite" })) toast("Reconnecting… try again", "err"); };
      shr.onclick = () => {
        closeSheet();
        if (!roomLink) return toast("Link isn't ready yet. Try again.", "err");
        const u = "https://t.me/share/url?url=" + encodeURIComponent(roomLink) + "&text=" + encodeURIComponent("Join me in the Nox Room \uD83C\uDFA7");
        try { if (tg && tg.openTelegramLink) return tg.openTelegramLink(u); } catch (e) {}
        window.open(u, "_blank");
      };
      b.append(grp, shr); c.appendChild(b);
    });
  };

  // ---------- people + voice (audio and screen go peer to peer between members, the server only relays the handshake) ----------
  let people = [];
  const voice = { on: false, muted: false, share: false };
  let micStream = null, scrStream = null, actx = null;
  const out = new Map(), inc = new Map(), pendIn = new Map(), levels = new Map(), speaking = new Set();
  const hue = (id) => (Math.abs(id | 0) * 47) % 360;
  function vstate() { send({ t: "vstate", v: voice.on ? 1 : 0, m: voice.muted ? 1 : 0, s: voice.share ? 1 : 0 }); }
  function rtcSend(to, k, d) { send({ t: "rtc", to: to, k: k, d: d }); }
  function dropOut(key) { const r = out.get(key); if (!r) return; out.delete(key); try { r.pc.close(); } catch (e) {} }
  function dropIn(key) {
    const r = inc.get(key); pendIn.delete(key);
    const k = key.split(":")[0], u = key.split(":")[1];
    if (r) { inc.delete(key); try { r.pc.close(); } catch (e) {} }
    if (k === "mic") { const el = document.getElementById("ra-" + u); if (el) el.remove(); levels.delete("u" + u); }
    else { $("scr").srcObject = null; $("stage").hidden = !scrStream; }
  }
  function flush(r) { r.ready = true; const q = r.q; r.q = []; q.forEach((c) => r.pc.addIceCandidate(c).catch(() => {})); }
  async function startOut(k, uid, stream, j) {
    const key = k + ":" + uid, old = out.get(key);
    if (old && old.j === j) return;
    if (old) dropOut(key);
    const pc = new RTCPeerConnection({ iceServers: ice }), rec = { pc: pc, q: [], ready: false, j: j };
    out.set(key, rec);
    stream.getTracks().forEach((t) => pc.addTrack(t, stream));
    pc.onicecandidate = (e) => { if (e.candidate) rtcSend(uid, k, { o: 1, c: e.candidate.toJSON() }); };
    pc.onconnectionstatechange = () => { if (pc.connectionState === "failed" || pc.connectionState === "closed") dropOut(key); };
    try {
      const off = await pc.createOffer(); await pc.setLocalDescription(off);
      rtcSend(uid, k, { o: 1, s: { type: "offer", sdp: pc.localDescription.sdp } });
      if (k === "scr") pc.getSenders().forEach((sn) => {
        if (sn.track && sn.track.kind === "video") { try { const p = sn.getParameters(); if (!p.encodings || !p.encodings.length) p.encodings = [{}]; p.encodings[0].maxBitrate = 700000; sn.setParameters(p).catch(() => {}); } catch (e) {} }
      });
    } catch (e) { dropOut(key); }
  }
  async function onRtc(m) {
    const f = m.from, k = m.k, d = m.d || {}, key = k + ":" + f;
    try {
      if (d.o) {                                          // from the sender -> my incoming connection
        if (d.s && d.s.type === "offer") {
          dropIn(key);
          const pc = new RTCPeerConnection({ iceServers: ice }), rec = { pc: pc, q: pendIn.get(key) || [], ready: false };
          pendIn.delete(key); inc.set(key, rec);
          pc.onicecandidate = (e) => { if (e.candidate) rtcSend(f, k, { o: 0, c: e.candidate.toJSON() }); };
          pc.ontrack = (e) => attachRemote(k, f, e);
          pc.onconnectionstatechange = () => { if (pc.connectionState === "failed" || pc.connectionState === "closed") dropIn(key); };
          await pc.setRemoteDescription(d.s); flush(rec);
          const ans = await pc.createAnswer(); await pc.setLocalDescription(ans);
          rtcSend(f, k, { o: 0, s: { type: "answer", sdp: pc.localDescription.sdp } });
        } else if (d.c) {
          const r = inc.get(key);
          if (!r) { const q = pendIn.get(key) || []; q.push(d.c); pendIn.set(key, q.slice(-40)); }
          else if (r.ready) r.pc.addIceCandidate(d.c).catch(() => {}); else r.q.push(d.c);
        }
      } else {                                            // from a receiver -> my outgoing connection
        const r = out.get(key); if (!r) return;
        if (d.s && d.s.type === "answer") { await r.pc.setRemoteDescription(d.s); flush(r); }
        else if (d.c) { if (r.ready) r.pc.addIceCandidate(d.c).catch(() => {}); else r.q.push(d.c); }
      }
    } catch (e) { dropIn(key); dropOut(key); }
  }
  function attachRemote(k, f, e) {
    const stream = (e.streams && e.streams[0]) || new MediaStream([e.track]);
    if (k === "mic") {
      let el = document.getElementById("ra-" + f);
      if (!el) { el = document.createElement("audio"); el.id = "ra-" + f; el.autoplay = true; el.setAttribute("playsinline", ""); $("remote").appendChild(el); }
      el.srcObject = stream; const p = el.play(); if (p && p.catch) p.catch(() => { $("tap").hidden = false; });
      watchLevel("u" + f, stream, f);
    } else {
      const v = $("scr"); v.srcObject = stream; $("stage").hidden = false; v.play().catch(() => {});
      const p = people.find((x) => x.id === f); $("stagetag").textContent = (p ? p.n : "someone") + " is sharing";
    }
  }
  function unlockRemote() { document.querySelectorAll("#remote audio").forEach((a) => a.play().catch(() => {})); const v = $("scr"); if (v.srcObject) v.play().catch(() => {}); }
  function watchLevel(id, stream, uid) {                  // who is talking right now (green ring)
    try {
      actx = actx || new (window.AudioContext || window.webkitAudioContext)();
      const an = actx.createAnalyser(); an.fftSize = 256; actx.createMediaStreamSource(stream).connect(an);
      levels.set(id, { an: an, uid: uid || meId, buf: new Uint8Array(an.fftSize) });
    } catch (e) {}
  }
  setInterval(() => {
    let changed = false;
    levels.forEach((l, id) => {
      l.an.getByteTimeDomainData(l.buf); let s = 0;
      for (let i = 0; i < l.buf.length; i++) { const x = (l.buf[i] - 128) / 128; s += x * x; }
      const on = Math.sqrt(s / l.buf.length) > 0.04 && !(l.uid === meId && voice.muted);
      if (on !== speaking.has(l.uid)) { on ? speaking.add(l.uid) : speaking.delete(l.uid); changed = true; }
    });
    if (changed) document.querySelectorAll(".av[data-u]").forEach((e) => e.classList.toggle("speaking", speaking.has(+e.dataset.u)));
  }, 200);

  function syncVoice() {
    const ids = new Set(people.map((p) => p.id));
    [["mic", micStream, voice.on], ["scr", scrStream, voice.share]].forEach((a) => {
      const k = a[0], stream = a[1], on = a[2];
      if (on && stream) people.forEach((p) => { if (p.id !== meId) startOut(k, p.id, stream, p.j); });
      [...out.keys()].forEach((key) => { const u = +key.split(":")[1]; if (key.startsWith(k + ":") && (!on || !ids.has(u))) dropOut(key); });
    });
    [...inc.keys()].forEach((key) => {
      const p = people.find((x) => x.id === +key.split(":")[1]);
      if (!p || (key.startsWith("mic:") ? !p.v : !p.s)) dropIn(key);
    });
    if (!people.some((p) => p.s) && !scrStream) { $("scr").srcObject = null; $("stage").hidden = true; }
  }
  setInterval(() => { if (voice.on || voice.share) syncVoice(); }, 6000);       // retry failed links
  function onReconnect() { out.forEach((r, k) => dropOut(k)); if (voice.on || voice.share) vstate(); }
  function resumeVoice() { if (micStream) micStream.getAudioTracks().forEach((t) => { t.enabled = !voice.muted; }); unlockRemote(); }
  function onPeople(m) {
    people = m.list || [];
    $("pc").textContent = (m.n || people.length) + (m.n === 1 ? " listener" : " listeners");
    const live = people.filter((p) => p.v).length, pb = $("pb"); pb.hidden = !live; pb.textContent = live;
    renderPeople(); syncVoice();
  }
  function renderPeople() {
    const list = $("plist"); list.replaceChildren();
    people.forEach((p, i) => {
      const r = h("div", "prow glass"); r.style.setProperty("--i", Math.min(i, 10));
      const av = h("div", "av", (p.n || "?").trim().charAt(0).toUpperCase() || "?"); av.style.setProperty("--h", hue(p.id)); av.dataset.u = p.id;
      if (p.p) bg(av, p.p);
      if (speaking.has(p.id)) av.classList.add("speaking");
      r.appendChild(av);
      const t = h("div", "pn"); t.appendChild(h("b", "keep", p.n + (p.id === meId ? " (you)" : "")));
      t.appendChild(h("span", null, p.s ? "sharing screen" : p.v ? (p.m ? "muted" : "in voice") : p.a ? "admin" : "listening"));
      r.appendChild(t);
      const ic = h("div", "pic");
      if (p.s) { const e = h("i", "c-violet"); e.appendChild(ico("screen")); ic.appendChild(e); }
      if (p.v) { const e = h("i", p.m ? "c-rose" : "c-mint"); e.appendChild(ico(p.m ? "micoff" : "mic")); ic.appendChild(e); }
      if (admin && p.v && !p.m && p.id !== meId) {
        const x = h("button", "mx"); x.appendChild(ico("micoff")); x.setAttribute("aria-label", "Mute"); x.onclick = () => { hap(); send({ t: "vmute", to: p.id }); toast("Muted " + p.n, "ok"); };
        ic.appendChild(x);
      }
      r.appendChild(ic); list.appendChild(r);
    });
    renderVoice();
  }
  function renderVoice() {
    $("v-join").hidden = voice.on; $("v-mute").hidden = !voice.on; $("v-leave").hidden = !voice.on;
    const m = $("v-mute"); m.classList.toggle("off", voice.muted);
    m.querySelector("span").textContent = voice.muted ? "unmute" : "mute";
    m.querySelector("use").setAttribute("href", voice.muted ? "#i-micoff" : "#i-mic");
    const sh = $("v-share"); sh.hidden = false; sh.classList.toggle("off", !voice.share); sh.classList.toggle("c-rose", voice.share); sh.classList.toggle("c-violet", !voice.share);
    sh.querySelector("span").textContent = voice.share ? "stop share" : "share";
  }
  function setMute(on) {
    voice.muted = on;
    if (micStream) micStream.getAudioTracks().forEach((t) => { t.enabled = !on; });
    vstate(); renderVoice();
  }
  async function joinVoice() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return toast("Voice isn't supported on this device", "err");
    try { micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }); }
    catch (e) { return toast("Microphone is blocked. Allow it for Telegram in your phone settings.", "err"); }
    voice.on = true; voice.muted = false; vstate(); watchLevel("me", micStream, meId); syncVoice(); renderVoice(); toast("You're in voice", "ok");
  }
  function leaveVoice() {
    if (micStream) micStream.getTracks().forEach((t) => t.stop());
    micStream = null; voice.on = false; voice.muted = false; levels.delete("me"); speaking.delete(meId);
    vstate(); syncVoice(); renderVoice();
  }
  function stopShare() {
    if (scrStream) scrStream.getTracks().forEach((t) => { t.onended = null; t.stop(); });
    scrStream = null; voice.share = false; vstate(); syncVoice(); renderVoice();
    if (!people.some((p) => p.s)) $("stage").hidden = true;
  }
  async function toggleShare() {
    hap();
    if (voice.share) return stopShare();
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) return toast("Screen share isn't supported by Telegram on this phone. It works on Telegram Desktop.", "info");
    try { scrStream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 15 }, audio: false }); }
    catch (e) { return; }
    voice.share = true; scrStream.getVideoTracks()[0].onended = stopShare;
    const v = $("scr"); v.srcObject = scrStream; v.muted = true; $("stage").hidden = false; $("stagetag").textContent = "you are sharing";
    vstate(); syncVoice(); renderVoice();
  }
  function onVDeny(m) {
    toast(m.m || "Not allowed right now", "err");
    if (m.k === "s") { if (scrStream) scrStream.getTracks().forEach((t) => t.stop()); scrStream = null; voice.share = false; $("stage").hidden = true; }
    else leaveVoice();
    renderVoice();
  }
  $("v-join").onclick = () => { hap(); joinVoice(); };
  $("v-leave").onclick = () => { hap(); leaveVoice(); };
  $("v-mute").onclick = () => { hap(); setMute(!voice.muted); };
  $("v-share").onclick = toggleShare;
  renderVoice();
  window.addEventListener("pagehide", () => { try { leaveVoice(); stopShare(); } catch (e) {} });

  // ---------- tabs ----------
  function setTab(n) {
    tab = n;
    TABS.forEach((id) => { $("v-" + id).hidden = id !== n; });
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b.dataset.tab === n));
    $("slider").style.transform = "translateX(" + TABS.indexOf(n) * 100 + "%)";
    $("views").scrollTop = 0;
    renderMini(); hap();
    if (n === "search") setTimeout(() => { try { $("q").focus({ preventScroll: true }); } catch (e) {} }, 300);
    else $("q").blur();
  }
  document.querySelectorAll(".tab").forEach((b) => { b.onclick = () => setTab(b.dataset.tab); });

  // ---------- audio sync (everyone hears the same second) ----------
  // Smooth, not jumpy: small drift is fixed by a tiny speed change, a seek only happens for big drift, and never while buffering.
  let lastSeek = 0, lastRetry = 0;
  au.preload = "auto";
  function seekTo(t) { try { if (au.readyState >= 1) { au.currentTime = Math.max(0, t); lastSeek = Date.now(); } } catch (e) {} }
  function play() {
    if (localOff || !st || st.paused) return;
    const p = au.play();
    if (p && p.catch) p.catch(() => { if (!document.hidden) $("tap").hidden = false; });
  }
  $("tapbtn").onclick = () => { $("tap").hidden = true; localOff = false; seekTo(want()); play(); renderNow(); unlockRemote(); };
  function loadTrack() {
    badSent = -1; au.playbackRate = 1;
    au.onloadedmetadata = () => { send({ t: "meta", seq: st.seq, dur: au.duration }); seekTo(want()); play(); };
    au.src = st.url; au.load();
  }
  function syncAudio() {
    if (!st || !st.track || !au.src) return;
    if (st.paused || localOff) { if (!au.paused) au.pause(); au.playbackRate = 1; return; }
    if (au.paused && au.readyState >= 2 && $("tap").hidden) play();
    if (au.readyState < 3) return;                                   // still buffering: never fight it, catch up after
    const d = want() - au.currentTime, a = Math.abs(d);
    if (a > 3) { if (Date.now() - lastSeek > 5000) { seekTo(want() + 0.3); au.playbackRate = 1; } }
    else if (a > 0.4) au.playbackRate = d > 0 ? 1.04 : 0.96;         // gently speed up / slow down
    else if (a < 0.15) au.playbackRate = 1;
  }
  function recover() {                                              // after the app was in the background the old connection is often dead
    if (!st || !st.track || !st.url || localOff || st.paused) return;
    if (!au.src || au.error || au.ended || (au.readyState < 2 && au.networkState !== 2)) loadTrack(); else syncAudio();
  }
  let stuckSince = 0, lastRecover = 0;
  function watchStuck() {
    if (!st || !st.track || st.paused || localOff || !$("tap").hidden) { stuckSince = 0; return; }
    const bad = au.paused || au.readyState < 2;
    if (!bad) { stuckSince = 0; return; }
    if (!stuckSince) stuckSince = Date.now();
    else if (Date.now() - stuckSince > (au.paused ? 3500 : 10000) && Date.now() - lastRecover > 8000) { lastRecover = Date.now(); stuckSince = 0; recover(); }
  }
  function warmNext() {                                              // preload the next song only near the end, so it never competes with the current one
    if (!st || !st.track || !st.nxt || st.nxt === nxtUrl) return;
    const left = (isFinite(au.duration) && au.duration > 0 ? au.duration : (st.track.dur || 0)) - want();
    if (left > 0 && left < 30) { nxtUrl = st.nxt; pre.preload = "auto"; pre.src = st.nxt; }
  }
  let localNext = false;
  au.onended = () => {
    if (!st) return;
    send({ t: "ended", seq: st.seq });
    if (st.nxt && !st.loop && !localOff && !localNext) {              // don't wait for the server (screen off / slow link): start the next song right now
      localNext = true; badSent = -1; au.playbackRate = 1;
      au.src = st.nxt; au.load(); const p = au.play(); if (p && p.catch) p.catch(() => {});
    }
  };
  au.onerror = () => { if (st && st.track && badSent !== st.seq) { badSent = st.seq; send({ t: "bad", seq: st.seq }); } };
  au.addEventListener("pause", () => {                               // screen off / app in background: try to keep the music going
    if (!st || !st.track || st.paused || localOff || au.ended || !document.hidden || Date.now() - lastRetry < 2000) return;
    lastRetry = Date.now();
    setTimeout(() => { if (au.paused && !localOff && st && !st.paused) { const p = au.play(); if (p && p.catch) p.catch(() => {}); } }, 300);
  });

  function onState(m) {
    const isNew = !st || st.seq !== m.seq;
    st = m;
    if (isNew) nxtUrl = "";
    renderNow(); renderQueue(); renderMini();
    localNext = false;
    if (!m.track) { au.pause(); au.removeAttribute("src"); return; }
    if (isNew && au.src && au.src === m.url && !au.error && au.readyState >= 2) { badSent = -1; syncAudio(); }   // already playing this song (moved on by itself)
    else if (isNew) loadTrack(); else syncAudio();
  }

  // ---------- render: now playing ----------
  function renderNow() {
    const t = st && st.track;
    $("title").textContent = t ? t.title : "Nothing playing";
    $("artist").textContent = t ? t.artist : "Add a song to start the party";
    $("kick").textContent = !t ? "idle" : (st.paused ? "paused" : "now playing");
    const by = $("by"); by.hidden = !t;
    if (t) by.textContent = "added by " + (t.by || "someone") + (st.preview ? " · 30 s preview" : "");
    $("n").textContent = st ? st.n : 0;
    const art = $("art"), cv = t && t.cover || "";
    if (cv) { art.style.setProperty("--cv", cssUrl(cv)); art.classList.add("cover"); } else art.classList.remove("cover");
    if (cv !== lastCover) {
      lastCover = cv; const a = $("amb");
      if (cv) { a.style.backgroundImage = cssUrl(cv); a.classList.add("on"); } else a.classList.remove("on");
    }
    const paused = !t || st.paused || localOff;
    $("app").classList.toggle("is-paused", paused);
    $("app").classList.toggle("app-playing", !paused);
    ["shuf", "skip", "loop", "auto", "q-shuf", "q-auto", "q-clear"].forEach((id) => $(id).classList.toggle("lock", !admin));
    ["loop", "q-loop"].forEach((id) => { if ($(id)) $(id).classList.toggle("on", !!(st && st.loop)); });
    ["auto", "q-auto"].forEach((id) => $(id).classList.toggle("on", !!(st && st.auto)));
    $("adm").hidden = !admin;
    media();
  }
  function renderMini() {
    const t = st && st.track, show = !!t && tab !== "now";
    $("mini").hidden = !show;
    if (!show) return;
    $("m-t").textContent = t.title; $("m-a").textContent = t.artist;
    const th = $("m-th"); th.style.backgroundImage = ""; bg(th, t.cover);
  }
  function draw() {
    const t = st && st.track;
    const d = t ? (isFinite(au.duration) && au.duration > 0 ? au.duration : (t.dur || 0)) : 0, p = t ? want() : 0;
    const pct = (d ? Math.min(100, p / d * 100) : 0) + "%";
    $("fill").style.setProperty("--p", pct); $("m-fill").style.setProperty("--p", pct);
    $("cur").textContent = fmt(p); $("dur").textContent = d ? fmt(d) : (t ? "--:--" : "0:00");
  }
  let mediaSet = false;
  function media() {
    try {
      if (!("mediaSession" in navigator)) return;
      if (st && st.track) {
        navigator.mediaSession.metadata = new MediaMetadata({ title: st.track.title, artist: st.track.artist,
          artwork: st.track.cover ? [{ src: st.track.cover, sizes: "512x512" }] : [] });
      }
      if (!mediaSet) {
        mediaSet = true;
        navigator.mediaSession.setActionHandler("play", () => { if (admin) send({ t: "resume" }); else { localOff = false; play(); renderNow(); } });
        navigator.mediaSession.setActionHandler("pause", () => { if (admin) send({ t: "pause" }); else { localOff = true; au.pause(); renderNow(); } });
        navigator.mediaSession.setActionHandler("nexttrack", () => { if (admin) send({ t: "skip" }); });
      }
    } catch (e) {}
  }
  let posT = 0;
  function mediaPos() {
    try {
      if (!("mediaSession" in navigator)) return;
      navigator.mediaSession.playbackState = !st || !st.track || st.paused || localOff ? "paused" : "playing";
      const d = isFinite(au.duration) && au.duration > 0 ? au.duration : (st && st.track && st.track.dur) || 0;
      if (d && Date.now() - posT > 4000 && navigator.mediaSession.setPositionState) {
        posT = Date.now();
        navigator.mediaSession.setPositionState({ duration: d, playbackRate: 1, position: Math.min(d, Math.max(0, want())) });
      }
    } catch (e) {}
  }
  setInterval(() => { syncAudio(); watchStuck(); warmNext(); draw(); mediaPos(); }, 500);
  // light mode while the app is in the background: far less GPU/memory, so Android is less likely to kill the page ("Aw, Snap!")
  const root = document.documentElement;
  try { if ((navigator.deviceMemory && navigator.deviceMemory <= 4) || (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4)) root.classList.add("slim"); } catch (e) {}
  function wake() { root.classList.remove("lite"); recover(); if (!ws || ws.readyState > 1) connect(); resumeVoice(); }
  document.addEventListener("visibilitychange", () => { if (document.hidden) root.classList.add("lite"); else wake(); });
  try { if (tg && tg.onEvent) tg.onEvent("deactivated", () => root.classList.add("lite")); } catch (e) {}
  try { if (tg && tg.onEvent) tg.onEvent("activated", wake); } catch (e) {}
  window.addEventListener("pageshow", wake); window.addEventListener("online", wake);

  // ---------- render: queue ----------
  function qRow(s, i) {
    const r = h("div", "row qrow glass"); r.style.setProperty("--i", Math.min(i, 10));
    r.appendChild(h("div", "idx", String(i + 1)));
    const th = h("div", "thumb"); th.style.setProperty("--h", 206 + (i * 11) % 60); bg(th, s.cover); r.appendChild(th);
    const t = h("div", "t"); t.appendChild(h("b", "keep", s.title)); t.appendChild(h("span", "keep", s.artist + " · " + (s.by || "someone")));
    r.appendChild(t);
    r.appendChild(h("div", "src" + (s.src === "g" ? " g" : s.src === "auto" ? " a2" : ""), s.src === "g" ? "group" : s.src === "auto" ? "auto" : "app"));
    if (admin) {
      const x = h("button", "rm"); x.appendChild(ico("x")); x.setAttribute("aria-label", "Remove");
      x.onclick = () => { hap(); send({ t: "remove", i: i }); };
      r.appendChild(x);
    } else r.appendChild(h("em", null, s.dur ? fmt(s.dur) : ""));
    return r;
  }
  function emptyBox(icon, title, text, cta, fn) {
    const e = h("div", "empty"), o = h("div", "orbico");
    o.appendChild(ico(icon)); e.appendChild(o); e.appendChild(h("b", null, title)); e.appendChild(h("div", null, text));
    if (cta) { const b = h("button", "chip c-blue", cta); b.onclick = fn; e.appendChild(b); }
    return e;
  }
  function renderQueue() {
    const q = st ? st.queue : [], qn = st ? st.qn : 0;
    $("qc").textContent = qn ? qn + (qn === 1 ? " song" : " songs") : "empty";
    const badge = $("qb"); badge.hidden = !qn; badge.textContent = qn > 99 ? "99+" : qn;
    const sig = q.map((x) => x.title + "|" + x.by + "|" + x.src).join("\n") + "#" + admin + "#" + qn;
    if (sig === qsig) return;
    qsig = sig;
    const list = $("list"); list.replaceChildren();
    if (!q.length) list.appendChild(emptyBox("note", "Queue is empty", "Add songs and they line up here.", "Find songs", () => setTab("search")));
    q.forEach((s, i) => list.appendChild(qRow(s, i)));
    if (qn > q.length) list.appendChild(h("div", "empty", "+" + (qn - q.length) + " more"));
  }

  // ---------- controls ----------
  function togglePlay() {
    hap();
    if (!st || !st.track) return toast("Nothing is playing yet. Add a song!", "info");
    if (admin) return void send({ t: st.paused ? "resume" : "pause" });
    localOff = !localOff;                                   // listeners can only pause their own phone
    if (localOff) { au.pause(); if (!hinted) { hinted = true; toast("Paused on your phone only. The room keeps playing.", "info"); } }
    else { seekTo(want()); play(); }
    renderNow();
  }
  $("pp").onclick = togglePlay; $("m-pp").onclick = togglePlay;
  $("mini").onclick = (e) => { if (!e.target.closest("#m-pp")) setTab("now"); };
  function adminAct(id, type, ok) {
    $(id).onclick = () => {
      hap(admin ? "light" : "rigid");
      if (!admin) return toast("Only group admins can do this", "err");
      if (type !== "clear" && type !== "autoplay" && type !== "loop" && !(st && st.track)) return toast("Nothing is playing yet", "info");
      if (type === "clear") return confirmSheet("Clear the queue?", "All upcoming songs will be removed. The current song keeps playing.", "Clear", "c-rose", () => send({ t: "clear" }));
      send({ t: type }); if (ok) toast(ok, "ok");
    };
  }
  adminAct("shuf", "shuffle", "Queue shuffled"); adminAct("skip", "skip");
  adminAct("loop", "loop"); adminAct("auto", "autoplay");
  adminAct("q-shuf", "shuffle", "Queue shuffled"); adminAct("q-auto", "autoplay"); adminAct("q-clear", "clear");
  $("lyr").onclick = () => {
    hap();
    if (!st || !st.track) return toast("Nothing is playing yet", "info");
    lyrOpen = true;
    sheet((c) => { c.appendChild(h("h3", "keep", st.track.title)); const l = h("div", "loader"); l.append(h("i"), h("i"), h("i")); c.appendChild(l); });
    send({ t: "lyrics" });
    setTimeout(() => { if (lyrOpen && $("sc").querySelector(".loader")) fillLyrics(st && st.track ? st.track.title : "Lyrics", ""); }, 12000);
  };
  function fillLyrics(title, text) {
    if (!lyrOpen) return;
    const c = $("sc"); c.replaceChildren(); c.appendChild(h("h3", "keep", title || "Lyrics"));
    c.appendChild(text ? h("pre", null, text) : h("p", null, "No lyrics found for this song."));
  }

  // ---------- search / add ----------
  function showSugg() { $("sugg").hidden = false; $("out").hidden = true; $("out").replaceChildren(); }
  (function buildTags() {
    const box = $("tags");
    TAGS.forEach((t) => { const b = h("button", t[1], t[0]); b.onclick = () => { hap(); $("q").value = t[0]; $("qx").hidden = false; doSearch(t[0], false); }; box.appendChild(b); });
  })();
  function skeleton() {
    $("sugg").hidden = true; const o = $("out"); o.hidden = false; o.replaceChildren();
    for (let i = 0; i < 5; i++) o.appendChild(h("div", "sk"));
  }
  function doSearch(q, artist) {
    const key = q.toLowerCase() + "|" + (artist ? 1 : 0), c = cache.get(key);
    lastReq = { q: q, artist: artist, id: ++reqId };
    if (c && Date.now() - c.at < 420000) return renderResults(c.m);
    skeleton();
    if (!send({ t: "search", q: q, artist: artist ? 1 : 0, id: lastReq.id })) { toast("Reconnecting… try again in a moment", "err"); showSugg(); }
  }
  $("q").addEventListener("input", () => {
    const v = $("q").value.trim(); $("qx").hidden = !v; clearTimeout(searchTimer);
    if (v.length < 2) { lastReq = null; return showSugg(); }
    searchTimer = setTimeout(() => doSearch(v, false), 380);
  });
  $("q").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault(); const v = $("q").value.trim();
    if (v.length >= 2) { clearTimeout(searchTimer); doSearch(v, false); $("q").blur(); } else toast("Type at least 2 letters", "info");
  });
  $("qx").onclick = () => { hap(); $("q").value = ""; $("qx").hidden = true; lastReq = null; showSugg(); $("q").focus(); };

  function resRow(it, i) {
    const r = h("div", "row glass"); r.style.setProperty("--i", Math.min(i, 10));
    const th = h("div", "thumb"); th.style.setProperty("--h", 205 + (i * 13) % 70); bg(th, it.cover);
    const t = h("div", "t"); t.appendChild(h("b", "keep", it.title)); t.appendChild(h("span", "keep", it.artist));
    const add = h("button", "add"); add.appendChild(ico("plus")); add.setAttribute("aria-label", "Add to queue");
    const go = () => {
      if (add.classList.contains("busy") || add.classList.contains("done")) return;
      hap(); add.classList.add("busy");
      if (!send({ t: "add", token: it.token })) { add.classList.remove("busy"); return toast("Reconnecting… try again", "err"); }
      pending.push(add);
      setTimeout(() => { const k = pending.indexOf(add); if (k >= 0) { pending.splice(k, 1); add.classList.remove("busy"); } }, 9000);
    };
    add.onclick = (e) => { e.stopPropagation(); go(); }; r.onclick = go;
    r.append(th, t, h("em", null, it.dur ? fmt(it.dur) : ""), add);
    return r;
  }
  function renderResults(m) {
    $("sugg").hidden = true;
    const o = $("out"); o.hidden = false; o.replaceChildren();
    const items = m.items || [], arts = m.artists || [];
    if (m.artist) {
      const back = h("button", "chip c-blue back-chip"); back.append(ico("back"), document.createTextNode("all results"));
      back.onclick = () => { hap(); const v = $("q").value.trim(); if (v.length >= 2) doSearch(v, false); else showSugg(); };
      o.appendChild(back); o.appendChild(h("h2", "sec keep", "Top songs · " + (lastReq ? lastReq.q : "")));
    }
    if (arts.length && !m.artist) {
      o.appendChild(h("h2", "sec", "artists"));
      const strip = h("div", "artists");
      arts.forEach((a) => {
        const b = h("button", "ar"), i = h("i"); bg(i, a.cover);
        b.append(i, h("span", "keep", a.name));
        b.onclick = () => { hap(); doSearch(a.name, true); $("views").scrollTop = 0; };
        strip.appendChild(b);
      });
      o.appendChild(strip);
    }
    if (items.length) {
      if (!m.artist) o.appendChild(h("h2", "sec", "songs"));
      items.forEach((it, i) => o.appendChild(resRow(it, i)));
    } else if (!arts.length) {
      o.appendChild(emptyBox("search", "No results", "Try the artist name or a different spelling.", "Clear search", () => $("qx").click()));
    }
  }
  function onResults(m) {
    if (!lastReq || m.id !== lastReq.id) return;                  // an old search finished late: ignore it
    cache.set(lastReq.q.toLowerCase() + "|" + (lastReq.artist ? 1 : 0), { m: m, at: Date.now() });
    if (cache.size > 40) cache.delete(cache.keys().next().value);
    renderResults(m);
  }
  function settle(okay) {
    const b = pending.shift();
    if (!b) return;
    b.classList.remove("busy");
    if (okay) { b.classList.add("done"); b.replaceChildren(ico("check")); }
  }

  // ---------- network ----------
  function setConn(x) { $("conn").hidden = !x; $("conn").textContent = x || ""; }
  function handle(m) {
    switch (m.t) {
      case "hello":
        admin = !!m.admin; roomLink = m.link || ""; meId = m.id || 0; if (Array.isArray(m.ice) && m.ice.length) ice = m.ice; onReconnect(); backoff = 1000; setConn(""); $("room").textContent = m.room || "live room";
        clearInterval(hb); send({ t: "ping", c: Date.now() });
        setTimeout(() => send({ t: "ping", c: Date.now() }), 600);
        hb = setInterval(() => send({ t: "ping", c: Date.now() }), 20000);
        qsig = ""; renderNow(); renderQueue();
        break;
      case "state": onState(m); break;
      case "people": onPeople(m); break;
      case "rtc": onRtc(m); break;
      case "vdeny": onVDeny(m); break;
      case "vmute": if (voice.on && !voice.muted) { setMute(true); toast((m.by || "An admin") + " muted you", "info"); } break;
      case "pong": {
        const rtt = Date.now() - m.c;
        if (rtt <= bestRtt + 30) { bestRtt = Math.min(bestRtt, rtt); off = m.st - (Date.now() - rtt / 2) / 1000; }
        if (admin !== !!m.adm) { admin = !!m.adm; qsig = ""; renderNow(); renderQueue(); }
        break;
      }
      case "results": onResults(m); break;
      case "ok": settle(true); toast(m.m, "ok"); break;
      case "err":
        if (/result|admin|queue|add/i.test(m.m)) settle(false);
        if (/expired/i.test(m.m) && lastReq) { cache.clear(); doSearch(lastReq.q, lastReq.artist); }
        if (/search|fast/i.test(m.m) && lastReq && !$("out").querySelector(".row")) { showSugg(); }
        toast(m.m, "err"); break;
      case "lyrics": fillLyrics(m.title, m.text); break;
      case "fatal": fatal(m.m); break;
    }
  }
  function connect() {
    if (dead || closing) return;
    setConn(backoff > 1000 ? "Reconnecting…" : "Connecting…");
    ws = new WebSocket("wss://" + location.host + "/ws");
    ws.onopen = () => { send({ t: "auth", initData: tg.initData }); };
    ws.onmessage = (e) => { let m; try { m = JSON.parse(e.data); } catch (x) { return; } handle(m); };
    ws.onclose = () => {
      clearInterval(hb);
      if (dead || closing) return;
      setConn("Reconnecting…");
      setTimeout(connect, backoff); backoff = Math.min(backoff * 1.6, 10000);
    };
  }
  setTab("now"); renderNow(); renderQueue();
  if (!tg || !tg.initData) fatal("Open this room from the pinned message in your Telegram group.");
  else connect();
})();
