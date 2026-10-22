from telethon import TelegramClient, events
from telethon.sessions import StringSession
import os
from google import genai
from threading import Thread
from flask import Flask

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MY_ID = int(os.getenv("MY_ID"))

# العميل الجديد
client_ai = genai.Client(api_key=GEMINI_KEY)

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
stopped = set()

SYSTEM = "[تنبيه: هذا رد تلقائي من مساعد اسود الذكي وليس اسود نفسه 🤖]\n"

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if not event.is_private: return
    if event.sender_id == MY_ID:
        t = (event.raw_text or "").lower()
        if "ايقاف" in t and event.is_reply:
            r = await event.get_reply_message()
            stopped.add(r.sender_id)
            await event.respond("تم ايقاف الرد عليه")
            return
        if "تشغيل" in t and event.is_reply:
            r = await event.get_reply_message()
            stopped.discard(r.sender_id)
            await event.respond("تم تشغيل الرد")
            return
        return
    if event.sender_id in stopped: return
    if not event.raw_text: return

    try:
        response = client_ai.models.generate_content(
            model="gemini-2.0-flash",
            contents=f"انت مساعد اسود الذكي ترد بلهجة يمنية قصيرة وودودة. رسالة الشخص: {event.raw_text}"
        )
        await event.respond(SYSTEM + response.text)
        print(f"رد ناجح على {event.sender_id}")
    except Exception as e:
        print(f"خطأ: {e}")
        await event.respond(SYSTEM + "هلا والله، اسود مشغول حاليا وبيرد عليك اول ما يفضى")

app = Flask(__name__)
@app.route('/')
def home(): return "AI Bot Running"
Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000))), daemon=True).start()

print("Bot Started...")
client.start()
client.run_until_disconnected()
