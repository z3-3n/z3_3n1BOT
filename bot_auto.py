from telethon import TelegramClient, events
from telethon.sessions import StringSession
import os, google.generativeai as genai
from threading import Thread
from flask import Flask

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
STRING_SESSION = os.getenv("STRING_SESSION")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
MY_ID = int(os.getenv("MY_ID"))

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
stopped = set()

SYSTEM = "انت مساعد اسود الذكي. لازم تبدأ كل رد بهذا النص: [تنبيه: هذا رد تلقائي من مساعد اسود الذكي وليس اسود نفسه 🤖]. بعدها رد بلهجة يمنية قصيرة وودودة حسب كلام الشخص. لا تسب ولا تجرح."

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if not event.is_private:
        return
    # تحكمك انت فقط
    if event.sender_id == MY_ID:
        t = (event.raw_text or "").lower()
        if "ايقاف" in t:
            # لازم ترد على رسالة الشخص الي تبي توقفه
            if event.is_reply:
                reply = await event.get_reply_message()
                stopped.add(reply.sender_id)
                await event.respond(f"تم ايقاف الرد على هذا الشخص")
            else:
                await event.respond("رد على رسالة الشخص بكلمة ايقاف")
            return
        if "تشغيل" in t:
            if event.is_reply:
                reply = await event.get_reply_message()
                stopped.discard(reply.sender_id)
                await event.respond("تم تشغيل الرد عليه")
            return
        return

    if event.chat_id in stopped:
        return

    try:
        res = model.generate_content(SYSTEM + f"\nرسالة الشخص: {event.raw_text}")
        await event.respond(res.text)
    except Exception as e:
        print(e)
        await event.respond("[تنبيه: رد تلقائي من مساعد اسود 🤖]\nهلا والله، اسود مشغول حاليا وبيرد عليك اول ما يفضى")

# سيرفر عشان Replit ما يطفي
app = Flask(__name__)
@app.route('/')
def home(): return "AI Bot is Running"
Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000))), daemon=True).start()

client.start()
client.run_until_disconnected()
