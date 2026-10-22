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

# غيرنا الموديل للجديد
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
stopped = set()

SYSTEM = "انت مساعد اسود الذكي. لازم تبدأ كل رد بهذا النص بالضبط: [تنبيه: هذا رد تلقائي من مساعد اسود الذكي وليس اسود نفسه 🤖] وبعدها سطر جديد. بعدها رد بلهجة يمنية قصيرة وودودة حسب كلام الشخص. لا تسب ولا تجرح."

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if not event.is_private:
        return
    
    # انت - اوامر التحكم
    if event.sender_id == MY_ID:
        t = (event.raw_text or "").lower()
        if "ايقاف" in t and event.is_reply:
            r = await event.get_reply_message()
            stopped.add(r.sender_id)
            await event.respond(f"✅ تم ايقاف الرد على {r.sender_id}")
            return
        if "تشغيل" in t and event.is_reply:
            r = await event.get_reply_message()
            stopped.discard(r.sender_id)
            await event.respond(f"✅ تم تشغيل الرد على {r.sender_id}")
            return
        return

    # اذا الشخص موقوف
    if event.sender_id in stopped:
        print(f"موقوف: {event.sender_id}")
        return

    if not event.raw_text:
        return

    print(f"رسالة من {event.sender_id}: {event.raw_text}")
    try:
        res = model.generate_content(SYSTEM + f"\nرسالة الشخص: {event.raw_text}")
        txt = res.text
        if not txt.startswith("[تنبيه"):
            txt = "[تنبيه: هذا رد تلقائي من مساعد اسود الذكي وليس اسود نفسه 🤖]\n" + txt
        await event.respond(txt)
        print("تم الرد بالذكاء")
    except Exception as e:
        print(f"خطأ Gemini: {e}")
        await event.respond("[تنبيه: هذا رد تلقائي من مساعد اسود الذكي وليس اسود نفسه 🤖]\nهلا والله، اسود مشغول حاليا وبيرد عليك أول ما يفضى")

app = Flask(__name__)
@app.route('/')
def home(): return "AI Bot is Running"
Thread(target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000))), daemon=True).start()

print("Bot Started...")
client.start()
client.run_until_disconnected()
