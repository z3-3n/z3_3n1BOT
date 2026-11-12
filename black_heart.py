import os
import json
import time
import asyncio
import random
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient, events, functions, types, Button
from telethon.sessions import StringSession
from groq import Groq

# =========================================================
# BLACK HEART - stable unified source
# This module registers handlers only. main.py starts tg once.
# Keep API_ID / API_HASH / STRING_SESSION in Replit Secrets.
# =========================================================

try:
    API_ID = int(os.environ["API_ID"])
    API_HASH = os.environ["API_HASH"].strip()
    STRING_SESSION = os.environ["STRING_SESSION"].strip()
except KeyError as exc:
    raise RuntimeError(f"متغير البيئة المطلوب غير مضبوط: {exc.args[0]}") from None
except ValueError:
    raise RuntimeError("قيمة API_ID غير صحيحة؛ يجب أن تكون رقماً.") from None

if API_ID <= 0 or not API_HASH or not STRING_SESSION:
    raise RuntimeError("تأكد من API_ID و API_HASH و STRING_SESSION في متغيرات البيئة.")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "").strip()

tg = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
client_ai = Groq(api_key=GROQ_API_KEY, timeout=35.0, max_retries=0) if GROQ_API_KEY else None

# FadeHost keeps /data across deployments; store all bot state there.
DATA_DIR = Path("/data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def data_file(filename):
    path = Path(filename)
    return path if path.is_absolute() else DATA_DIR / path


SETTINGS_FILE = "settings.json"
WELCOMED_FILE = "welcomed.json"
MUTED_FILE = "muted_private.json"
STATS_FILE = "message_stats.json"
AUTO_REPLIES_FILE = "auto_replies.json"
PROTECTED_FILE = "protected_chats.json"

# Official Groq model IDs. If one is unavailable, the next is tried.
AI_MODELS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
]

REPLY_STYLE = (
    "اجعل ردودك قصيرة وطبيعية كأنك صاحب الحساب نفسه، وغالباً جملة واحدة أو جملتان. "
    "رد على مضمون الكلام مباشرة وبحسب السياق، ولا تحوّل كل رسالة إلى عرض خدمة. "
    "ممنوع أن تختم تلقائياً بعبارات مثل: هل تحتاج مساعدة؟ هل أساعدك بشيء؟ "
    "إذا احتجت شيئاً أخبرني، أنا هنا للمساعدة، أو أي عبارة مشابهة. "
    "لا تسأل سؤالاً في نهاية كل رد؛ اسأل فقط إذا كان فهم الكلام يتطلب توضيحاً فعلاً. "
    "لا تشرح بإسهاب إلا إذا طلب المستخدم شرحاً أو مساعدة، وعندها اشرح بالقدر اللازم."
)

SYSTEM_FIRST = (
    "أنت مساعد BLACK HEART. تحدث بالعربية وبلهجة يمنية صنعانية خفيفة، "
    "كن ودوداً ومفيداً، واكتب إجابات واضحة ومختصرة. " + REPLY_STYLE
)
SYSTEM_NORMAL = (
    "أنت BLACK HEART. تحدث بلهجة يمنية صنعانية خفيفة، "
    "أجب بشكل طبيعي ومفيد، ولا تستخدم السب أو الإهانة أو التهديد. " + REPLY_STYLE
)
SYSTEM_QASF = (
    "أنت BLACK HEART في وضع المزاح. استخدم دعابة خفيفة باللهجة الصنعانية "
    "دون سب أو تهديد أو تحقير أو استهداف شخصي. " + REPLY_STYLE
)


def load_json(filename, default):
    path = data_file(filename)
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                value = json.load(f)
            if isinstance(value, type(default)):
                return value
    except Exception as exc:
        print(f"JSON LOAD ERROR ({path.name}): {exc}")
    return default


def save_json(filename, data):
    path = data_file(filename)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as exc:
        print(f"JSON SAVE ERROR ({path.name}): {exc}")


settings = load_json(SETTINGS_FILE, {"ai": True, "qasf": False})
settings.setdefault("ai", True)
settings.setdefault("qasf", False)
settings.setdefault("auto_replies", True)
welcomed = load_json(WELCOMED_FILE, {})
muted_private = load_json(MUTED_FILE, {})
message_stats = load_json(STATS_FILE, {})
auto_replies = load_json(AUTO_REPLIES_FILE, {})
protected_chats = load_json(PROTECTED_FILE, {})


def display_name(user):
    first = getattr(user, "first_name", None)
    last = getattr(user, "last_name", None)
    title = getattr(user, "title", None)
    name = " ".join(x for x in (first, last) if x)
    return name or title or "مستخدم"


def clean_text(value):
    return (value or "").replace("<", "").replace(">", "").strip()


def is_bot_account(user):
    """Return True for Telegram bots or usernames ending with 'bot'."""
    if not user:
        return False
    if bool(getattr(user, "bot", False)):
        return True
    username = (getattr(user, "username", None) or "").strip().lstrip("@").lower()
    return username.endswith("bot")


async def get_replied_user(event):
    if not event.is_reply:
        await event.edit("❌ رد على رسالة الشخص أولاً.")
        return None
    msg = await event.get_reply_message()
    if not msg:
        await event.edit("❌ لم أستطع العثور على الرسالة.")
        return None
    user = await msg.get_sender()
    if not user or not getattr(user, "id", None):
        await event.edit("❌ لم أستطع تحديد صاحب الرسالة.")
        return None
    return user


async def require_group_admin(event):
    if not event.is_group:
        await event.edit("❌ هذا الأمر يعمل داخل المجموعات فقط.")
        return False
    try:
        permissions = await tg.get_permissions(event.chat_id, "me")
        if getattr(permissions, "is_creator", False) or getattr(permissions, "is_admin", False):
            return True
    except Exception as exc:
        print("ADMIN CHECK ERROR:", exc)
    await event.edit("❌ يجب أن يكون حسابك مشرفاً في المجموعة لتنفيذ هذا الأمر.")
    return False


MEMORY_DB = data_file("ai_memory.sqlite3")
MEMORY_DAYS = 7
MEMORY_LIMIT = 20

def _memory_connection():
    conn = sqlite3.connect(str(MEMORY_DB), timeout=20)
    conn.execute("CREATE TABLE IF NOT EXISTS ai_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL, user_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL, created_at INTEGER NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_memory ON ai_messages(chat_id,user_id,created_at)")
    return conn

def prune_ai_memory():
    cutoff = int(time.time()) - MEMORY_DAYS * 86400
    with _memory_connection() as conn:
        conn.execute("DELETE FROM ai_messages WHERE created_at < ?", (cutoff,))

def get_ai_history(chat_id, user_id):
    cutoff = int(time.time()) - MEMORY_DAYS * 86400
    with _memory_connection() as conn:
        conn.execute("DELETE FROM ai_messages WHERE created_at < ?", (cutoff,))
        rows = conn.execute("SELECT role,content FROM ai_messages WHERE chat_id=? AND user_id=? AND created_at>=? ORDER BY id DESC LIMIT ?", (str(chat_id),str(user_id),cutoff,MEMORY_LIMIT)).fetchall()
    return [{"role":r,"content":c} for r,c in reversed(rows)]

def save_ai_message(chat_id,user_id,role,content):
    if content:
        with _memory_connection() as conn:
            conn.execute("INSERT INTO ai_messages(chat_id,user_id,role,content,created_at) VALUES(?,?,?,?,?)", (str(chat_id),str(user_id),role,str(content)[:12000],int(time.time())))

try:
    prune_ai_memory()
except Exception as exc:
    print("AI MEMORY INIT ERROR:", exc)

async def ai_completion(prompt, system, history=None):
    if client_ai is None:
        return "⚠️ مفتاح GROQ_API_KEY غير مضبوط في Secrets."

    errors = []
    selected_model = settings.get("selected_ai_model", AI_MODELS[0])
    models_to_try = [selected_model] + [m for m in AI_MODELS if m != selected_model]
    messages = [{"role":"system","content":system}]
    if history:
        messages.extend(history[-MEMORY_LIMIT:])
    messages.append({"role":"user","content":prompt or "ابدأ الحديث"})
    for model in models_to_try:
        try:
            response = await asyncio.to_thread(
                client_ai.chat.completions.create,
                model=model,
                messages=messages,
                temperature=0.7,
                max_tokens=500,
            )
            if response.choices:
                content = response.choices[0].message.content
                if content:
                    print("AI MODEL USED:", model)
                    return content.strip()
            errors.append(f"{model}: empty response")
        except Exception as exc:
            errors.append(f"{model}: {exc}")
            print("AI MODEL ERROR:", model, exc)

    return (
        "⚠️ تعذّر الاتصال بجميع نماذج الذكاء المتاحة حالياً. "
        "تحقق من مفتاح Groq وحدود الاستخدام وحالة النماذج."
    )


async def ai_reply(prompt, system, history=None):
    try:
        return await ai_completion(prompt, system, history=history)
    except Exception as exc:
        print("AI FATAL ERROR:", exc)
        return "هلا والله 👋🏻 الذكاء مشغول حالياً، جرّب بعد قليل."


def increment_message_count(chat_id, sender_id):
    chat_key = str(chat_id)
    user_key = str(sender_id)
    message_stats.setdefault(chat_key, {})
    message_stats[chat_key][user_key] = int(message_stats[chat_key].get(user_key, 0)) + 1
    # Save periodically to avoid writing to disk for every message.
    total = sum(int(v) for v in message_stats[chat_key].values())
    if total % 10 == 0:
        save_json(STATS_FILE, message_stats)


async def user_role(chat_id, user):
    try:
        p = await tg.get_permissions(chat_id, user)
        if getattr(p, "is_creator", False):
            return "منشئ المجموعة"
        if getattr(p, "is_admin", False):
            return "مشرف"
        return "عضو"
    except Exception:
        return "غير معروف"


async def user_bio(user):
    try:
        full = await tg(functions.users.GetFullUserRequest(user))
        return getattr(full.full_user, "about", None) or "لا يوجد بايو"
    except Exception:
        return "غير متاح"


# ------------------------- Help menus -------------------------

MENU_TEXT = (
    "🖤 **BLACK HEART - القائمة الرئيسية**\n\n"
    + "\n".join(f"`.م{i}` - {name}" for i, name in enumerate([
        "الإدارة", "الحماية", "المجموعة", "الحساب", "المعلومات والمنشن",
        "التنسيق", "الترجمة", "الوسائط", "أدوات الوسائط", "الذكاء الاصطناعي",
        "الردود التلقائية", "النشر والجدولة", "الأدوات", "حالة السورس", "التسلية"
    ], 1))
    + "\n\nاكتب رقم القائمة لعرض أوامرها. الأوامر التي تتطلب مشرفاً موضحة داخل القائمة."
)

MENU_PAGES = {
  1: "🛡 **الإدارة**\n`.حظر` / `.الغاء حظر` بالرد\n`.كتم` / `.الغاء كتم` بالرد\n`.طرد` بالرد\n`.تثبيت` / `.الغاء تثبيت` بالرد\n`.مسح` بالرد\n`.بلوك` / `.الغاء بلوك` بالرد في الخاص\n`.كتم خاص` / `.الغاء كتم خاص` بالرد في الخاص",
  2: "🧰 **الحماية**\n`.تفعيل حماية` - حذف الرسائل التي تحتوي روابط في المجموعة\n`.تعطيل حماية` - إيقاف حذف الروابط\n`.حالة حماية` - عرض الحالة\nتحتاج صلاحية مشرف، كما يحتاج الحساب صلاحية حذف الرسائل.",
  3: "👥 **المجموعة**\n`.معلومات المجموعة` - معلومات المجموعة الحالية\n`.عدد الاعضاء` - عدد الأعضاء\n`.رابط المجموعة` - إنشاء رابط دعوة إذا كانت الصلاحية متاحة",
 4: "👤 **الحساب**\n`.معلوماتي` - معلومات حسابك\n`.تغيير الاسم الاسم الجديد` - تغيير اسم الحساب\n`.تغيير البايو النص` - تغيير النبذة",
  5: "🔎 **المعلومات والمنشن**\n`.ايدي` أو `.ا` - معلوماتك أو معلومات صاحب الرسالة التي ترد عليها\n`.منشن` - منشن صاحب الرسالة التي ترد عليها فقط",
  6: "✍️ **التنسيق**\n`.عريض النص` - نص عريض\n`.مائل النص` - نص مائل\n`.كود النص` - نص بتنسيق كود\n`.شطب النص` - نص مشطوب",
  7: "🌐 **الترجمة**\n`.ترجم النص` - ترجمة النص إلى العربية\n`.ترجم انجليزي النص` - ترجمة النص إلى الإنجليزية\nتحتاج مفتاح GROQ_API_KEY.",
  8: "🖼 **الوسائط**\n`.معلومات الوسائط` بالرد على صورة أو ملف - عرض معلوماته\n`.حفظ الوسائط` بالرد - إعادة إرسال الوسيط في المحادثة\nلا يقوم السورس بتنزيل محتوى من مواقع خارجية.",
  9: "📁 **أدوات الوسائط**\n`.معلومات الوسائط` بالرد على ملف أو صورة\n`.حفظ الوسائط` بالرد لإعادة إرسال الملف\nلا توجد أوامر تحميل من روابط خارجية في هذه النسخة.",
 10: "🤖 **الذكاء الاصطناعي**\n`.تشغيل ذكي` / `.ايقاف ذكي`\n`.تفعيل القصف` / `.تعطيل القصف` (مزاح خفيف)\n`.النموذج` - عرض النماذج الاحتياطية\nيرد في الخاص، وفي المجموعات عند منشن الحساب فقط.",
 11: "💬 **الردود التلقائية**\n`.اضافة رد الكلمة | الرد`\n`.اضف رد` - إضافة رد مطابق\n`.اضف رد مميز` - إضافة رد عند وجود الكلمة داخل الرسالة\n`.حذف رد` ثم أرسل الكلمة - حذف الرد المطابق\n`.حذف رد مميز` ثم أرسل الكلمة - حذف الرد المميز\n`.الردود` - عرض الردود المحفوظة",
 12: "📣 **النشر والجدولة**\n`.نشر النص` - إرسال نص في المحادثة الحالية\n`.جدولة 10 النص` - إرسال النص بعد 10 دقائق (يمكن تغيير الرقم)\nاستخدمها باعتدال وفي المحادثات التي تملك حق النشر فيها.",
 13: "🧮 **الأدوات**\n`.وقت` - الوقت الحالي\n`.تاريخ` - التاريخ الحالي\n`.رابط الرسالة` بالرد - رابط الرسالة إذا كانت المجموعة عامة أو الرابط متاحاً",
 14: "⚙️ **حالة السورس**\n`.حالة` - حالة الاتصال والذكاء\n`.احصائيات` - عدد الرسائل المرصودة في هذه النسخة\nالإحصائيات تبدأ من وقت تشغيل هذه النسخة ولا تسترجع التاريخ السابق.",
 15: "🎭 **التسلية**\n`.نكتة` / `.حكمة` / `.لغز` / `.جواب`\n`.حظ` / `.اقتباس`"
}

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الاوامر$"))
async def commands_menu(event):
    await event.edit(MENU_TEXT)

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.م([1-9]|1[0-5])$"))
async def numbered_menu(event):
    number = int(event.pattern_match.group(1))
    await event.edit(MENU_PAGES[number])


# ------------------------- Group moderation -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حظر$"))
async def ban_user(event):
    if not await require_group_admin(event):
        return
    user = await get_replied_user(event)
    if not user:
        return
    try:
        await tg(functions.channels.EditBannedRequest(
            event.chat_id,
            user,
            types.ChatBannedRights(until_date=None, view_messages=True)
        ))
        await event.edit(f"🚫 تم حظر {display_name(user)}.")
    except Exception as exc:
        await event.edit(f"❌ تعذّر الحظر. تأكد أن المجموعة تدعم هذا الإجراء وأن صلاحياتك كافية.\n`{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الغاء حظر$"))
async def unban_user(event):
    if not await require_group_admin(event):
        return
    user = await get_replied_user(event)
    if not user:
        return
    try:
        await tg(functions.channels.EditBannedRequest(
            event.chat_id,
            user,
            types.ChatBannedRights(until_date=None, view_messages=False)
        ))
        await event.edit(f"✅ تم فك الحظر عن {display_name(user)}.")
    except Exception as exc:
        await event.edit(f"❌ تعذّر فك الحظر: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.كتم$"))
async def mute_user(event):
    if not await require_group_admin(event):
        return
    user = await get_replied_user(event)
    if not user:
        return
    try:
        await tg.edit_permissions(event.chat_id, user, send_messages=False)
        await event.edit(f"🔇 تم كتم {display_name(user)}.")
    except Exception as exc:
        await event.edit(f"❌ تعذّر الكتم: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الغاء كتم$"))
async def unmute_user(event):
    if not await require_group_admin(event):
        return
    user = await get_replied_user(event)
    if not user:
        return
    try:
        await tg.edit_permissions(event.chat_id, user, send_messages=True)
        await event.edit(f"✅ تم فك كتم {display_name(user)}.")
    except Exception as exc:
        await event.edit(f"❌ تعذّر فك الكتم: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.طرد$"))
async def kick_user(event):
    if not await require_group_admin(event):
        return
    user = await get_replied_user(event)
    if not user:
        return
    try:
        await tg.kick_participant(event.chat_id, user)
        await event.edit(f"👢 تم طرد {display_name(user)}.")
    except Exception as exc:
        await event.edit(f"❌ تعذّر الطرد: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تثبيت$"))
async def pin_message(event):
    if not await require_group_admin(event):
        return
    if not event.is_reply:
        return await event.edit("رد على الرسالة التي تريد تثبيتها.")
    try:
        msg = await event.get_reply_message()
        await tg.pin_message(event.chat_id, msg.id)
        await event.edit("📌 تم تثبيت الرسالة.")
    except Exception as exc:
        await event.edit(f"❌ تعذّر التثبيت: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الغاء تثبيت$"))
async def unpin_message(event):
    if not await require_group_admin(event):
        return
    if not event.is_reply:
        return await event.edit("رد على الرسالة التي تريد إلغاء تثبيتها.")
    try:
        msg = await event.get_reply_message()
        await tg.unpin_message(event.chat_id, msg.id)
        await event.edit("✅ تم إلغاء تثبيت الرسالة.")
    except Exception as exc:
        await event.edit(f"❌ تعذّر إلغاء التثبيت: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.مسح$"))
async def delete_replied_message(event):
    if not await require_group_admin(event):
        return
    if not event.is_reply:
        return await event.edit("رد على الرسالة التي تريد حذفها.")
    try:
        msg = await event.get_reply_message()
        await msg.delete()
        await event.delete()
    except Exception as exc:
        await event.edit(f"❌ تعذّر حذف الرسالة: `{exc}`")


# ------------------------- Private block controls -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.بلوك$"))
async def block_user(event):
    if not event.is_private:
        return await event.edit("استخدم هذا الأمر في الخاص بالرد على رسالة الشخص.")
    user = await get_replied_user(event)
    if not user:
        return
    try:
        await tg(functions.contacts.BlockRequest(user))
        await event.edit(f"🚫 تم حظر {display_name(user)}.")
    except Exception as exc:
        await event.edit(f"❌ تعذّر الحظر: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الغاء بلوك$"))
async def unblock_user(event):
    if not event.is_private:
        return await event.edit("استخدم هذا الأمر في الخاص بالرد على رسالة الشخص.")
    user = await get_replied_user(event)
    if not user:
        return
    try:
        await tg(functions.contacts.UnblockRequest(user))
        await event.edit(f"✅ تم فك الحظر عن {display_name(user)}.")
    except Exception as exc:
        await event.edit(f"❌ تعذّر فك الحظر: `{exc}`")


# ------------------------- Private mute list -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.كتم خاص$"))
async def mute_private_user(event):
    if not event.is_private:
        return await event.edit("هذا الأمر يعمل في الخاص فقط.")
    user = await get_replied_user(event)
    if not user:
        return
    muted_private[str(user.id)] = {"name": display_name(user), "time": time.time()}
    save_json(MUTED_FILE, muted_private)
    await event.edit(f"🔇 ستُتجاهل رسائل {display_name(user)} الواردة في الخاص.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الغاء كتم خاص$"))
async def unmute_private_user(event):
    user = await get_replied_user(event)
    if not user:
        return
    if muted_private.pop(str(user.id), None) is None:
        return await event.edit("هذا الشخص غير موجود في قائمة الكتم الخاص.")
    save_json(MUTED_FILE, muted_private)
    await event.edit(f"✅ تم إلغاء كتم {display_name(user)} في الخاص.")


# ------------------------- ID / mention -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.(?:ايدي|ا)$"))
async def show_id(event):
    try:
        if event.is_reply:
            reply = await event.get_reply_message()
            user = await reply.get_sender()
        else:
            user = await event.get_sender()

        if not user:
            return await event.edit("❌ لم أستطع تحديد المستخدم.")

        username = getattr(user, "username", None) or "لا يوجد"
        bio = await user_bio(user)
        role = await user_role(event.chat_id, user) if event.is_group else "خاص"
        count = message_stats.get(str(event.chat_id), {}).get(str(user.id), 0)
        name = clean_text(display_name(user))
        bio = clean_text(bio)

        result = (
            f"᷂NAME ᷂#{name}\n"
            f"USE ᷂#{username}\n"
            f"STA ᷂#{role}\n"
            f"MSG ᷂#{count} رسالة مرصودة منذ تشغيل الإحصاء\n"
            f"ID ᷂#{user.id}\n"
            f"BIO ᷂#{bio}\n\n"
            "#سورس قلب اސމ︎ بالذكاء الاصطناعي🖤🥀"
        )
        await event.edit(result)
    except Exception as exc:
        await event.edit(f"❌ تعذّر جلب المعلومات: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.منشن$"))
async def mention_replied_user(event):
    user = await get_replied_user(event)
    if not user:
        return
    import html
    name = html.escape(display_name(user))
    await event.edit(f'<a href="tg://user?id={user.id}">{name}</a>', parse_mode="html")


# ------------------------- AI controls -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تشغيل ذكي$"))
async def enable_ai(event):
    paused_chats = set(str(x) for x in settings.get("ai_paused_chats", []))
    paused_chats.discard(str(event.chat_id))
    settings["ai_paused_chats"] = sorted(paused_chats)
    if "AI_PAUSED_CHATS" in globals():
        AI_PAUSED_CHATS.discard(str(event.chat_id))
    save_json(SETTINGS_FILE, settings)
    await event.edit("✅ تم تشغيل الذكاء الاصطناعي في هذه المحادثة.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.ايقاف ذكي$"))
async def disable_ai(event):
    paused_chats = set(str(x) for x in settings.get("ai_paused_chats", []))
    paused_chats.add(str(event.chat_id))
    settings["ai_paused_chats"] = sorted(paused_chats)
    if "AI_PAUSED_CHATS" in globals():
        AI_PAUSED_CHATS.add(str(event.chat_id))
    save_json(SETTINGS_FILE, settings)
    await event.edit("🛑 تم إيقاف الذكاء الاصطناعي في هذه المحادثة فقط.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تفعيل القصف$"))
async def enable_qasf(event):
    settings["qasf"] = True
    save_json(SETTINGS_FILE, settings)
    await event.edit("🔥 تم تفعيل وضع المزاح الخفيف.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تعطيل القصف$"))
async def disable_qasf(event):
    settings["qasf"] = False
    save_json(SETTINGS_FILE, settings)
    await event.edit("✅ تم تعطيل وضع المزاح.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تغيير النموذج(?:\s+(\d+))?$"))
async def change_ai_model(event):
    choice = event.pattern_match.group(1)
    current = settings.get("selected_ai_model", AI_MODELS[0])
    if not choice:
        rows = "\n".join(f"{i}. `{m}`" + ("  ✅ الحالي" if m == current else "") for i,m in enumerate(AI_MODELS,1))
        return await event.edit("🤖 **تغيير نموذج الذكاء**\n\n" + rows + "\n\nاختر بالأمر: `.تغيير النموذج 1` أو `.تغيير النموذج 2`")
    index = int(choice)-1
    if index < 0 or index >= len(AI_MODELS):
        return await event.edit("❌ الرقم غير صحيح.")
    settings["selected_ai_model"] = AI_MODELS[index]
    save_json(SETTINGS_FILE, settings)
    await event.edit("✅ تم اختيار النموذج:\n`" + AI_MODELS[index] + "`\nوسيُستخدم النموذج الاحتياطي تلقائياً إذا تعذّر.")
    
@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.النموذج$"))
async def show_models(event):
    current = settings.get("selected_ai_model", AI_MODELS[0])
    await event.edit("🤖 **النموذج الحالي:** `" + current + "`\nللعرض والتغيير استخدم `.تغيير النموذج`.")


# ------------------------- Protection / group / profile -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تفعيل حماية$"))
async def enable_protection(event):
    if not await require_group_admin(event): return
    protected_chats[str(event.chat_id)] = True
    save_json(PROTECTED_FILE, protected_chats)
    await event.edit("🛡 تم تفعيل حذف الرسائل التي تحتوي روابط.")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تعطيل حماية$"))
async def disable_protection(event):
    if not await require_group_admin(event): return
    protected_chats.pop(str(event.chat_id), None)
    save_json(PROTECTED_FILE, protected_chats)
    await event.edit("✅ تم إيقاف حماية الروابط.")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حالة حماية$"))
async def protection_status(event):
    state = protected_chats.get(str(event.chat_id), False)
    await event.edit("🛡 حماية الروابط مفعّلة." if state else "الحماية غير مفعّلة.")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.معلومات المجموعة$"))
async def group_info(event):
    if not event.is_group: return await event.edit("هذا الأمر للمجموعات فقط.")
    try:
        chat = await event.get_chat()
        count = getattr(chat, "participants_count", None)
        title = clean_text(getattr(chat, "title", "مجموعة"))
        username = getattr(chat, "username", None)
        await event.edit(f"👥 **{title}**\nID: `{event.chat_id}`\nالأعضاء: `{count if count is not None else 'غير متاح'}`\nالمعرف: `@{username}`" if username else f"👥 **{title}**\nID: `{event.chat_id}`\nالأعضاء: `{count if count is not None else 'غير متاح'}`\nالمجموعة خاصة.")
    except Exception as exc: await event.edit(f"تعذر جلب المعلومات: `{exc}`")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.عدد الاعضاء$"))
async def member_count(event):
    if not event.is_group: return await event.edit("هذا الأمر للمجموعات فقط.")
    try:
        chat = await event.get_chat()
        count = getattr(chat, "participants_count", None)
        await event.edit(f"👥 عدد الأعضاء: `{count if count is not None else 'غير متاح'}`")
    except Exception as exc: await event.edit(f"تعذر جلب العدد: `{exc}`")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.رابط المجموعة$"))
async def group_link(event):
    if not event.is_group: return await event.edit("هذا الأمر للمجموعات فقط.")
    try:
        link = await tg.export_invite_link(event.chat_id)
        await event.edit(f"🔗 رابط الدعوة:\n{link}")
    except Exception as exc: await event.edit(f"تعذر إنشاء الرابط. تأكد من صلاحيات الدعوة.\n`{exc}`")

# Sequential, persistent username availability search; never changes the account username.
async def _username_search(event, length):
    from telethon import functions
    me = await tg.get_me()
    original_username = getattr(me, "username", None)
    if not original_username:
        return await event.edit("⚠️ حسابك لا يملك يوزراً حالياً. لن يتم تغيير أي إعداد.")
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    state_file = "username_search_state.json"
    state = load_json(state_file, {})
    key = str(length)
    cursor = int(state.get(key, 0) or 0)
    total = len(alphabet) ** length
    await event.edit("🔎 البحث المتسلسل بدأ من الاحتمال رقم " + str(cursor + 1) + ". سأفحص 30 احتمالاً بالترتيب دون تكرار، ويوزرك محفوظ: @" + original_username)

    def make_username(number):
        parts = []
        for _ in range(length):
            number, digit = divmod(number, len(alphabet))
            parts.append(alphabet[digit])
        return "_".join(parts)

    available = []
    checked = 0
    while checked < 30 and cursor < total:
        username = make_username(cursor)
        cursor += 1
        state[key] = cursor
        save_json(state_file, state)
        if username.lower() == original_username.lower():
            continue
        try:
            result = await tg(functions.account.CheckUsernameRequest(username=username))
            checked += 1
            if result:
                available.append("@" + username)
        except Exception as exc:
            msg = str(exc).upper()
            if "USERNAME_OCCUPIED" in msg or "USERNAME_INVALID" in msg:
                checked += 1
                continue
            if "FLOOD" in msg or "TOO_MANY" in msg:
                break
            print("USERNAME SEARCH ERROR:", exc)
            checked += 1

    lines = ["🖤 النتائج المتاحة وقت الفحص:"]
    lines.extend("- " + item for item in available)
    if not available:
        lines.append("لم يظهر يوزر متاح في هذه الدفعة.")
    lines.append("تم فحص: " + str(checked) + " احتمالاً.")
    lines.append("يوزرك الأصلي محفوظ كما هو: @" + original_username)
    if cursor >= total:
        lines.append("✅ اكتمل تسلسل جميع الاحتمالات لهذا النوع.")
    else:
        lines.append("للمتابعة دون تكرار، أعد كتابة الأمر نفسه. التالي من رقم: " + str(cursor + 1))
    await event.edit("\\n".join(lines))

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.بحث يوزر ثلاثي$"))
async def search_three_char_username(event):
    await _username_search(event, 3)

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.بحث يوزر رباعي$"))
async def search_four_char_username(event):
    await _username_search(event, 4)

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.معلوماتي$"))
async def my_profile(event):
    me = await tg.get_me()
    await event.edit(f"👤 الاسم: {display_name(me)}\nالمعرف: @{getattr(me, 'username', None) or 'لا يوجد'}\nID: `{me.id}`\nرقم الهاتف: مخفي حفاظاً على الخصوصية.")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تغيير الاسم\s+(.+)$"))
async def change_name(event):
    name = event.pattern_match.group(1).strip()[:64]
    try:
        await tg(functions.account.UpdateProfileRequest(first_name=name))
        await event.edit("✅ تم تحديث اسم الحساب.")
    except Exception as exc: await event.edit(f"تعذر تغيير الاسم: `{exc}`")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تغيير البايو\s+(.+)$"))
async def change_bio(event):
    bio = event.pattern_match.group(1).strip()[:70]
    try:
        await tg(functions.account.UpdateProfileRequest(about=bio))
        await event.edit("✅ تم تحديث النبذة.")
    except Exception as exc: await event.edit(f"تعذر تغيير النبذة: `{exc}`")

# ------------------------- Text formatting / translation -------------------------

async def format_text(event, mode):
    value = event.pattern_match.group(1).strip()
    if not value: return await event.edit("اكتب النص بعد الأمر.")
    if mode == "bold": out = f"**{value}**"
    elif mode == "italic": out = f"__{value}__"
    elif mode == "code": out = f"`{value}`"
    else: out = f"~~{value}~~"
    await event.edit(out)

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.عريض\s+(.+)$"))
async def fmt_bold(e): await format_text(e, "bold")
@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.مائل\s+(.+)$"))
async def fmt_italic(e): await format_text(e, "italic")
@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.كود\s+(.+)$"))
async def fmt_code(e): await format_text(e, "code")
@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.شطب\s+(.+)$"))
async def fmt_strike(e): await format_text(e, "strike")

async def translate_text(event, target):
    value = event.pattern_match.group(1).strip()
    if not value: return await event.edit("اكتب النص بعد الأمر.")
    await event.edit("🌐 جارٍ الترجمة...")
    result = await ai_reply(f"ترجم النص التالي إلى {target} فقط، دون شرح أو إضافات:\n{value}", "أنت مترجم دقيق. أعد الترجمة فقط.")
    await event.edit(result)

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.ترجم انجليزي\s+(.+)$"))
async def translate_english(e): await translate_text(e, "الإنجليزية")
@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.ترجم\s+(.+)$"))
async def translate_arabic(e): await translate_text(e, "العربية")

# ------------------------- Media tools -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.معلومات الوسائط$"))
async def media_info(event):
    if not event.is_reply: return await event.edit("رد على صورة أو ملف أولاً.")
    msg = await event.get_reply_message()
    if not msg or not msg.media: return await event.edit("الرسالة المحددة لا تحتوي وسيطاً.")
    doc = getattr(msg, "document", None)
    photo = getattr(msg, "photo", None)
    name = "صورة" if photo else "ملف"
    size = getattr(doc, "size", None) if doc else None
    mime = getattr(doc, "mime_type", None) if doc else None
    await event.edit(f"🗂 نوع الوسيط: {name}\nالحجم: {size if size is not None else 'غير متاح'} بايت\nالنوع: {mime or 'صورة تيليجرام'}\nمعرف الرسالة: `{msg.id}`")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حفظ الوسائط$"))
async def resend_media(event):
    if not event.is_reply: return await event.edit("رد على صورة أو ملف أولاً.")
    msg = await event.get_reply_message()
    if not msg or not msg.media: return await event.edit("الرسالة المحددة لا تحتوي وسيطاً.")
    try:
        await tg.send_file(event.chat_id, msg.media, caption="🖤")
        await event.delete()
    except Exception as exc: await event.edit(f"تعذر إعادة إرسال الوسيط: `{exc}`")

# ------------------------- Auto replies -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.اضافة رد\s+(.+)$"))
async def add_auto_reply(event):
    raw = event.pattern_match.group(1)
    if "|" not in raw: return await event.edit("الصيغة: `.اضافة رد الكلمة | الرد`")
    trigger, answer = [x.strip() for x in raw.split("|", 1)]
    if not trigger or not answer: return await event.edit("اكتب الكلمة والرد.")
    auto_replies[trigger.lower()] = answer[:1500]
    save_json(AUTO_REPLIES_FILE, auto_replies)
    await event.edit(f"✅ تمت إضافة رد للكلمة: {trigger}")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حذف رد مباشر\s+(.+)$"))
async def remove_auto_reply(event):
    key = event.pattern_match.group(1).strip().lower()
    if auto_replies.pop(key, None) is None: return await event.edit("لا يوجد رد محفوظ لهذه الكلمة.")
    save_json(AUTO_REPLIES_FILE, auto_replies)
    await event.edit("✅ تم حذف الرد.")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الردود$"))
async def list_auto_replies(event):
    if not auto_replies: return await event.edit("لا توجد ردود تلقائية محفوظة.")
    rows = []
    for k, v in list(auto_replies.items())[:30]:
        answer = v.get("answer", "") if isinstance(v, dict) else str(v)
        mode = "مميز" if isinstance(v, dict) and v.get("mode") == "contains" else "مطابق"
        rows.append(f"• {k} [{mode}] ← {answer[:80]}")
    await event.edit("💬 **الردود المحفوظة**\n" + "\n".join(rows))

# ------------------------- Posting / scheduling -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.نشر\s+(.+)$"))
async def publish_text(event):
    text = event.pattern_match.group(1).strip()
    try:
        await tg.send_message(event.chat_id, text)
        await event.delete()
    except Exception as exc: await event.edit(f"تعذر النشر: `{exc}`")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.جدولة\s+(\d+)\s+(.+)$"))
async def schedule_text(event):
    minutes = int(event.pattern_match.group(1))
    text = event.pattern_match.group(2).strip()
    if minutes < 1 or minutes > 10080: return await event.edit("اختر مدة من دقيقة إلى 7 أيام.")
    try:
        await tg.send_message(event.chat_id, text, schedule=datetime.now(timezone.utc) + timedelta(minutes=minutes))
        await event.edit(f"⏰ تمت جدولة الرسالة بعد {minutes} دقيقة.")
    except Exception as exc: await event.edit(f"تعذرت الجدولة في هذه المحادثة: `{exc}`")

# ------------------------- Utilities / status -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.وقت$"))
async def show_time(event): await event.edit("🕒 الوقت: " + datetime.now().strftime("%H:%M:%S"))
@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تاريخ$"))
async def show_date(event): await event.edit("📅 التاريخ: " + datetime.now().strftime("%Y-%m-%d"))

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.رابط الرسالة$"))
async def message_link(event):
    if not event.is_reply: return await event.edit("رد على الرسالة أولاً.")
    msg = await event.get_reply_message()
    try:
        chat = await event.get_chat()
        username = getattr(chat, "username", None)
        if username: link = f"https://t.me/{username}/{msg.id}"
        elif str(event.chat_id).startswith("-100"):
            internal = str(event.chat_id)[4:]
            link = f"https://t.me/c/{internal}/{msg.id}"
        else: return await event.edit("لا يتوفر رابط مباشر لهذه الرسالة.")
        await event.edit("🔗 " + link)
    except Exception as exc: await event.edit(f"تعذر إنشاء الرابط: `{exc}`")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حالة$"))
async def source_status(event):
    me = await tg.get_me()
    await event.edit(f"🖤 **BLACK HEART يعمل**\nالحساب: {display_name(me)}\nTelegram: متصل\nالذكاء: {'مفعّل' if settings.get('ai', True) else 'متوقف'}\nGroq: {'مضبوط' if client_ai else 'غير مضبوط'}\nالردود التلقائية: {len(auto_replies)}")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.احصائيات$"))
async def source_stats(event):
    chat_data = message_stats.get(str(event.chat_id), {})
    total = sum(int(v) for v in chat_data.values())
    await event.edit(f"📊 إحصائيات هذه المحادثة منذ تثبيت النسخة الحالية\nعدد المستخدمين المرصودين: {len(chat_data)}\nإجمالي الرسائل المرصودة: {total}")

# ------------------------- Simple fun commands -------------------------

JOKES = [
    "واحد قال لصاحبه: ذاكرتك كيف؟ قال: ممتازة... بس نسيت وين حطيتها 😂",
    "واحد اشترى ساعة ضد الماء، عطشها وسقاها 😂",
    "قالوا للكسلان قم بدري، قال: طيب صحّوني أمس 😂",
]
WISDOM = [
    "الخطوة الصغيرة كل يوم تصنع فرقاً كبيراً مع الوقت.",
    "لا تقارن بدايتك بنهاية طريق شخص آخر.",
    "الكلمة الطيبة تفتح أبواباً لا تفتحها القوة.",
]
RIDDLES = [
    ("ما الشيء الذي كلما أخذت منه كبر؟", "الحفرة."),
    ("له أسنان ولا يعض، ما هو؟", "المشط."),
    ("يمشي بلا قدمين ويبكي بلا عينين، ما هو؟", "السحاب."),
]
pending_riddles = {}

QUOTES = [
    "كن لطيفاً، فكل شخص يخوض معركة لا تعرفها.",
    "ابدأ بما تستطيع، ومن مكانك، وبما تملك.",
    "العلم يرفع صاحبه، والعمل يثبت أثره.",
]


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.نكتة ثابتة$"))
async def joke(event):
    await event.edit(random.choice(JOKES))


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حكمة ثابتة$"))
async def wisdom(event):
    await event.edit(random.choice(WISDOM))


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.لغز ثابت$"))
async def riddle(event):
    question, answer = random.choice(RIDDLES)
    pending_riddles[str(event.chat_id)] = answer
    await event.edit(f"🧩 {question}\n\nللإجابة اكتب: `.جواب`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.جواب$"))
async def riddle_answer(event):
    answer = pending_riddles.pop(str(event.chat_id), None)
    if answer:
        await event.edit(f"💡 الإجابة: {answer}")
    else:
        await event.edit("ما في لغز حالي. اكتب `.لغز` أولاً.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حظ$"))
async def luck(event):
    await event.edit(f"🍀 رقمك العشوائي للتسلية: **{random.randint(1, 100)}**")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.اقتباس ثابت$"))
async def quote(event):
    await event.edit(random.choice(QUOTES))


# ------------------------- Incoming messages / counters / AI -------------------------

@tg.on(events.NewMessage(incoming=True))
async def incoming_handler(event):
    sender_id = str(event.sender_id or "")
    if not sender_id:
        return

    # Ignore bot accounts completely to prevent bot-to-bot reply loops.
    try:
        incoming_sender = await event.get_sender()
        if is_bot_account(incoming_sender):
            return
    except Exception as exc:
        print("SENDER CHECK ERROR:", exc)
        return

    # Count only messages observed after this version is installed.
    if event.is_group:
        increment_message_count(event.chat_id, sender_id)

    if event.is_private and sender_id in muted_private:
        return

    # Optional anti-link protection for groups; only enabled by a group admin.
    if event.is_group and protected_chats.get(str(event.chat_id), False):
        incoming_text = (event.raw_text or "").lower()
        has_link = any(token in incoming_text for token in ("http://", "https://", "t.me/", "www."))
        if has_link:
            try:
                sender = await event.get_sender()
                perms = await tg.get_permissions(event.chat_id, sender) if sender else None
                is_admin = bool(
                    perms and (
                        getattr(perms, "is_admin", False)
                        or getattr(perms, "is_creator", False)
                    )
                )
                if not is_admin:
                    await event.delete()
                    return
            except Exception as exc:
                # If permissions cannot be checked, do not delete blindly.
                print("ANTI LINK PERMISSION CHECK ERROR:", exc)

    incoming_text = (event.raw_text or "").strip()
    if settings.get("auto_replies", True) and incoming_text:
        normalized = incoming_text.casefold().strip()
        exact = auto_replies.get(normalized)
        if exact:
            try:
                if isinstance(exact, dict):
                    if exact.get("mode", "exact") == "exact":
                        await event.reply(exact.get("answer", ""))
                        return
                else:
                    await event.reply(exact)
                    return
            except Exception as exc:
                print("AUTO REPLY EXACT ERROR:", exc)
        for saved_trigger, saved_value in list(auto_replies.items()):
            if isinstance(saved_value, dict) and saved_value.get("mode") == "contains" and saved_trigger.casefold() in normalized:
                try:
                    await event.reply(saved_value.get("answer", ""))
                    return
                except Exception as exc:
                    print("AUTO REPLY CONTAINS ERROR:", exc)

    # Developer dot-commands are handled by the dedicated command bridge;
    # do not send an unrelated AI reply to those commands.
    if incoming_text.startswith(".") and len(incoming_text) > 1 and incoming_text[1].isalnum():
        developer_ids = {str(x) for x in load_json("developers.json", [])}
        if sender_id in developer_ids:
            return

    # AI can be paused globally or separately in each chat. Other commands,
    # games, and auto-replies remain available while AI is paused.
    if not settings.get("ai_global_enabled", settings.get("ai", True)):
        return
    if str(event.chat_id) in settings.get("ai_paused_chats", []):
        return

    # Automatic replies in private; in groups only when the account is mentioned.
    if not event.is_private and not event.mentioned:
        return

    text_in = (event.raw_text or "").strip()
    if not text_in:
        return

    chat_key = str(event.chat_id)
    first_message = chat_key not in welcomed
    system = SYSTEM_QASF if settings.get("qasf", False) else (
        SYSTEM_FIRST if first_message else SYSTEM_NORMAL
    )

    user_key = str(event.sender_id)
    try:
        history = get_ai_history(chat_key, user_key)
    except Exception as exc:
        print("AI MEMORY READ ERROR:", exc)
        history = []
    answer = await ai_reply(text_in, system, history=history)
    try:
        await event.reply(answer)
        try:
            save_ai_message(chat_key, user_key, "user", text_in)
            save_ai_message(chat_key, user_key, "assistant", answer)
        except Exception as exc:
            print("AI MEMORY SAVE ERROR:", exc)
        if first_message:
            welcomed[chat_key] = True
            save_json(WELCOMED_FILE, welcomed)
    except Exception as exc:
        print("REPLY ERROR:", exc)


print("🖤 BLACK HEART unified source loaded")

# =========================================================
# BLACK HEART EXTENSIONS - additional functional commands
# =========================================================

WARNINGS_FILE = "warnings.json"
WELCOME_SETTINGS_FILE = "welcome_settings.json"
LEAVE_SETTINGS_FILE = "leave_settings.json"
NOTES_FILE = "notes.json"
ANTIFLOOD_FILE = "antiflood_settings.json"

warnings_data = load_json(WARNINGS_FILE, {})
welcome_settings = load_json(WELCOME_SETTINGS_FILE, {})
leave_settings = load_json(LEAVE_SETTINGS_FILE, {})
notes_data = load_json(NOTES_FILE, {})
antiflood_settings = load_json(ANTIFLOOD_FILE, {})
_flood_windows = {}


def _chat_key(event):
    return str(event.chat_id)


def _warn_key(chat_id, user_id):
    return f"{chat_id}:{user_id}"


async def _target_from_reply(event):
    if not event.is_reply:
        await event.edit("❌ رد على رسالة الشخص أولاً.")
        return None
    reply = await event.get_reply_message()
    if not reply:
        await event.edit("❌ لم أجد الرسالة المحددة.")
        return None
    user = await reply.get_sender()
    if not user or not getattr(user, "id", None):
        await event.edit("❌ لم أستطع تحديد صاحب الرسالة.")
        return None
    return user


# ------------------------- Warnings -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تحذير(?:\s+(.+))?$"))
async def warn_member(event):
    if not await require_group_admin(event):
        return
    user = await _target_from_reply(event)
    if not user:
        return
    reason = (event.pattern_match.group(1) or "مخالفة قوانين المجموعة").strip()
    key = _warn_key(event.chat_id, user.id)
    entry = warnings_data.setdefault(key, {"name": display_name(user), "items": []})
    entry.setdefault("items", []).append({"reason": reason[:250], "time": int(time.time())})
    save_json(WARNINGS_FILE, warnings_data)
    await event.edit(f"⚠️ تم تسجيل تحذير لـ {display_name(user)}.\nعدد التحذيرات: {len(entry['items'])}\nالسبب: {reason}")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تحذيراته$"))
async def list_member_warnings(event):
    if not await require_group_admin(event):
        return
    user = await _target_from_reply(event)
    if not user:
        return
    entry = warnings_data.get(_warn_key(event.chat_id, user.id), {})
    items = entry.get("items", [])
    if not items:
        return await event.edit("✅ لا توجد تحذيرات مسجلة لهذا العضو.")
    lines = [f"{i}. {x.get('reason', 'بدون سبب')}" for i, x in enumerate(items[-10:], 1)]
    await event.edit(f"⚠️ تحذيرات {display_name(user)} ({len(items)}):\n" + "\n".join(lines))


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تصفير التحذيرات$"))
async def clear_member_warnings(event):
    if not await require_group_admin(event):
        return
    user = await _target_from_reply(event)
    if not user:
        return
    existed = warnings_data.pop(_warn_key(event.chat_id, user.id), None)
    save_json(WARNINGS_FILE, warnings_data)
    await event.edit("✅ تم تصفير التحذيرات." if existed else "لا توجد تحذيرات لهذا العضو.")


# ------------------------- Group lock / unlock -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.قفل$"))
async def lock_group(event):
    if not await require_group_admin(event):
        return
    try:
        await tg.edit_permissions(event.chat_id, None, send_messages=False)
        await event.edit("🔒 تم تقييد إرسال الرسائل للأعضاء وفق صلاحيات تيليجرام الافتراضية.\nلفتح الإرسال استخدم `.فتح`.")
    except Exception as exc:
        await event.edit(f"❌ تعذر قفل المحادثة. قد لا تكون مجموعة فائقة أو قد لا تتوفر الصلاحية.\n`{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.فتح$"))
async def unlock_group(event):
    if not await require_group_admin(event):
        return
    try:
        await tg.edit_permissions(event.chat_id, None, send_messages=True)
        await event.edit("🔓 تم السماح بإرسال الرسائل وفق الصلاحيات الافتراضية الحالية.")
    except Exception as exc:
        await event.edit(f"❌ تعذر فتح الإرسال: `{exc}`")


# ------------------------- Welcome settings -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تفعيل ترحيب$"))
async def welcome_enable(event):
    if not await require_group_admin(event):
        return
    welcome_settings.setdefault(_chat_key(event), {})["enabled"] = True
    welcome_settings[_chat_key(event)].setdefault("text", "أهلاً {name} نورت المجموعة 🖤")
    save_json(WELCOME_SETTINGS_FILE, welcome_settings)
    await event.edit("✅ تم تفعيل الترحيب التلقائي.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تعطيل ترحيب$"))
async def welcome_disable(event):
    if not await require_group_admin(event):
        return
    welcome_settings.setdefault(_chat_key(event), {})["enabled"] = False
    save_json(WELCOME_SETTINGS_FILE, welcome_settings)
    await event.edit("✅ تم تعطيل الترحيب التلقائي.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.رسالة ترحيب\s+(.+)$"))
async def welcome_set_text(event):
    if not await require_group_admin(event):
        return
    text_value = event.pattern_match.group(1).strip()
    welcome_settings.setdefault(_chat_key(event), {})["text"] = text_value[:800]
    save_json(WELCOME_SETTINGS_FILE, welcome_settings)
    await event.edit("✅ تم حفظ رسالة الترحيب. استخدم `{name}` لإدراج اسم العضو.")


@tg.on(events.ChatAction)
async def welcome_new_member(event):
    try:
        if not (event.user_joined or event.user_added):
            return
        chat_id = str(event.chat_id)
        config = welcome_settings.get(chat_id, {})
        if not config.get("enabled"):
            return
        users = await event.get_users()
        if not users:
            return
        template = config.get("text", "أهلاً {name} نورت المجموعة 🖤")
        for user in users[:5]:
            name = clean_text(display_name(user))[:60]
            text_value = template.replace("{name}", name)
            await tg.send_message(event.chat_id, text_value)
    except Exception as exc:
        print("WELCOME ERROR:", exc)


# ------------------------- Anti-flood / duplicate protection -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تفعيل مكافحة التكرار$"))
async def antiflood_enable(event):
    if not await require_group_admin(event):
        return
    antiflood_settings[_chat_key(event)] = True
    save_json(ANTIFLOOD_FILE, antiflood_settings)
    await event.edit("🛡 تم تفعيل الحد من الإرسال السريع. ستحذف الرسائل الزائدة فقط دون طرد تلقائي.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تعطيل مكافحة التكرار$"))
async def antiflood_disable(event):
    if not await require_group_admin(event):
        return
    antiflood_settings.pop(_chat_key(event), None)
    save_json(ANTIFLOOD_FILE, antiflood_settings)
    await event.edit("✅ تم تعطيل الحد من الرسائل المتكررة.")


@tg.on(events.NewMessage(incoming=True))
async def antiflood_monitor(event):
    try:
        if not event.is_group or not event.sender_id:
            return
        if not antiflood_settings.get(str(event.chat_id), False):
            return
        # Admins and the account owner are not moderated by this filter.
        sender = await event.get_sender()
        if not sender or getattr(sender, "bot", False):
            return
        perms = await tg.get_permissions(event.chat_id, sender)
        if getattr(perms, "is_admin", False) or getattr(perms, "is_creator", False):
            return
        key = (str(event.chat_id), str(event.sender_id))
        now = time.monotonic()
        stamps = [t for t in _flood_windows.get(key, []) if now - t < 8]
        stamps.append(now)
        _flood_windows[key] = stamps
        if len(stamps) > 6:
            await event.delete()
    except Exception as exc:
        print("ANTIFLOOD ERROR:", exc)


# ------------------------- Admin / member information -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.المشرفين$"))
async def list_group_admins(event):
    if not event.is_group:
        return await event.edit("هذا الأمر للمجموعات فقط.")
    try:
        admins = await tg.get_participants(event.chat_id, limit=100, filter=types.ChannelParticipantsAdmins)
        if not admins:
            return await event.edit("لم أستطع جلب قائمة المشرفين.")
        lines = []
        for user in admins[:50]:
            uname = f"@{user.username}" if getattr(user, "username", None) else f"ID: {user.id}"
            lines.append(f"• {clean_text(display_name(user))} — {uname}")
        await event.edit("👮 **مشرفو المجموعة**\n" + "\n".join(lines))
    except Exception as exc:
        await event.edit(f"❌ تعذر جلب المشرفين: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.بحث عضو\s+(.+)$"))
async def search_group_member(event):
    if not event.is_group:
        return await event.edit("هذا الأمر للمجموعات فقط.")
    query = event.pattern_match.group(1).strip()
    try:
        users = await tg.get_participants(event.chat_id, limit=15, search=query)
        if not users:
            return await event.edit("لم أجد عضواً بهذا الاسم.")
        rows = []
        for user in users[:15]:
            uname = f"@{user.username}" if getattr(user, "username", None) else "بدون معرف"
            rows.append(f"• {clean_text(display_name(user))} — {uname} — `{user.id}`")
        await event.edit("🔎 **نتائج البحث**\n" + "\n".join(rows))
    except Exception as exc:
        await event.edit(f"❌ تعذر البحث: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.معلومات العضو$"))
async def member_info_alias(event):
    # Reuse the same implementation without relying on an edited message
    # to trigger a second outgoing-message handler.
    await show_id(event)


# ------------------------- Notes -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حفظ ملاحظة\s+(.+)$"))
async def save_note(event):
    raw = event.pattern_match.group(1)
    if "|" not in raw:
        return await event.edit("الصيغة: `.حفظ ملاحظة العنوان | نص الملاحظة`")
    title, body = [part.strip() for part in raw.split("|", 1)]
    if not title or not body:
        return await event.edit("يجب كتابة العنوان ونص الملاحظة.")
    notes_data.setdefault(str(event.sender_id), {})[title[:80]] = body[:3000]
    save_json(NOTES_FILE, notes_data)
    await event.edit(f"📝 تم حفظ الملاحظة: {title}")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.ملاحظة\s+(.+)$"))
async def read_note(event):
    title = event.pattern_match.group(1).strip()
    body = notes_data.get(str(event.sender_id), {}).get(title)
    await event.edit(f"📝 **{title}**\n{body}" if body else "لم أجد هذه الملاحظة.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حذف ملاحظة\s+(.+)$"))
async def delete_note(event):
    title = event.pattern_match.group(1).strip()
    user_notes = notes_data.get(str(event.sender_id), {})
    if user_notes.pop(title, None) is None:
        return await event.edit("لم أجد هذه الملاحظة.")
    if not user_notes:
        notes_data.pop(str(event.sender_id), None)
    save_json(NOTES_FILE, notes_data)
    await event.edit("✅ تم حذف الملاحظة.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الملاحظات$"))
async def list_notes(event):
    user_notes = notes_data.get(str(event.sender_id), {})
    if not user_notes:
        return await event.edit("لا توجد ملاحظات محفوظة.")
    await event.edit("📝 **ملاحظاتك**\n" + "\n".join(f"• {title}" for title in list(user_notes)[:50]))


# ------------------------- AI direct command / settings -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.سؤال\s+(.+)$"))
async def direct_ai_question(event):
    if not client_ai:
        return await event.edit("⚠️ أضف GROQ_API_KEY إلى Secrets لتشغيل الذكاء.")
    question = event.pattern_match.group(1).strip()
    await event.edit("🤖 أفكر في الإجابة...")
    answer = await ai_reply(question, SYSTEM_NORMAL)
    await event.edit(answer)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.عدد رسائلي$"))
async def my_message_count(event):
    total = int(message_stats.get(str(event.chat_id), {}).get(str(event.sender_id), 0))
    await event.edit(f"📊 عدد رسائلك المرصودة في هذه المحادثة منذ تشغيل الإحصاء: {total}")


# ------------------------- Update the 15 help pages -------------------------

MENU_PAGES[1] += "\n`.تحذير` بالرد - تسجيل تحذير\n`.تحذيراته` بالرد - عرض التحذيرات\n`.تصفير التحذيرات` بالرد - حذفها"
MENU_PAGES[2] += "\n`.تفعيل مكافحة التكرار` / `.تعطيل مكافحة التكرار`\nيحد من الإرسال السريع ويحذف الرسائل الزائدة فقط."
MENU_PAGES[3] += "\n`.قفل` / `.فتح` - تقييد/السماح بإرسال الرسائل\n`.المشرفين` - عرض المشرفين\n`.بحث عضو الاسم` - البحث في الأعضاء"
MENU_PAGES[11] += "\n`.تفعيل ترحيب` / `.تعطيل ترحيب`\n`.رسالة ترحيب النص` - تخصيص رسالة الترحيب، استخدم {name} للاسم."
MENU_PAGES[13] += "\n`.حفظ ملاحظة العنوان | النص`\n`.ملاحظة العنوان` / `.حذف ملاحظة العنوان` / `.الملاحظات`\n`.عدد رسائلي` - عدد رسائلك المرصودة\n`.سؤال النص` - سؤال مباشر للذكاء الاصطناعي."

print("🖤 BLACK HEART extensions loaded")

# ------------------------- Timed moderation / controlled cleanup -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حظر مؤقت\s+(\d{1,4})$"))
async def timed_ban(event):
    if not await require_group_admin(event):
        return
    user = await _target_from_reply(event)
    if not user:
        return
    minutes = int(event.pattern_match.group(1))
    if not 1 <= minutes <= 10080:
        return await event.edit("اختر مدة من دقيقة إلى 7 أيام.")
    try:
        await tg.edit_permissions(event.chat_id, user, datetime.now(timezone.utc) + timedelta(minutes=minutes), view_messages=True)
        await event.edit(f"🚫 تم حظر {display_name(user)} لمدة {minutes} دقيقة.")
    except Exception as exc:
        await event.edit(f"❌ تعذر الحظر المؤقت: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.كتم مؤقت\s+(\d{1,4})$"))
async def timed_mute(event):
    if not await require_group_admin(event):
        return
    user = await _target_from_reply(event)
    if not user:
        return
    minutes = int(event.pattern_match.group(1))
    if not 1 <= minutes <= 10080:
        return await event.edit("اختر مدة من دقيقة إلى 7 أيام.")
    try:
        await tg.edit_permissions(event.chat_id, user, datetime.now(timezone.utc) + timedelta(minutes=minutes), send_messages=False)
        await event.edit(f"🔇 تم كتم {display_name(user)} لمدة {minutes} دقيقة.")
    except Exception as exc:
        await event.edit(f"❌ تعذر الكتم المؤقت: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تنظيف\s+(\d{1,2})$"))
async def clean_recent_messages(event):
    if not await require_group_admin(event):
        return
    count = int(event.pattern_match.group(1))
    if not 1 <= count <= 20:
        return await event.edit("يمكن تنظيف 1 إلى 20 رسالة في المرة الواحدة.")
    try:
        ids = []
        async for msg in tg.iter_messages(event.chat_id, limit=count + 1):
            ids.append(msg.id)
        if event.id not in ids:
            ids.append(event.id)
        await tg.delete_messages(event.chat_id, ids)
    except Exception as exc:
        await event.edit(f"❌ تعذر تنظيف الرسائل: `{exc}`")


# ------------------------- Reminders -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.ذكرني\s+(\d{1,4})\s+(.+)$"))
async def remind_later(event):
    minutes = int(event.pattern_match.group(1))
    reminder_text = event.pattern_match.group(2).strip()
    if not 1 <= minutes <= 10080:
        return await event.edit("اختر مدة من دقيقة إلى 7 أيام.")
    try:
        await tg.send_message(
            event.chat_id,
            f"⏰ تذكيرك:\n{reminder_text}",
            schedule=datetime.now(timezone.utc) + timedelta(minutes=minutes),
        )
        await event.edit(f"✅ تم ضبط التذكير بعد {minutes} دقيقة.")
    except Exception as exc:
        await event.edit(f"❌ تعذر ضبط التذكير في هذه المحادثة: `{exc}`")


# ------------------------- Additional help text -------------------------

MENU_PAGES[1] += "\n`.حظر مؤقت 30` بالرد - حظر لمدة محددة\n`.كتم مؤقت 30` بالرد - كتم لمدة محددة\n`.تنظيف 10` - حذف آخر 10 رسائل (حتى 20)."
MENU_PAGES[12] += "\n`.ذكرني 15 النص` - إرسال تذكير مجدول بعد عدد الدقائق."


# =========================================================
# BLACK HEART - additional practical commands
# =========================================================

# ------------------------- Help / settings -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.(?:مساعدة|القائمة)$"))
async def help_alias(event):
    await event.edit(MENU_TEXT)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الاعدادات$"))
async def show_settings(event):
    await event.edit(
        "⚙️ **إعدادات BLACK HEART**\n"
        f"الذكاء الاصطناعي: {'مفعّل' if settings.get('ai', True) else 'متوقف'}\n"
        f"وضع المزاح: {'مفعّل' if settings.get('qasf', False) else 'متوقف'}\n"
        f"الردود التلقائية: {'مفعّلة' if settings.get('auto_replies', True) else 'متوقفة'}\n"
        f"مفتاح Groq: {'موجود' if client_ai else 'غير موجود'}\n"
        f"عدد الردود المحفوظة: {len(auto_replies)}\n"
        f"عدد الملاحظات: {sum(len(v) for v in notes_data.values())}"
    )


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تفعيل الردود$"))
async def enable_auto_replies(event):
    settings["auto_replies"] = True
    save_json(SETTINGS_FILE, settings)
    await event.edit("✅ تم تفعيل الردود التلقائية.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تعطيل الردود$"))
async def disable_auto_replies(event):
    settings["auto_replies"] = False
    save_json(SETTINGS_FILE, settings)
    await event.edit("✅ تم تعطيل الردود التلقائية.")


# ------------------------- Group default permission locks -------------------------

async def set_group_restriction(event, **permissions):
    if not await require_group_admin(event):
        return
    try:
        await tg.edit_permissions(event.chat_id, None, **permissions)
        labels = {
            "embed_links": "الروابط المضمنة",
            "send_media": "الوسائط",
            "send_stickers": "الملصقات وملفات GIF",
            "send_polls": "الاستطلاعات",
            "invite_users": "دعوة المستخدمين",
        }
        label = next((labels[k] for k in permissions if k in labels), "الصلاحية")
        state = next(iter(permissions.values()))
        await event.edit(f"{'🔓 تم فتح' if state else '🔒 تم قفل'} {label} للأعضاء.")
    except Exception as exc:
        await event.edit(f"❌ تعذر تغيير الصلاحية. تأكد من صلاحيات الحساب ونوع المجموعة.\n`{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.قفل روابط$"))
async def lock_links(event):
    if not await require_group_admin(event):
        return
    protected_chats[str(event.chat_id)] = True
    save_json(PROTECTED_FILE, protected_chats)
    await event.edit("🔒 تم تفعيل منع الروابط؛ ستحذف رسائل الروابط من غير المشرفين.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.فتح روابط$"))
async def unlock_links(event):
    if not await require_group_admin(event):
        return
    protected_chats.pop(str(event.chat_id), None)
    save_json(PROTECTED_FILE, protected_chats)
    await event.edit("🔓 تم السماح بالروابط وإيقاف منعها.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.قفل وسائط$"))
async def lock_media(event):
    await set_group_restriction(event, send_media=False)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.فتح وسائط$"))
async def unlock_media(event):
    await set_group_restriction(event, send_media=True)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.قفل ملصقات$"))
async def lock_stickers(event):
    await set_group_restriction(event, send_stickers=False)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.فتح ملصقات$"))
async def unlock_stickers(event):
    await set_group_restriction(event, send_stickers=True)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.قفل استطلاعات$"))
async def lock_polls(event):
    await set_group_restriction(event, send_polls=False)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.فتح استطلاعات$"))
async def unlock_polls(event):
    await set_group_restriction(event, send_polls=True)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.قفل دعوات$"))
async def lock_invites(event):
    await set_group_restriction(event, invite_users=False)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.فتح دعوات$"))
async def unlock_invites(event):
    await set_group_restriction(event, invite_users=True)


# ------------------------- Member / message information -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.رابط حساب$"))
async def account_link(event):
    user = await _target_from_reply(event)
    if not user:
        return
    username = getattr(user, "username", None)
    link = f"https://t.me/{username}" if username else f"tg://user?id={user.id}"
    await event.edit(f"🔗 رابط الحساب: {link}")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.معلومات الرسالة$"))
async def replied_message_info(event):
    if not event.is_reply:
        return await event.edit("رد على رسالة أولاً.")
    msg = await event.get_reply_message()
    if not msg:
        return await event.edit("لم أجد الرسالة المحددة.")
    sender = await msg.get_sender()
    media_name = "نعم" if msg.media else "لا"
    text_len = len(msg.raw_text or "")
    date_value = msg.date.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if msg.date else "غير متاح"
    await event.edit(
        "🧾 **معلومات الرسالة**\n"
        f"المعرف: `{msg.id}`\n"
        f"المرسل: {clean_text(display_name(sender)) if sender else 'غير معروف'}\n"
        f"معرف المرسل: `{getattr(sender, 'id', 'غير متاح')}`\n"
        f"التاريخ: `{date_value}`\n"
        f"عدد الأحرف: `{text_len}`\n"
        f"تحتوي وسيطاً: `{media_name}`"
    )


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.نسخ النص$"))
async def copy_replied_text(event):
    if not event.is_reply:
        return await event.edit("رد على رسالة نصية أولاً.")
    msg = await event.get_reply_message()
    if not msg or not msg.raw_text:
        return await event.edit("الرسالة لا تحتوي نصاً قابلاً للنسخ.")
    value = msg.raw_text[:3500]
    await event.edit(f"📋 النص المنسوخ:\n\n{value}")


# ------------------------- Leave messages -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تفعيل مغادرة$"))
async def enable_leave_message(event):
    if not await require_group_admin(event):
        return
    leave_settings.setdefault(_chat_key(event), {})["enabled"] = True
    leave_settings[_chat_key(event)].setdefault("text", "مع السلامة {name} 👋")
    save_json(LEAVE_SETTINGS_FILE, leave_settings)
    await event.edit("✅ تم تفعيل رسالة المغادرة.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تعطيل مغادرة$"))
async def disable_leave_message(event):
    if not await require_group_admin(event):
        return
    leave_settings.setdefault(_chat_key(event), {})["enabled"] = False
    save_json(LEAVE_SETTINGS_FILE, leave_settings)
    await event.edit("✅ تم تعطيل رسالة المغادرة.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.رسالة مغادرة\s+(.+)$"))
async def set_leave_message(event):
    if not await require_group_admin(event):
        return
    value = event.pattern_match.group(1).strip()
    leave_settings.setdefault(_chat_key(event), {})["text"] = value[:800]
    save_json(LEAVE_SETTINGS_FILE, leave_settings)
    await event.edit("✅ تم حفظ رسالة المغادرة. استخدم `{name}` لإدراج الاسم.")


@tg.on(events.ChatAction)
async def leave_member_message(event):
    try:
        if not event.user_left:
            return
        chat_id = str(event.chat_id)
        config = leave_settings.get(chat_id, {})
        if not config.get("enabled"):
            return
        users = await event.get_users()
        if not users:
            return
        template = config.get("text", "مع السلامة {name} 👋")
        for user in users[:3]:
            name = clean_text(display_name(user))[:60]
            await tg.send_message(event.chat_id, template.replace("{name}", name))
    except Exception as exc:
        print("LEAVE MESSAGE ERROR:", exc)


# ------------------------- Uptime / chat tools -------------------------

_SOURCE_STARTED_AT = time.monotonic()

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.مدة التشغيل$"))
async def uptime_command(event):
    seconds = int(time.monotonic() - _SOURCE_STARTED_AT)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    await event.edit(f"⏱ مدة تشغيل BLACK HEART: {days} يوم، {hours} ساعة، {minutes} دقيقة، {secs} ثانية.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.معرف المحادثة$"))
async def chat_id_command(event):
    await event.edit(f"🆔 معرف هذه المحادثة: `{event.chat_id}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.عدد الردود$"))
async def auto_reply_count(event):
    await event.edit(f"💬 عدد الردود المحفوظة: {len(auto_replies)}")


# Extend the help pages to match commands that are now implemented.
MENU_PAGES[1] += "\n`.حظر مؤقت 30` / `.كتم مؤقت 30` بالرد - لمدة محددة\n`.تنظيف 10` - تنظيف آخر 10 رسائل."
MENU_PAGES[2] += "\n`.قفل روابط` / `.فتح روابط` - منع/السماح بروابط الأعضاء\n`.قفل وسائط` / `.فتح وسائط`\n`.قفل ملصقات` / `.فتح ملصقات`\n`.قفل استطلاعات` / `.فتح استطلاعات`\n`.قفل دعوات` / `.فتح دعوات`"
MENU_PAGES[3] += "\n`.رابط حساب` بالرد - رابط العضو\n`.معلومات الرسالة` بالرد - بيانات الرسالة\n`.نسخ النص` بالرد - نسخ نص الرسالة"
MENU_PAGES[11] += "\n`.تفعيل مغادرة` / `.تعطيل مغادرة`\n`.رسالة مغادرة النص` - تخصيص رسالة المغادرة."
MENU_PAGES[13] += "\n`.الاعدادات` - عرض إعدادات السورس\n`.مدة التشغيل` - مدة عمل السورس\n`.معرف المحادثة` - معرف المحادثة\n`.تفعيل الردود` / `.تعطيل الردود`\n`.عدد الردود` - عدد الردود المحفوظة"


# =========================================================
# BLACK HEART - COMPLETE COMMAND EXPANSION
# Added: per-chat/global AI controls, interactive replies, safer mentions,
# dynamic AI entertainment, aligned ASCII art, controlled animations,
# simple playable games, and YouTube search links.
# Existing handlers and settings are preserved.
# =========================================================

import html as _bh_html
import re
from urllib.parse import quote_plus as _bh_quote_plus

AI_PAUSED_CHATS = set(str(x) for x in settings.get("ai_paused_chats", []))
AI_GLOBAL_ENABLED = bool(settings.get("ai_global_enabled", settings.get("ai", True)))
PENDING_AUTO_REPLY = {}
PENDING_DELETE_AUTO_REPLY = {}
FUN_HISTORY_FILE = "fun_history.json"
fun_history = load_json(FUN_HISTORY_FILE, {})
GAME_STATE = {}
ACTIVE_ANIMATIONS = {}


def _save_ai_state():
    settings["ai_global_enabled"] = AI_GLOBAL_ENABLED
    settings["ai_paused_chats"] = sorted(AI_PAUSED_CHATS)
    # Keep legacy key aligned for older versions of this source.
    settings["ai"] = AI_GLOBAL_ENABLED
    save_json(SETTINGS_FILE, settings)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.ايقاف ذكي هنا$"))
async def ai_pause_this_chat(event):
    AI_PAUSED_CHATS.add(str(event.chat_id))
    _save_ai_state()
    await event.edit("🛑 تم إيقاف ردود الذكاء الاصطناعي في هذه المحادثة فقط. بقية الأوامر ما زالت تعمل.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تشغيل ذكي هنا$"))
async def ai_resume_this_chat(event):
    AI_PAUSED_CHATS.discard(str(event.chat_id))
    _save_ai_state()
    await event.edit("✅ تم تشغيل الذكاء الاصطناعي في هذه المحادثة.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.ايقاف الذكاء للكل$"))
async def ai_pause_everywhere(event):
    global AI_GLOBAL_ENABLED
    AI_GLOBAL_ENABLED = False
    _save_ai_state()
    await event.edit("🛑 تم إيقاف الذكاء الاصطناعي في جميع المحادثات. بقية الأوامر والألعاب مستمرة.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تشغيل الذكاء للكل$"))
async def ai_resume_everywhere(event):
    global AI_GLOBAL_ENABLED
    AI_GLOBAL_ENABLED = True
    _save_ai_state()
    await event.edit("✅ تم تشغيل الذكاء الاصطناعي في جميع المحادثات غير الموقوفة محلياً.")


# Keep old global commands compatible with the new global/local split.
# The original .تشغيل ذكي and .ايقاف ذكي handlers remain available.

# ------------------------- Interactive auto-replies -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.اضف رد$"))
async def begin_interactive_auto_reply(event):
    key = (str(event.chat_id), str(event.sender_id))
    PENDING_AUTO_REPLY[key] = {"step": "trigger", "mode": "exact", "started": time.monotonic()}
    await event.edit("💬 أرسل الكلمة أو العبارة. سيرد فقط إذا كانت الرسالة مطابقة لها وحدها.\nللإلغاء: `.الغاء اضافة رد`")




@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.اضف رد مميز$"))
async def begin_interactive_special_auto_reply(event):
    key = (str(event.chat_id), str(event.sender_id))
    PENDING_AUTO_REPLY[key] = {"step": "trigger", "mode": "contains", "started": time.monotonic()}
    await event.edit("💬 أرسل الكلمة التي تريد مراقبتها. سيرد إذا ظهرت داخل أي رسالة حتى لو معها كلام آخر.\nللإلغاء: `.الغاء اضافة رد`")
@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حذف رد$"))
async def begin_delete_exact_auto_reply(event):
    key = (str(event.chat_id), str(event.sender_id))
    PENDING_DELETE_AUTO_REPLY[key] = {"mode": "exact", "started": time.monotonic()}
    PENDING_AUTO_REPLY.pop(key, None)
    await event.edit("🗑️ أرسل الكلمة أو العبارة المحفوظة التي تريد حذف ردّها.")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حذف رد مميز$"))
async def begin_delete_special_auto_reply(event):
    key = (str(event.chat_id), str(event.sender_id))
    PENDING_DELETE_AUTO_REPLY[key] = {"mode": "contains", "started": time.monotonic()}
    PENDING_AUTO_REPLY.pop(key, None)
    await event.edit("🗑️ أرسل الكلمة المحفوظة في الرد المميز التي تريد حذفها.")

@tg.on(events.NewMessage(outgoing=True))
async def delete_auto_reply_step(event):
    key = (str(event.chat_id), str(event.sender_id))
    state = PENDING_DELETE_AUTO_REPLY.get(key)
    if not state:
        return
    raw = (event.raw_text or "").strip()
    if not raw or raw.startswith("."):
        return
    if time.monotonic() - state.get("started", 0) > 300:
        PENDING_DELETE_AUTO_REPLY.pop(key, None)
        return
    trigger = raw.casefold()
    saved = auto_replies.get(trigger)
    wanted_mode = state.get("mode", "exact")
    if saved is None:
        PENDING_DELETE_AUTO_REPLY.pop(key, None)
        return await event.edit("❌ لا يوجد رد محفوظ بهذه الكلمة.")
    saved_mode = saved.get("mode", "exact") if isinstance(saved, dict) else "exact"
    if saved_mode != wanted_mode:
        PENDING_DELETE_AUTO_REPLY.pop(key, None)
        return await event.edit("❌ الرد موجود، لكنه من النوع الآخر. استخدم أمر الحذف المطابق لنوعه.")
    auto_replies.pop(trigger, None)
    save_json(AUTO_REPLIES_FILE, auto_replies)
    PENDING_DELETE_AUTO_REPLY.pop(key, None)
    await event.edit("✅ تم حذف الرد المحفوظ.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الغاء اضافة رد$"))
async def cancel_interactive_auto_reply(event):
    key = (str(event.chat_id), str(event.sender_id))
    PENDING_AUTO_REPLY.pop(key, None)
    await event.edit("تم إلغاء إضافة الرد.")


@tg.on(events.NewMessage(outgoing=True))
async def interactive_auto_reply_steps(event):
    key = (str(event.chat_id), str(event.sender_id))
    state = PENDING_AUTO_REPLY.get(key)
    if not state:
        return
    raw = (event.raw_text or "").strip()
    if not raw or raw.startswith("."):
        return
    if time.monotonic() - state.get("started", 0) > 300:
        PENDING_AUTO_REPLY.pop(key, None)
        return
    if state["step"] == "trigger":
        state["trigger"] = raw[:120]
        state["step"] = "answer"
        state["started"] = time.monotonic()
        await event.edit("✅ تم استلام الكلمة. أرسل الآن الرد الذي تريد أن يحفظه BLACK HEART.")
        return
    trigger = state.get("trigger", "").strip()
    if not trigger:
        PENDING_AUTO_REPLY.pop(key, None)
        return await event.edit("تعذر حفظ الرد؛ ابدأ من جديد بالأمر `.اضف رد`.")
    mode = state.get("mode", "exact")
    auto_replies[trigger.casefold()] = {"mode": mode, "answer": raw[:1500]}
    save_json(AUTO_REPLIES_FILE, auto_replies)
    PENDING_AUTO_REPLY.pop(key, None)
    mode_label = "مطابقة الرسالة وحدها" if mode == "exact" else "وجود الكلمة داخل الرسالة"
    await event.edit(f"🖤 تم حفظ الرد للكلمة: {trigger}\nطريقة التشغيل: {mode_label}")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تعديل رد\s+(.+)$"))
async def edit_saved_auto_reply(event):
    raw = event.pattern_match.group(1).strip()
    if "|" not in raw:
        return await event.edit("الصيغة: `.تعديل رد الكلمة | الرد الجديد`")
    trigger, answer = [x.strip() for x in raw.split("|", 1)]
    if trigger.lower() not in auto_replies:
        return await event.edit("لا يوجد رد محفوظ بهذه الكلمة.")
    if not answer:
        return await event.edit("اكتب الرد الجديد بعد علامة |.")
    auto_replies[trigger.lower()] = answer[:1500]
    save_json(AUTO_REPLIES_FILE, auto_replies)
    await event.edit("✅ تم تعديل الرد المحفوظ.")


# ------------------------- Mentions (bounded to avoid flooding) -------------------------

async def _mention_members(event, admins_only=False):
    if not event.is_group:
        return await event.edit("هذا الأمر يعمل داخل المجموعات فقط.")
    try:
        if admins_only:
            users = await tg.get_participants(event.chat_id, limit=100, filter=types.ChannelParticipantsAdmins)
        else:
            users = await tg.get_participants(event.chat_id, limit=100)
        selected = [u for u in users if not is_bot_account(u)][:20]
        if not selected:
            return await event.edit("لم أجد أعضاء مناسبين للمنشن.")
        chunks = []
        for user in selected:
            name = _bh_html.escape(clean_text(display_name(user))[:40])
            chunks.append(f'<a href="tg://user?id={user.id}">{name}</a>')
        label = "مشرفو المجموعة" if admins_only else "أعضاء المجموعة"
        body = "📣 " + label + " (حتى 20 حساباً في هذه الرسالة):\n" + "، ".join(chunks)
        await event.edit(body, parse_mode="html")
        if len(users) > 20:
            await event.respond("ملاحظة: تم وضع حد 20 منشن في الرسالة لتقليل الإزعاج واحترام قيود تيليجرام.")
    except Exception as exc:
        await event.edit(f"تعذر جلب الأعضاء أو إنشاء المنشن: `{exc}`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.منشن الكل$"))
async def mention_all_members(event):
    await _mention_members(event, admins_only=False)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.منشن المشرفين$"))
async def mention_all_admins(event):
    await _mention_members(event, admins_only=True)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الغاء المنشن$"))
async def cancel_mention(event):
    # This command removes the current command message; it cannot retract
    # notifications already delivered by Telegram.
    await event.edit("تم إلغاء أمر المنشن. لا يمكن سحب إشعار وصل للأعضاء سابقاً.")


# ------------------------- AI-generated entertainment -------------------------

async def _fresh_fun(event, category, instruction):
    chat_key = str(event.chat_id)
    history = fun_history.setdefault(chat_key, [])
    avoid = "\nتجنب تكرار هذه النتائج أو إعادة صياغتها: " + " | ".join(history[-12:])
    prompt = instruction + avoid + "\nأعطني نتيجة واحدة فقط، عربية، قصيرة، مناسبة للجميع، ولا تدّعِ أن معلومة غير مؤكدة حقيقة."
    await event.edit("🖤 لحظة أجهز لك شيئاً جديداً...")
    answer = await ai_reply(prompt, "أنت مولّد محتوى عربي متنوع. لا تكرر الإجابات السابقة. كن واضحاً ومناسباً للجميع.")
    if answer.startswith("⚠️"):
        return await event.edit(answer)
    history.append(answer[:220])
    fun_history[chat_key] = history[-20:]
    save_json(FUN_HISTORY_FILE, fun_history)
    await event.edit(answer)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حكمة$"))
async def ai_wisdom(event):
    await _fresh_fun(event, "wisdom", "اكتب حكمة جديدة ذات معنى عملي وليست مبتذلة.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.نكتة$"))
async def ai_joke(event):
    await _fresh_fun(event, "joke", "اكتب نكتة قصيرة ذكية وخفيفة دون إساءة لأي فئة أو شخص.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.اقتباس$"))
async def ai_quote(event):
    await _fresh_fun(event, "quote", "اكتب اقتباساً أصلي الصياغة عن الحياة أو التعلم أو الصبر، دون نسبته لشخص حقيقي.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.معلومة$"))
async def ai_fact(event):
    await _fresh_fun(event, "fact", "اذكر معلومة علمية أو تاريخية عامة معروفة، بصياغة دقيقة وتجنب الأرقام المشكوك فيها.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.هل تعلم$"))
async def ai_did_you_know(event):
    await _fresh_fun(event, "did_you_know", "اكتب فقرة هل تعلم قصيرة بمعلومة موثوقة ومعروفة.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حظي$"))
async def ai_luck(event):
    await _fresh_fun(event, "luck", "اكتب رسالة حظ وتفاؤل مرحة للتسلية فقط، ولا تقدم تنبؤاً حقيقياً بالمستقبل.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.قصف$"))
async def ai_qasf_one_liner(event):
    target = ""
    if event.is_reply:
        reply = await event.get_reply_message()
        who = await reply.get_sender() if reply else None
        target = f"اكتب مزحة خفيفة موجهة إلى {clean_text(display_name(who)) if who else 'الصديق'} دون تجريح. "
    else:
        target = "اكتب قفشة مرحة عامة. "
    answer = await ai_reply(target + "اختم بعبارة اعتذار مازحة متنوعة مثل أمزح أمزح 😹🤣، دون تكرار حرفي دائماً.", SYSTEM_QASF)
    await event.edit(answer)


# ------------------------- Telegram-aligned ASCII art -------------------------

ASCII_ART = {
    # ASCII-only art: avoids emoji and backslash-width inconsistencies.
    "قلب": "   ##   ##\n  #### ####\n ###########\n  #########\n   #######\n    #####\n     ###\n      #",
    "وردة": "    .-.-.\n  .'  *  '.\n /  * * *  /\n |   * *   |\n  '.  *  .'\n    '---'\n      |\n   /  |  /\n  /   | /\n      |\n     / |",
    "فراشة": "  .==.       .==.\n /    >     <    /\n<  **  >---<  **  >\n >    /     /    <\n  '=='       '=='\n      /   /\n       / /",
    "تاج": "       ^\n  ^   ^^^   ^\n  |  |   |  |\n  |_________|\n  |         |\n  |_________|",
    "نجمة": "      |\n   ---*---\n    / | /\n      |",
    "قطة": " /^^^\n( o.o )\n > ^ <",
    "دب": " (o_o)\n /|_|\n  | |",
    "أرنب": " ( / )\n ( o.o )\n / > <",
    "بيت": "     ^\n    /|\n   /_|\n   |[]|\n   |__|\n   |__|",
    "سيارة": "      ______\n ____/|_||_|____\n|   _       _   |\n'--(o)-----(o)--'",
    "شجرة": "      #\n     ###\n    #####\n   #######\n      |\n      |",
}


async def _send_ascii(event, name):
    art = ASCII_ART.get(name)
    if not art:
        return await event.edit("لا توجد رسمة بهذا الاسم.")
    # <pre> gives a fixed-width block in Telegram. ASCII drawings avoid
    # most emoji-width inconsistencies across Android/iOS fonts.
    await event.edit(f"<pre>{_bh_html.escape(art)}</pre>", parse_mode="html")


for _art_name in ASCII_ART:
    async def _art_handler(event, _name=_art_name):
        await _send_ascii(event, _name)
    tg.add_event_handler(
        _art_handler,
        events.NewMessage(outgoing=True, pattern=r"^\." + re.escape(_art_name) + r"$")
    )


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.اسم\s+(.+)$"))
async def draw_name(event):
    name = event.pattern_match.group(1).strip()[:24]
    # Boxed monospace name: stable alignment in Telegram.
    width = max(8, min(28, len(name) + 4))
    line = "+" + "-" * (width - 2) + "+"
    middle = "| " + name[:width - 4].center(width - 4) + " |"
    await event.edit(f"<pre>{_bh_html.escape(line + chr(10) + middle + chr(10) + line)}</pre>", parse_mode="html")


# ------------------------- Controlled emoji animations -------------------------

ANIMATION_FRAMES = {
    "هه": ["😄 🖤 😁 🖤 😆", "🖤 😂 🖤 🤣 🖤", "😸 🖤 😹 🖤 😄", "😁 🖤 😆 🖤 😂"],
    "مح": ["😗 💋 😙 💋 😚", "💋 😘 💋 😗 💋", "😙 💋 😚 💋 😘"],
    "حب": ["🤍 🤎 🖤 💜 💙", "💚 💛 🧡 ❤️ 💓", "💞 💕 ❣️ 💖 💘", "💝 💗 🤍 🤎 🖤"],
}


async def _run_animation(event, name):
    chat_key = str(event.chat_id)
    previous = ACTIVE_ANIMATIONS.get(chat_key)
    if previous and not previous.done():
        previous.cancel()
    frames = ANIMATION_FRAMES[name]
    task = asyncio.current_task()
    ACTIVE_ANIMATIONS[chat_key] = task
    try:
        await event.edit(frames[0])
        # 21 edits, deliberately paced to reduce Telegram flood limits.
        for index in range(1, 21):
            await asyncio.sleep(1.1)
            await event.edit(frames[index % len(frames)])
        await event.edit(frames[-1] + "\n🖤")
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        print("ANIMATION STOPPED:", exc)
    finally:
        if ACTIVE_ANIMATIONS.get(chat_key) is task:
            ACTIVE_ANIMATIONS.pop(chat_key, None)


for _animation_name in ANIMATION_FRAMES:
    async def _animation_handler(event, _name=_animation_name):
        await _run_animation(event, _name)
    tg.add_event_handler(
        _animation_handler,
        events.NewMessage(outgoing=True, pattern=r"^\." + re.escape(_animation_name) + r"$")
    )


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.ايقاف الحركة$"))
async def stop_animation(event):
    task = ACTIVE_ANIMATIONS.get(str(event.chat_id))
    if task and not task.done():
        task.cancel()
        await event.edit("⏹ تم إيقاف الحركة.")
    else:
        await event.edit("لا توجد حركة تعمل في هذه المحادثة.")


# ------------------------- Playable mini-games -------------------------


XO_GAMES = {}


def _xo_winner(board):
    wins = ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6))
    for mark in ("X", "O"):
        if any(all(board[i] == mark for i in line) for line in wins):
            return mark
    if all(value in ("X", "O") for value in board):
        return "draw"
    return None


def _xo_board_text(board):
    cells = [value if value in ("X", "O") else str(i + 1) for i, value in enumerate(board)]
    return "🎮 **BLACK HEART | XO**\n\n" + " | ".join(cells[:3]) + "\n-----------\n" + " | ".join(cells[3:6]) + "\n-----------\n" + " | ".join(cells[6:])


def _xo_ai_move(board, ai_mark, human_mark):
    empty = [i for i, value in enumerate(board) if value not in ("X", "O")]
    if not empty:
        return None
    for mark in (ai_mark, human_mark):
        for pos in empty:
            test = board[:]
            test[pos] = mark
            wins = ((0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6))
            if any(all(test[i] == mark for i in line) for line in wins):
                return pos
    if 4 in empty:
        return 4
    corners = [i for i in (0, 2, 6, 8) if i in empty]
    return random.choice(corners or empty)


async def _xo_send_board(chat_id, state, note):
    await tg.send_message(chat_id, _xo_board_text(state["board"]) + "\n\n" + note)


async def _xo_finish(chat_id, state, result):
    state["finished"] = True
    if result == "draw":
        note = "🤝 تعادل! انتهت اللعبة."
    elif state["mode"] == "ai":
        note = "🎉 فزت!" if result == state["human_mark"] else "🤖 فاز الذكاء الاصطناعي."
    else:
        note = f"🏆 فاز اللاعب {result}!"
    await _xo_send_board(chat_id, state, note)


async def _xo_handle_text(event, outgoing):
    chat_id = int(event.chat_id)
    key = str(chat_id)
    state = XO_GAMES.get(key)
    if not state:
        return
    text_value = (event.raw_text or "").strip().lower()
    sender = int(event.sender_id or 0)

    if state.get("finished"):
        return

    if state["stage"] == "mode":
        if not outgoing or sender != state["owner"]:
            return
        if text_value not in ("ذكي", "شخص"):
            return
        state["mode"] = "ai" if text_value == "ذكي" else "pvp"
        state["stage"] = "mark"
        await tg.send_message(chat_id, "اختر رمزك بإرسال حرف واحد: X أو O")
        return

    if state["stage"] == "mark":
        if not outgoing or sender != state["owner"] or text_value.upper() not in ("X", "O"):
            return
        mark = text_value.upper()
        state["human_mark"] = mark
        state["board"] = [" "] * 9
        if state["mode"] == "ai":
            state["ai_mark"] = "O" if mark == "X" else "X"
            state["stage"] = "playing"
            state["turn"] = "X"
            if state["ai_mark"] == "X":
                pos = _xo_ai_move(state["board"], state["ai_mark"], mark)
                state["board"][pos] = state["ai_mark"]
                state["turn"] = mark
            await _xo_send_board(chat_id, state, "أرسل رقم الخانة من 1 إلى 9 عندما يأتي دورك.")
        else:
            state["stage"] = "join"
            state["players"] = {mark: state["owner"]}
            await tg.send_message(chat_id, f"تم اختيار {mark}. ينتظر لاعباً آخر ليرسل الرمز الآخر ({'O' if mark == 'X' else 'X'}) للانضمام.")
        return

    if state["stage"] == "join":
        other_mark = "O" if state["human_mark"] == "X" else "X"
        if outgoing or text_value.upper() != other_mark or sender == state["owner"]:
            return
        state["players"][other_mark] = sender
        state["stage"] = "playing"
        state["turn"] = "X"
        await _xo_send_board(chat_id, state, "بدأت اللعبة! دور اللاعب X أولاً. أرسل رقم الخانة من 1 إلى 9.")
        return

    if state["stage"] != "playing" or text_value not in tuple(str(i) for i in range(1, 10)):
        return

    mark = state.get("turn")
    if state["mode"] == "ai":
        if not outgoing or sender != state["owner"] or mark != state["human_mark"]:
            return
    else:
        expected_id = state.get("players", {}).get(mark)
        if expected_id != sender or outgoing != (sender == state["owner"]):
            return

    pos = int(text_value) - 1
    if state["board"][pos] in ("X", "O"):
        if outgoing:
            await tg.send_message(chat_id, "هذه الخانة محجوزة. اختر رقماً آخر من 1 إلى 9.")
        return
    state["board"][pos] = mark
    result = _xo_winner(state["board"])
    if result:
        await _xo_finish(chat_id, state, result)
        return

    state["turn"] = "O" if mark == "X" else "X"
    if state["mode"] == "ai":
        ai_mark = state["ai_mark"]
        ai_pos = _xo_ai_move(state["board"], ai_mark, state["human_mark"])
        if ai_pos is not None:
            state["board"][ai_pos] = ai_mark
        result = _xo_winner(state["board"])
        if result:
            await _xo_finish(chat_id, state, result)
            return
        state["turn"] = state["human_mark"]
        await _xo_send_board(chat_id, state, "دورك الآن. أرسل رقم الخانة من 1 إلى 9.")
    else:
        await _xo_send_board(chat_id, state, f"دور اللاعب {state['turn']} — أرسل رقم الخانة من 1 إلى 9.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.اكس او$"))
async def start_tic_tac_toe(event):
    XO_GAMES[str(event.chat_id)] = {
        "owner": int(event.sender_id), "stage": "mode", "mode": None,
        "board": [" "] * 9, "finished": False
    }
    await event.edit("🎮 **BLACK HEART | XO**\n\nطريقة اللعب؟\nأرسل: ذكي أو شخص")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^(ذكي|شخص|[xXoO]|[1-9])$"))
async def xo_outgoing_text(event):
    await _xo_handle_text(event, True)


@tg.on(events.NewMessage(incoming=True, pattern=r"^([xXoO]|[1-9])$"))
async def xo_incoming_text(event):
    await _xo_handle_text(event, False)


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.خمن رقم$"))
async def start_number_guess(event):
    GAME_STATE[str(event.chat_id)] = {"type": "guess", "number": random.randint(1, 20), "tries": 0}
    await event.edit("🔢 اخترت رقماً من 1 إلى 20. حاول تخمينه بالأمر `.تخمين رقم`.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تخمين\s+(\d{1,2})$"))
async def number_guess(event):
    state = GAME_STATE.get(str(event.chat_id))
    if not state or state.get("type") != "guess":
        return await event.edit("ابدأ أولاً بالأمر `.خمن رقم`.")
    value = int(event.pattern_match.group(1))
    if not 1 <= value <= 20:
        return await event.edit("اختر رقماً من 1 إلى 20.")
    state["tries"] += 1
    if value == state["number"]:
        tries = state["tries"]
        GAME_STATE.pop(str(event.chat_id), None)
        await event.edit(f"🎉 صحيح! الرقم هو {value}. عدد محاولاتك: {tries}.")
    elif state["tries"] >= 7:
        answer = state["number"]
        GAME_STATE.pop(str(event.chat_id), None)
        await event.edit(f"انتهت المحاولات السبع. الرقم كان {answer}. جرّب مرة أخرى بالأمر `.خمن رقم`.")
    else:
        await event.edit(("⬆️ أكبر" if value < state["number"] else "⬇️ أصغر") + f" — المحاولة {state['tries']} من 7.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.الغاء اللعبة$"))
async def cancel_game(event):
    GAME_STATE.pop(str(event.chat_id), None)
    await event.edit("تم إنهاء اللعبة الحالية.")


# ------------------------- YouTube search -------------------------

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.يوت\s+(.+)$"))
async def youtube_search(event):
    query = event.pattern_match.group(1).strip()
    if not query:
        return await event.edit("اكتب اسم الأغنية أو المقطع بعد `.يوت`.")
    link = "https://www.youtube.com/results?search_query=" + _bh_quote_plus(query)
    await event.edit(f"▶️ بحث يوتيوب عن: **{_bh_html.escape(query)}**\n{link}\n\nافتح النتائج لاختيار المقطع الصحيح. لا يوفر هذا الأمر تنزيل محتوى محمي بحقوق النشر.", parse_mode="html")




@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.لغز$"))
async def ai_riddle(event):
    prompt = (
        "أنشئ لغزاً عربياً جديداً قصيراً ومناسباً للجميع. "
        "اكتب بالضبط سطرين بهذا الشكل:\nالسؤال: ...\nالإجابة: ...\n"
        "لا تضف شرحاً أو خيارات."
    )
    await event.edit("🧩 أجهز لك لغزاً جديداً...")
    result = await ai_reply(prompt, "أنت كاتب ألغاز عربية. اجعل اللغز واضحاً وله إجابة محددة.")
    question, answer = result, "لم أتمكن من استخراج الإجابة؛ جرّب لغزاً آخر."
    for line in result.splitlines():
        if line.strip().startswith("السؤال:"):
            question = line.split(":", 1)[1].strip()
        elif line.strip().startswith("الإجابة:"):
            answer = line.split(":", 1)[1].strip()
    pending_riddles[str(event.chat_id)] = answer
    await event.edit(f"🧩 {question}\n\nللإجابة اكتب: `.جواب`")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.منشن مخفي$"))
async def hidden_mention_replied_user(event):
    user = await get_replied_user(event)
    if not user:
        return
    # Telegram's user-id deep link displays only the supplied name.
    label = _bh_html.escape(clean_text(display_name(user)))
    await event.edit(f'<a href="tg://user?id={user.id}">{label}</a>', parse_mode="html")

# ------------------------- Update help pages -------------------------

MENU_PAGES[5] += "\n`.منشن مخفي` بالرد - منشن باسم ظاهر فقط\n`.منشن الكل` - منشن محدود حتى 20 عضواً\n`.منشن المشرفين` - منشن المشرفين\n`.الغاء المنشن` - إلغاء الأمر الحالي"
MENU_PAGES[10] += "\n`.ايقاف ذكي هنا` / `.تشغيل ذكي هنا` - إيقاف/تشغيل الذكاء في المحادثة\n`.ايقاف الذكاء للكل` / `.تشغيل الذكاء للكل` - تحكم عام\n`.معلومة` / `.هل تعلم` / `.حظي` / `.قصف`"
MENU_PAGES[11] += "\n`.اضف رد` - رد عند تطابق الرسالة وحدها\n`.اضف رد مميز` - رد عند وجود الكلمة داخل الرسالة\n`.حذف رد` ثم أرسل الكلمة - حذف الرد المطابق\n`.حذف رد مميز` ثم أرسل الكلمة - حذف الرد المميز\n`.تعديل رد الكلمة | الرد الجديد` - تعديل رد"
MENU_PAGES[15] += "\n`.قلب` `.وردة` `.فراشة` `.تاج` `.نجمة` `.قطة` `.دب` `.أرنب` `.بيت` `.سيارة` `.شجرة`\n`.اسم الاسم` - رسم الاسم\n`.هه` / `.مح` / `.حب` - حركة رموز (21 تعديلاً)\n`.ايقاف الحركة` - إيقاف الحركة\n`.اكس او` - لعبة XO بأزرار تفاعلية\n`.خمن رقم` / `.تخمين 7` - لعبة تخمين\n`.الغاء اللعبة` - إنهاء اللعبة\n`.يوت اسم المقطع` - البحث في يوتيوب"

print("🖤 BLACK HEART full command expansion loaded")