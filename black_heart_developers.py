"""Persistent developer access for BLACK HEART.

Authorized developers can issue existing dot-commands from either private chats
or groups. Their incoming command is re-sent by the userbot so the existing
outgoing command handlers execute without rewriting the whole command system.
"""
from telethon import events
from black_heart import tg, is_bot_account, load_json, save_json

DEVELOPERS_FILE = "developers.json"
developers = load_json(DEVELOPERS_FILE, [])
developers = {str(x) for x in developers if str(x).isdigit()}


def _save_developers():
    save_json(DEVELOPERS_FILE, sorted(developers))


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.رفع مطور$"))
async def promote_developer(event):
    if not event.is_reply:
        return await event.edit("❌ رد على رسالة الشخص ثم أرسل: .رفع مطور")
    reply = await event.get_reply_message()
    user = await reply.get_sender() if reply else None
    if not user or not getattr(user, "id", None):
        return await event.edit("❌ لم أستطع تحديد صاحب الرسالة.")
    if is_bot_account(user):
        return await event.edit("❌ لا يمكن ترقية حساب بوت.")
    developers.add(str(user.id))
    _save_developers()
    await event.edit(f"🖤 تم رفع {getattr(user, 'first_name', None) or 'المستخدم'} إلى مطور. يستطيع الآن تنفيذ أوامر BLACK HEART من الخاص أو المجموعات.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.حذف مطور$"))
async def demote_developer(event):
    if not event.is_reply:
        return await event.edit("❌ رد على رسالة المطور ثم أرسل: .حذف مطور")
    reply = await event.get_reply_message()
    user = await reply.get_sender() if reply else None
    if not user or not getattr(user, "id", None):
        return await event.edit("❌ لم أستطع تحديد صاحب الرسالة.")
    if str(user.id) not in developers:
        return await event.edit("هذا الحساب ليس مطوراً.")
    developers.discard(str(user.id))
    _save_developers()
    await event.edit("✅ تم سحب صلاحية المطور.")


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.المطورين$"))
async def list_developers(event):
    if not developers:
        return await event.edit("لا يوجد مطورون إضافيون حالياً.")
    lines = []
    for user_id in sorted(developers):
        try:
            user = await tg.get_entity(int(user_id))
            name = getattr(user, "first_name", None) or "مستخدم"
            lines.append(f"• {name} — {user_id}")
        except Exception:
            lines.append(f"• {user_id}")
    await event.edit("🖤 **مطورو BLACK HEART**\n" + "\n".join(lines))


@tg.on(events.NewMessage(incoming=True))
async def developer_command_bridge(event):
    sender_id = str(event.sender_id or "")
    if not sender_id or sender_id not in developers:
        return
    text = (event.raw_text or "").strip()
    if not text.startswith(".") or text in {".رفع مطور", ".حذف مطور", ".المطورين"}:
        return
    try:
        sender = await event.get_sender()
        if not sender or is_bot_account(sender):
            return
        # Preserve the reply target so commands such as moderation commands
        # continue to work when issued by a developer.
        reply_to = None
        if event.is_reply:
            replied = await event.get_reply_message()
            reply_to = replied.id if replied else None
        await tg.send_message(event.chat_id, text, reply_to=reply_to)
        await event.delete()
    except Exception as exc:
        print("DEVELOPER COMMAND BRIDGE ERROR:", exc)
