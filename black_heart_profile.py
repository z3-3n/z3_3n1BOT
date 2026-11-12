import html
import asyncio
import json
from telethon import events, functions

# إضافات BLACK HEART - تُحمّل بعد black_heart.py
from black_heart import tg, display_name, clean_text, user_bio, user_role, _bh_html, ASCII_ART, MENU_PAGES, data_file

# رسومات ASCII ثابتة العرض؛ تجنب الإيموجي داخل الرسم لأنها تختلف في عرضها بين الأجهزة.
ASCII_ART.update({
    "قلب": "   **   **\n  **** ****\n ***********\n  *********\n   *******\n    *****\n     ***\n      *",
    "شجرة": "       /\\n      /  \\n     /    \\n    /______\\n       ||\n       ||\n     __||__",
    "سيارة": "       __________\n  ____/| ______ |\\____\n |    | |______| |    |\n |____|__________|____|\n   O              O",
    "فراشة": "   .==-.       .-==.\n  /     \\     /     \\n (       )---(       )\n  \\     /     \\     /\n   '==-'       '-=='\n       \\     /\n        \\   /\n         \\ /",
})

async def _get_target(event):
    if event.is_reply:
        msg = await event.get_reply_message()
        return await msg.get_sender() if msg else None
    return await event.get_sender()

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.كشف$"))
async def blackheart_profile_info(event):
    user = await _get_target(event)
    if not user:
        return await event.edit("❌ تعذّر تحديد الحساب.")
    name = html.escape(clean_text(display_name(user)))
    username = getattr(user, "username", None)
    username_text = "@" + username if username else "لا يوجد"
    bio = html.escape(clean_text(await user_bio(user)))
    role = await user_role(event.chat_id, user) if event.is_group else "—"
    premium = "نعم 💎" if getattr(user, "premium", False) else "لا"
    bot_status = "بوت" if getattr(user, "bot", False) else "مستخدم"
    text = (
        "🖤 **BLACK HEART | كشف الحساب**\n"
        "━━━━━━━━━━━━━━\n"
        f"👤 الاسم: {name}\n"
        f"🔗 المعرف: {html.escape(username_text)}\n"
        f"🆔 ID: `{user.id}`\n"
        f"👑 الرتبة: {html.escape(role)}\n"
        f"💎 Premium: {premium}\n"
        f"🤖 النوع: {bot_status}\n"
        f"📝 النبذة: {bio}\n"
        "━━━━━━━━━━━━━━"
    )
    await event.edit(text)

async def _send_profile_photo(event, target):
    try:
        photo = await tg.download_profile_photo(target, file=bytes)
        if not photo:
            return await event.edit("❌ هذا الحساب لا يملك صورة ملف شخصي متاحة.")
        await tg.send_file(event.chat_id, photo, caption=f"🖤 صورة الملف الشخصي — {clean_text(display_name(target))}")
        await event.delete()
    except Exception as exc:
        print("PROFILE PHOTO ERROR:", exc)
        await event.edit("❌ تعذّر جلب صورة الملف الشخصي.")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.(?:اا|صورتي)$"))
async def blackheart_my_photo(event):
    target = await _get_target(event)
    if not target:
        return await event.edit("❌ تعذّر تحديد الحساب.")
    await _send_profile_photo(event, target)

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.ضحك$"))
async def blackheart_laugh(event):
    frames = ["😂 🤣 😹 🤣 😂", "😹 😂 🤣 😂 😹", "🤣 😆 😂 😆 🤣", "😂 🖤 🤣 🖤 😹"]
    try:
        await event.edit(frames[0])
        for frame in frames[1:]:
            await asyncio.sleep(1.2)
            await event.edit(frame)
        await event.edit("😂🤣😹")
    except Exception as exc:
        print("LAUGH ANIMATION ERROR:", exc)

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.تاك(?:\s+(.+))?$"))
async def blackheart_announcement(event):
    # رسالة إعلان عادية دون منشن جماعي أو إزعاج جميع الأعضاء.
    message = (event.pattern_match.group(1) or "السلام عليكم").strip()
    if len(message) > 1000:
        return await event.edit("❌ الرسالة طويلة جداً؛ الحد 1000 حرف.")
    await event.edit("📢 " + message)

IMPERSONATION_BACKUP = data_file("profile_restore.json")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.انتحال$"))
async def blackheart_impersonate_demo(event):
    if not event.is_reply:
        return await event.edit("↩️ رد على حساب الشخص ثم أرسل .انتحال. للرجوع أرسل .اعادة.")
    replied = await event.get_reply_message()
    target = await replied.get_sender() if replied else None
    if not target or not getattr(target, "id", None):
        return await event.edit("❌ لم أستطع تحديد الحساب.")
    me = await tg.get_me()
    if me.id == target.id:
        return await event.edit("هذا حسابك بالفعل.")
    if IMPERSONATION_BACKUP.exists():
        return await event.edit("⚠️ توجد محاكاة سابقة؛ استخدم .اعادة أولاً.")
    backup = {"first_name": me.first_name or "", "last_name": me.last_name or "", "about": await user_bio(me)}
    try:
        with IMPERSONATION_BACKUP.open("w", encoding="utf-8") as fp:
            json.dump(backup, fp, ensure_ascii=False)
        await tg(functions.account.UpdateProfileRequest(
            first_name=(getattr(target, "first_name", None) or " "),
            last_name=(getattr(target, "last_name", None) or ""),
            about=(await user_bio(target))[:70],
        ))
        await event.edit("🎭 تمت محاكاة الاسم والنبذة مؤقتاً للعرض. لم يتغير المعرف أو الصورة. أرسل .اعادة للرجوع.")
    except Exception as exc:
        IMPERSONATION_BACKUP.unlink(missing_ok=True)
        await event.edit(f"❌ تعذّر تنفيذ المحاكاة: {exc}")

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.اعادة$"))
async def blackheart_restore_profile(event):
    if not IMPERSONATION_BACKUP.exists():
        return await event.edit("ℹ️ لا توجد محاكاة محفوظة؛ حسابك على وضعه الأصلي.")
    try:
        with IMPERSONATION_BACKUP.open("r", encoding="utf-8") as fp:
            backup = json.load(fp)
        await tg(functions.account.UpdateProfileRequest(
            first_name=backup.get("first_name") or " ",
            last_name=backup.get("last_name") or "",
            about=(backup.get("about") or "")[:70],
        ))
        IMPERSONATION_BACKUP.unlink(missing_ok=True)
        await event.edit("✅ رجع اسم حسابك ونبذته كما كانا.")
    except Exception as exc:
        await event.edit(f"❌ تعذّرت الاستعادة: {exc}")

MENU_PAGES[4] += "\n`.كشف` بالرد - كشف بيانات الحساب\n`.اا` أو `.صورتي` - إرسال صورة الحساب، وبالرد صورة صاحب الرسالة\n`.انتحال` بالرد - محاكاة الاسم والنبذة مؤقتاً\n`.اعادة` - استعادة الاسم والنبذة\n"
MENU_PAGES[5] += "\n`.تاك نص` - إرسال إعلان نصي دون منشن جماعي\n"
MENU_PAGES[15] += "\n`.ضحك` - حركة ضحك\n`.انتحال` بالرد / `.اعادة` - محاكاة مؤقتة ثم استعادة الحساب\n`.قلب` / `.شجرة` / `.سيارة` / `.فراشة` - رسومات محسّنة\n"

MENU_PAGES[1] += "\n`.رفع مطور` بالرد - إضافة مطور\n`.حذف مطور` أو `.مسح مطور` بالرد - حذف مطور\n`.المطورين` - عرض قائمة المطورين"

print("🖤 BLACK HEART profile, photo, art and fun extensions loaded")
