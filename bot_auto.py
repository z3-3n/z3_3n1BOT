import telebot, os, random, time, json
from flask import Flask, request

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = 6453478028
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

stopped_file = "stopped.json"
try:
    with open(stopped_file, "r") as f:
        stopped_users = set(json.load(f))
except:
    stopped_users = set()

def save_stopped():
    with open(stopped_file, "w") as f:
        json.dump(list(stopped_users), f)

FIRST_MSGS = ["هلا انا بوت اسود صاحب الحساب مشغول", "رسالتك وصلت وبيرد عليك قريب"]

RANDOM_REPLIES = ["ها ايش في", "ارحب نورت الخاص", "قول بسرعة", "شكلك فاضي", "حياك انا ماسك الخاص"]

welcomed = {}
def get_reply(uid):
    if uid not in welcomed:
        welcomed[uid] = True
        return random.choice(FIRST_MSGS)
    return random.choice(RANDOM_REPLIES)

@bot.message_handler(func=lambda m: m.from_user.id == OWNER_ID)
def owner_handler(m):
    txt = (m.text or "").strip().lower()
    cid = m.chat.id
    
    if txt == "ايقاف":
        stopped_users.add(cid)
        save_stopped()
        bot.send_message(cid, "تم وقفت البوت")
        return
    if txt == "تفعيل":
        stopped_users.discard(cid)
        save_stopped()
        bot.send_message(cid, "تم شغلت البوت")
        return
    if txt == "قائمة الموقوفين":
        bot.send_message(cid, f"الموقوفين: {list(stopped_users) or 'مافي حد'}")
        return

    # هذا السطر هو الحل - اذا ايوجرام ارسل رسالة نيابة عن شخص
    if m.chat.id not in stopped_users:
        bot.send_chat_action(m.chat.id, 'typing')
        time.sleep(0.8)
        bot.send_message(m.chat.id, get_reply(m.chat.id))

@bot.message_handler(content_types=['text'], func=lambda m: m.from_user.id != OWNER_ID)
def auto_reply(m):
    if m.chat.type != 'private':
        return
    if m.chat.id in stopped_users:
        return
    bot.send_chat_action(m.chat.id, 'typing')
    time.sleep(0.8)
    bot.send_message(m.chat.id, get_reply(m.from_user.id))

@app.route('/webhook', methods=['POST'])
def webhook():
    update = telebot.types.Update.de_json(request.get_data().decode("utf-8"))
    bot.process_new_updates([update])
    return "ok", 200

@app.route('/')
def home():
    return "Bot Working"

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    DOMAIN = "z33n1bot-production.up.railway.app"
    url = f"https://{DOMAIN}/webhook"
    bot.set_webhook(url=url)
    print(f"Webhook set to {url}")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
