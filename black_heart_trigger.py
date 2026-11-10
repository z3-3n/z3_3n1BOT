"""Incoming trigger: reply whenever a person says the standalone word 'اسود'."""
import re
from telethon import events
from black_heart import tg, is_bot_account

_TRIGGER = re.compile(r"(?<![\\u0600-\\u06FF])اسود(?![\\u0600-\\u06FF])")


@tg.on(events.NewMessage(incoming=True))
async def black_heart_name_trigger(event):
    text = (event.raw_text or "").strip()
    if not text or not _TRIGGER.search(text):
        return
    try:
        sender = await event.get_sender()
        if not sender or is_bot_account(sender):
            return
        await event.reply("عيون اسود 🖤")
    except Exception as exc:
        print("BLACK HEART NAME TRIGGER ERROR:", exc)
