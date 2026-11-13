"""Persistent developer access for BLACK HEART.

Developer commands are dispatched through the existing outgoing command handlers.
This preserves the original command implementation and its reply/edit behavior.
"""
import inspect
from telethon import events
import black_heart as bh
from black_heart import tg, is_bot_account, load_json, save_json, settings

DEVELOPERS_FILE = "developers.json"
developers = load_json(DEVELOPERS_FILE, [])
developers = {str(x) for x in developers if str(x).isdigit()}


def _save_developers():
    save_json(DEVELOPERS_FILE, sorted(developers))


async def _dispatch_existing_command(sent_message):
    """Run the matching registered outgoing NewMessage handlers for a sent copy."""
    synthetic_event = events.NewMessage.Event(sent_message)
    synthetic_event._set_client(tg)

    matched = 0
    for callback, builder in tg.list_event_handlers():
        if not isinstance(builder, events.NewMessage) or not builder.outgoing:
            continue
        try:
            # Evaluate the registered regex directly and attach its match to the
            # synthetic outgoing event. This avoids Telethon filter state being
            # absent on messages created by send_message from the developer bridge.
            pattern = getattr(builder, "pattern", None)
            if pattern:
                raw_text = sent_message.raw_text or ""
                if callable(pattern):
                    pattern_match = pattern(raw_text)
                elif hasattr(pattern, "match"):
                    pattern_match = pattern.match(raw_text)
                else:
                    pattern_match = None
                if not pattern_match:
                    continue
                synthetic_event.pattern_match = pattern_match
            else:
                accepted = builder.filter(synthetic_event)
                if inspect.isawaitable(accepted):
                    accepted = await accepted
                if not accepted:
                    continue

            matched += 1
            await callback(synthetic_event)
        except events.StopPropagation:
            break
        except Exception as exc:
            print("DEVELOPER COMMAND HANDLER ERROR:", getattr(callback, "__name__", repr(callback)), exc)

    return matched


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


@tg.on(events.NewMessage(outgoing=True, pattern=r"^\.(?:حذف|مسح) مطور$"))
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
    if not (len(text) > 1 and text.startswith(".") and text[1].isalnum()):
        return
    if text in {".رفع مطور", ".حذف مطور", ".مسح مطور", ".المطورين"}:
        return

    try:
        sender = await event.get_sender()
        if not sender or is_bot_account(sender):
            return

        # These controls are handled directly because they update shared AI state.
        if text in {".ايقاف ذكي هنا", ".تشغيل ذكي هنا", ".ايقاف ذكي", ".تشغيل ذكي"}:
            chat_id = str(event.chat_id)
            paused = {str(x) for x in settings.get("ai_paused_chats", [])}
            enabled_chats = {str(x) for x in settings.get("ai_enabled_chats", [])}
            if text in {".ايقاف ذكي هنا", ".ايقاف ذكي"}:
                paused.add(chat_id)
                enabled_chats.discard(chat_id)
                answer = "🛑 تم إيقاف الذكاء في هذه المحادثة فقط."
            else:
                paused.discard(chat_id)
                enabled_chats.add(chat_id)
                answer = "✅ تم تشغيل الذكاء في هذه المحادثة فقط، حتى لو كان متوقفاً عن الكل."
            settings["ai_paused_chats"] = sorted(paused)
            settings["ai_enabled_chats"] = sorted(enabled_chats)
            save_json("settings.json", settings)
            await tg.send_message(event.chat_id, answer)
            return

        if text in {".ايقاف الذكاء للكل", ".تشغيل الذكاء للكل"}:
            enabled = text == ".تشغيل الذكاء للكل"
            settings["ai_global_enabled"] = enabled
            settings["ai"] = enabled
            settings["ai_enabled_chats"] = []
            bh.AI_GLOBAL_ENABLED = enabled
            save_json("settings.json", settings)
            answer = "✅ تم تشغيل الذكاء للجميع." if enabled else "🛑 تم إيقاف الذكاء للجميع."
            await tg.send_message(event.chat_id, answer)
            return

        reply_to = None
        if event.is_reply:
            replied = await event.get_reply_message()
            reply_to = replied.id if replied else None

        # Explicitly dispatch because send_message may not emit a local update.
        sent = await tg.send_message(event.chat_id, text, reply_to=reply_to)
        matched = await _dispatch_existing_command(sent)
        if not matched:
            await sent.edit("⚠️ لم أجد معالجاً لهذا الأمر في النسخة الحالية.")
    except Exception as exc:
        print("DEVELOPER COMMAND BRIDGE ERROR:", exc)
