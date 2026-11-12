import html
import asyncio
from telethon import events

# إضافات BLACK HEART - تُحمّل بعد black_heart.py
from black_heart import tg, display_name, clean_text, user_bio, user_role, _bh_html, ASCII_ART, MENU_PAGES

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

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.(?:كشف|ا)$"))
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

@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.انتحال$"))
async def blackheart_impersonation_notice(event):
    await event.edit(
        "⚠️ أمر الانتحال الذي ينسخ هوية شخص آخر قد يضلّل أعضاء المجموعة. "
        "لن أغيّر اسمك أو صورتك لتقليد حساب شخص آخر. "
        "يمكنك استخدام .اا لعرض صورتك و.كشف لعرض بيانات الحساب."
    )

MENU_PAGES[4] += "\n`.كشف` أو `.ا` بالرد - كشف بيانات الحساب\n`.اا` أو `.صورتي` - إرسال صورة الحساب، وبالرد صورة صاحب الرسالة\n"
MENU_PAGES[5] += "\n`.تاك نص` - إرسال إعلان نصي دون منشن جماعي\n"
MENU_PAGES[15] += "\n`.ضحك` - حركة ضحك\n`.قلب` / `.شجرة` / `.سيارة` / `.فراشة` - رسومات محسّنة\n"

print("🖤 BLACK HEART profile, photo, art and fun extensions loaded")
