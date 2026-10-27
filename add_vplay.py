with open("nox/handlers.py", "r") as f:
    code = f.read()

vplay_code = '''
@router.message(Command("vplay"), F.chat.type.in_(GROUPS))
async def cmd_vplay(m: Message, command: CommandObject):
    if not await guard(m):
        return
    store.touch_group(m.chat)
    g = store.group(m.chat.id)
    if not g["panel"]:
        return await m.reply("The room isn't open yet. Ask an admin to send /start first.")
    if g["play"] == "admins" and not await admin_of(m):
        return await m.reply("🔒 Only admins can add videos in this group.")
    q = clean_text(command.args or "", 80)
    if len(q) < 2:
        return await m.reply("Usage: <code>/vplay video name</code>")
    
    # Force YouTube search for videos
    results = await music._yt_search(q, 1)
    if not results:
        return await m.reply("😕 No videos found on YouTube.")
        
    room = rooms.get(m.chat.id)
    if room is None:
        return await m.reply("I'm very busy right now. Please try again in a minute.")
        
    t = results[0]
    t.update(by=clean_text(m.from_user.first_name if m.from_user else "Admin", 30), by_id=m.from_user.id if m.from_user else 0, src="g")
    
    pos = room.add(t)
    if pos is None:
        return await m.reply("The queue is full right now.")
    reply = await m.reply(ui.added_text(t, pos, t["by"]), reply_markup=ui.join_kb(m.chat.id))
    await _autodel(m)
    msgs = [reply.message_id] + ([] if store.group(m.chat.id)["autodel"] else [m.message_id])
    t["instant"] = pos == "start"
    if t.get("started"):
        _delete_msgs(m.chat.id, msgs, 20 if t["instant"] else 0)
    else:
        t["msgs"] = msgs
'''

if '@router.message(Command("vplay")' not in code:
    code = code.replace('for _c, _f, _t in (("skip",', vplay_code + '\n\nfor _c, _f, _t in (("skip",')

with open("nox/handlers.py", "w") as f:
    f.write(code)

print("✅ handlers.py me /vplay add ho gaya!")
