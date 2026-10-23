## v16: audio card glitch fix: lambi divider hata di, buttons ke labels chhote (bubble ke barabar).

## v15: In Chat = ek hi message (asli music + caption + buttons). Next/auto pe usi message ka gaana badal jata hai (edit), naya message nahi aata.

## v14: In Chat ab 2 message: upar player card (banner/cover SPOILER me + buttons), neeche asli music message. Next pe naya gaana neeche aata hai, card wahi update hota hai. Private player card ka cover bhi spoiler me.

## v13: search results ek gaana = ek button (small caps), jaisa bola tha.

## v12: player + search UI
- Search results: numbered list (small caps) + 1-8 number buttons (4 per row, blue/green rows).
- Player card: premium layout (title, artist, album, duration, up next). **In Chat** ab file nahi, asli Telegram music message bhejta hai (cover + Telegram ke apne player me chalta hai) aur wahi player panel ko replace karta hai; buttons uske neeche rehte hain. Next dabane pe naya gaana purane ko replace karta hai.

## v11: help page
- Help me popup wale command buttons hata diye. Ab har command ki ek-line explanation page ke text me hai (small caps), neeche sirf page buttons.

## v10: kya naya hai
- **Buttons ke colour:** upar se row-by-row blue, green, blue, green... (Loop/Auto ON ho to label me ✔).
- **Song bot me bhi:** player card pe **🎵 In Chat** button, song audio file ban ke isi chat me aa jata hai. **Open Player** se Mini App. Jisko jahan man kare.
- **Mini App me song ka icon (cover) wapas:** `id="stage"` do jagah tha, screen-share wala art ko hide kar deta tha.
- **Help ke andar pages:** Everyone / Admins / Private Player. Har command ek button, tap karo to popup me samjhega.
- Update: files replace karo, `git add -A && git commit -m "v10" && git push`.

## v9: kya naya hai
- **Private player:** bot ke private chat me gaane ka naam bhejo (ya `/play naam`). Results buttons me aate hain, ek tap pe tumhara apna player ban jata hai (album art, Pause/Skip/Queue/Loop/Auto/Stop) aur **Open Player** se Mini App me akele sunte ho.
- Welcome message waisa hi hai, bas uski aur group room ki picture ab **spoiler** hai.
- Buttons: 2-2 ek row me, label ke akshar phaile hue taaki button bhara-bhara lage.
- Awaaz atakna (background / screen off): jab app background me ho tab ab room-clock ke peeche bhagna (seek / speed change) band hai, aur agla gaana memory me pehle se download hota hai, isliye gaana badalte waqt rukta nahi.
- Update: files replace karo, `git add -A && git commit -m "v9" && git push`.

# Sonic Nox: live listening rooms for Telegram groups

## v2: kya naya hai (purane repo par update kaise karein)
- Music source ab **JioSaavn API** hai (full-length gaane, artists, cover art). URL code me default hai, Render me kuch add nahi karna.
  Purani `CURIOUS_API_KEY`, `API_BASE`, `SC_SEARCH_PATH`, yt-dlp aur ffmpeg ki zarurat nahi, Render ke Environment se hata sakte ho.
- Naya Mini App: Now / Search / Queue tabs, mini player, artist search, har button alag rang me, small caps font.
- Bot ke buttons: har button coloured, har tap ka jawab milta hai, room message par gaane ka cover art lagta hai. Naye: Autoplay, `/autoplay`, `/join`.
- Speed: gaana search result se seedha chalta hai (extra lookup nahi), agla gaana pehle se load hota hai, files gzip + long cache.
- Update: purani repo ki saari files is zip ki files se replace karo, `git add . && git commit -m "v2" && git push`, Render khud redeploy karega.

Bot ka naam: **SonicNoxBot**. Group me `/start` karo, `/play song` se gaane add karo, aur sab Mini App me ek saath sunein.

```
Telegram ──► Cloudflare Worker (public, secret header lagata hai) ──► Render (bot + Mini App + WebSocket) ──► MongoDB Atlas
```
Render ka URL kisi ko nahi dikhta. Bina secret header ke Render har request pe 404 deta hai.

## 1. Pehle ye accounts chahiye (sab free)
GitHub, Render, Cloudflare, MongoDB Atlas, UptimeRobot.
Apna Telegram user ID `@userinfobot` se lo.

## 2. Secrets banao (Termux me)
```bash
python -c "import secrets;print(secrets.token_urlsafe(32))"   # ek baar PROXY_SECRET ke liye
python -c "import secrets;print(secrets.token_urlsafe(32))"   # dusri baar WEBHOOK_SECRET ke liye
```
Dono alag-alag value hone chahiye. Kahin share mat karo.

## 3. Termux se GitHub pe push
```bash
pkg install -y git unzip
unzip sonic-nox.zip && cd sonic-nox
git init && git add . && git commit -m "Sonic Nox"
git branch -M main
git remote add origin https://github.com/YOUR_NAME/sonic-nox.git
git push -u origin main        # password ki jagah GitHub Personal Access Token
```
GitHub repo **Private** rakho. `.env` kabhi commit mat karna (`.gitignore` me already hai).

## 4. MongoDB Atlas
Free cluster banao, Database Access me user banao, Network Access me `0.0.0.0/0` allow karo
(Render free ka fixed IP nahi hota), aur connection string (`mongodb+srv://...`) copy karo.

## 5. Render pe deploy
1. New, Web Service, apna GitHub repo chuno (ya `render.yaml` se Blueprint).
2. Plan **Free**, start command repo ki `render.yaml` jaisi (`--workers 1` zaroori hai).
3. Environment variables (`.env.example` dekho): `BOT_TOKEN`, `PROXY_SECRET`, `WEBHOOK_SECRET`, `OWNER_IDS`, `MONGO_URI`,
   `BOT_USERNAME=SonicNoxBot`, `MINIAPP_SHORT=room`, aur abhi ke liye `PUBLIC_URL=https://placeholder.workers.dev`.
4. Deploy ho jaye to Render ka URL (`https://xxx.onrender.com`) copy kar lo.

## 6. Cloudflare Worker
Dashboard, Workers & Pages, Create, Hello World, Edit code, `worker/worker.js` paste karo, Deploy.
Phir Settings, Variables me do cheezein daalo:
- `ORIGIN` = Render URL
- `PROXY_SECRET` = wahi jo Render me hai (**Encrypt** karo)

Worker ka URL (`https://xxx.workers.dev`) milega.

## 7. Jodna
1. Render me `PUBLIC_URL` ko Worker URL se badlo (bina `/` ke end me), save, redeploy. Bot ab apna webhook set kar dega.
2. BotFather, `/newapp`, SonicNoxBot chuno, title `Nox Room`, **Web App URL = Worker URL**, short name `room`.
3. BotFather, `/mybots`, Bot Settings, Group Privacy ko default hi rehne do.

## 8. UptimeRobot
HTTP monitor banao: `https://xxx.workers.dev/health`, har 5 minute. Isse Render free sleep nahi karega.
(Render ko seedha ping mat karo.)

## 9. Test
1. Bot ko group me add karo, admin banao (**Pin messages** + Delete messages).
2. Group me `/start`, banner wala message pin hoga.
3. `/play believer`, phir **Join Room** dabao.
4. Private chat me `/admin` (sirf `OWNER_IDS` wale ko chalega).

## Commands
Sab: `/play`, `/queue`, `/settings` (admins). Admins: `/skip /pause /resume /loop /shuffle /clear /end`.
Owner: `/admin` (stats, API health, broadcast, ban/unban, maintenance).

## Security: kya kya laga hai
- Render ka URL chhupa hai. Worker secret header lagata hai, uske bina 404 (webhook samet).
- Telegram webhook: secret URL path + secret token header, dono constant-time compare.
- Mini App login: Telegram `initData` HMAC verify, 4 ghante se purana reject, aur room sirf group ke members ke liye.
- Room link tamper nahi ho sakta (signed `start_param`) aur membership har join pe check hoti hai.
- Admin actions (skip, pause, loop, shuffle) server pe admin check karke hi chalte hain, buttons chhupane se kuch nahi hota.
- Gaana end/skip sirf majority listeners ki report + sahi time ke baad maana jata hai, ek client room ko control nahi kar sakta.
- Search result ke full details server pe rehte hain; browser sirf ek token bhejta hai, to koi fake gaana/URL inject nahi kar sakta.
- Rate limits (commands, websocket, search, connections per IP) aur baar-baar galti pe temporary block.
- Sab input saaf hota hai (control/bidi characters hatte hain), bot messages HTML-escape hote hain, Mini App me `innerHTML` pe user data nahi.
- Third-party APIs ke URLs sirf `https` + public hostname hi chalte hain (IP/localhost/credentials reject).
- Strict CSP, `nosniff`, no-referrer, HSTS; `/docs` band; origin check on WebSocket.
- API calls pe timeout + cache + circuit breaker; ban list, maintenance mode, secrets sirf env variables me.

**Limits (sach):** koi bhi system 100% unhackable nahi hota. Ye layers casual aur zyadatar targeted attacks rokti hain,
par Render free ke resources limited hain, aur third-party music APIs unofficial hain (kabhi bhi band ya badal sakti hain).
Bot token leak ho to turant BotFather me `/revoke` karo.

## Agar kuch na chale
- **Audio nahi bajta / search khali:** Termux me `python test_apis.py` chalao aur `api_report.txt` ka text bhejo. Bot ka admin panel
  (`/admin` -> API health) bhi JioSaavn ka status dikhata hai. API badalni ho to Render me `JIOSAAVN_BASE` daalo (default code me hi hai).
- **Mini App "Open from group" bole:** link `t.me/SonicNoxBot/room?startapp=...` se hi khulna chahiye, browser se nahi.
- **Websocket connect nahi hota:** `PUBLIC_URL` bilkul Worker ka URL ho (https, bina trailing `/`).
- **Buttons colored nahi:** purana Telegram app ho sakta hai, normal buttons dikhenge, kaam sab chalega.
- Tests: `python -m unittest discover -s tests`

## Room lifecycle, people and voice (v7)
- The room lives from `/start` until an admin sends `/end` (the pinned message turns into "Room closed" and is unpinned). It keeps playing even if nobody is inside; with Autoplay on and an empty room it stops after about 3 songs.
- When a requested song starts playing, its `/play` message and the "added" reply are deleted automatically (the bot needs the "Delete messages" admin right). `/queue` replies are deleted as soon as the song changes.
- Mini App **People** tab: real Telegram names and photos, who is in voice / muted / sharing. Voice and screen share are peer to peer (WebRTC), the server only relays the handshake. Max 8 speakers, one screen share at a time. Admins can mute a speaker.
- Phones behind strict mobile NATs may not connect with STUN only. Add a TURN server in Render with `ICE_SERVERS`, for example:
  `[{"urls":["stun:stun.l.google.com:19302"]},{"urls":["turn:YOUR_TURN_HOST:3478"],"username":"USER","credential":"PASS"}]`
- Screen share works on Telegram Desktop and Web. Telegram's mobile apps do not allow it inside Mini Apps, so the Share button explains that on phones.
