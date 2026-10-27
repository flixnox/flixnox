with open("nox/handlers.py", "r") as f:
    code = f.read()

# Ensure DM search works properly
# Jaise hi user DM me text bhejta hai, usko search karke gaana uthana chahiye
dm_logic = '''
@router.message(F.chat.type == "private", F.text, ~F.text.startswith("/"))
async def text_private(m: Message):
    if await guard(m):
        store.touch_user(m.from_user)
        await private_search(m, m.text)

@router.message(Command("play", "search"), F.chat.type == "private")
async def cmd_play_private(m: Message, command: CommandObject):
    if await guard(m):
        store.touch_user(m.from_user)
        await private_search(m, command.args)
'''

# Purane DM handlers ko hatao agar hain
import re
code = re.sub(r'@router\.message\(F\.chat\.type == "private".*?(?=@router|async def|$)', '', code, flags=re.DOTALL)
code = re.sub(r'@router\.message\(Command\("play", "search"\), F\.chat\.type == "private"\).*?(?=@router|async def|$)', '', code, flags=re.DOTALL)

# Naya logic add karo
code += "\n" + dm_logic

with open("nox/handlers.py", "w") as f:
    f.write(code)

print("✅ handlers.py me DM me gaana wapas aa gaya!")
