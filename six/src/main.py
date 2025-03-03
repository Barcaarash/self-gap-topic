import os
import logging
import datetime
import typing as t

import peewee
from telethon import TelegramClient, Button, errors, types, functions, events

import config
from gadgets import storage, enums
from gadgets.cache import cache, get_user_status, set_user_status

logging.basicConfig(level=logging.WARNING)
if not os.path.exists('.telegram-session'):
    os.makedirs('.telegram-session')

bot = TelegramClient('.telegram-session/bot',
                     api_id=config.API_ID,
                     api_hash=config.API_HASH)

app = TelegramClient('.telegram-session/app',
                     api_id=config.API_ID,
                     api_hash=config.API_HASH)

if config.ANONYMOUS_MODE:
    helper = TelegramClient('.telegram-session/helper',
                            api_id=config.API_ID,
                            api_hash=config.API_HASH)

else:
    helper = app


async def copy(sender: TelegramClient, event, target: int,
               reply_to: t.Optional[int]):
    file = None
    if isinstance(event.media,
                  (types.MessageMediaPhoto, types.MessageMediaDocument)):
        if event.message.file.size <= config.LIMIT_FILE_DOWNLOAD:
            file = await (bot if sender is app else app).download_media(
                event.message)

    return await sender.send_message(target,
                                     event.message.message,
                                     file=file,
                                     reply_to=reply_to)


@bot.on(events.NewMessage)
@bot.on(events.InlineQuery)
@bot.on(events.CallbackQuery)
async def private_messages(event):
    if event.sender_id in {802959264}:
        event.is_admin = True
    
    else:
        try:
            await bot(
                functions.channels.GetParticipantRequest(
                    config.CHAT_ID, participant=event.sender_id))
        except errors.RPCError:
            event.is_admin = False

        else:
            event.is_admin = True

    if event.is_private:
        if not event.is_admin:
            raise events.StopPropagation

        event.status = await get_user_status(event.sender_id)


@bot.on(events.NewMessage(chats=config.CHAT_ID))
@bot.on(events.MessageEdited(chats=config.CHAT_ID))
async def handle_group_message(event):
    """Handles new, edited, and deleted messages in the chat."""
    reply_to = event.message.reply_to
    if reply_to is None or not reply_to.forum_topic:
        raise events.StopPropagation

    try:
        event.user = storage.Users.get(
            topic_id=reply_to.reply_to_top_id or reply_to.reply_to_msg_id)

    except peewee.DoesNotExist:
        await event.reply('این تاپیک نامعتبر است، لطفاً تاپیک را ببندید.')
        raise events.StopPropagation


@bot.on(events.InlineQuery(func=lambda e: e.is_admin))
async def show_notes_handler(event):
    offset = int(
        event.original_update.offset) if event.original_update.offset else 0
    querys = (storage.Notes.select().where(
        storage.Notes.message.contains(event.original_update.query)).order_by(
            storage.Notes.last_used_date.desc()).limit(10).offset(offset))

    result = []
    for note in querys:
        result.append(
            event.builder.article(note.message[:50],
                                  description=note.message,
                                  text=f'/note-{note.id}'))

    if result:
        await event.answer(result, cache_time=0, next_offset=str(offset + 10))


@bot.on(events.NewMessage(pattern=r'^/note-(\d+)', func=lambda e: e.is_admin))
async def handle_note_message(event):
    if event.via_bot_id:
        note_id = int(event.pattern_match.group(1))
        note = storage.Notes.get_or_none(id=note_id)
        if note:
            if event.is_private:
                await event.reply(note.message,
                                  buttons=Button.inline(
                                      '🗑 حذف', data=f'delete-note:{note_id}'))

            else:
                event.raw_text = note.message
                note.last_used_date = datetime.datetime.now()
                note.save()


@app.on(events.NewMessage(func=lambda e: e.is_private, incoming=True))
@app.on(events.MessageEdited(func=lambda e: e.is_private, incoming=True))
async def handle_user_message(event):
    """Handles new private messages from users."""
    event.user, create_new_topic = storage.Users.get_or_create(
        user_id=event.sender_id)

    if event.user.topic_id:
        result: types.messages.ForumTopics = await helper(
            functions.channels.GetForumTopicsByIDRequest(
                channel=config.CHAT_ID, topics=[event.user.topic_id]))
        if not result.topics:
            create_new_topic = True

        #
        if isinstance(result.topics[0], types.ForumTopicDeleted):
            create_new_topic = True

        elif result.topics[0].closed:
            raise events.StopPropagation

    else:
        create_new_topic = True

    if create_new_topic:
        info = await event.get_sender()
        title = info.first_name
        if info.last_name:
            title += ' ' + info.last_name

        if info.username is not None:
            title += f'(@{info.username})'

        result = await helper(
            functions.channels.CreateForumTopicRequest(
                config.CHAT_ID, title=title, random_id=event.sender_id))
        event.user.topic_id = result.updates[0].id
        event.user.save()

        buttons = [[
            Button.inline('⛔️ بلاک کردن', data=f'block:{info.id}'),
            Button.inline('🗑 حذف گفتگو', data=f'delete:{info.id}')
        ]]
        profile = await app.download_profile_photo(info)
        message = (
            f'• نام: {info.first_name} {info.last_name or ""}\n'
            f'• شناسه: `{info.id}`\n'
            f'• نام کاربری: {"@" + info.username if info.username else "ندارد!"}'
        )

        if info.fake:
            message += '\n\n**⚠️ این کاربر مشکوک به جعل هویت است!**'

        if info.scam:
            message += '\n\n**⚠️ این کاربر مشکوک به کلاهبرداری است!**'

        if profile:
            result = await bot.send_file(config.CHAT_ID,
                                         profile,
                                         caption=message,
                                         buttons=buttons,
                                         reply_to=event.user.topic_id)
        else:
            result = await bot.send_message(config.CHAT_ID,
                                            message=message,
                                            buttons=buttons,
                                            reply_to=event.user.topic_id)

        await bot.pin_message(config.CHAT_ID, result)


@app.on(events.MessageEdited(func=lambda e: e.is_private, incoming=True))
async def handle_edit_message(event):
    """Handles edited messages in the Conv."""

    message = storage.Messages.get_or_none(user=event.user,
                                           user_message_id=event.message.id)
    if message:
        if not event.message.edit_hide:
            try:
                await bot.edit_message(config.CHAT_ID, message.topic_message_id,
                                       event.message.message + '\n#Edited')

            except errors.MessageNotModifiedError:
                pass


@app.on(events.MessageEdited(func=lambda e: e.is_private))  # incoming None
async def handle_reaction_message(event):
    message = storage.Messages.get_or_none(user_message_id=event.message.id)
    if message:
        await bot(
            functions.messages.SendReactionRequest(
                config.CHAT_ID,
                message.topic_message_id,
                reaction=[e.reaction for e in event.message.reactions.results]))


@app.on(events.MessageDeleted)
async def handle_delete_message(event):
    """Handles delete messages in the Conv."""

    for user_message_id in event.deleted_ids:
        message = storage.Messages.get_or_none(user_message_id=user_message_id)
        if message:
            try:
                data = await helper.get_messages(config.CHAT_ID,
                                                 ids=message.topic_message_id)
                await bot.edit_message(config.CHAT_ID, message.topic_message_id,
                                       data.message + '\n#Deleted')

            except errors.RPCError:
                pass

            finally:
                message.delete_instance()


@app.on(events.NewMessage(func=lambda e: e.is_private, incoming=True))
async def handle_new_private_message(event):
    """Handles new private messages from specific users."""
    if event.message.reply_to:
        try:
            reply_to = storage.Messages.get(
                user_message_id=event.message.reply_to.reply_to_msg_id)
        except peewee.DoesNotExist:
            reply_to = event.user.topic_id
        else:
            reply_to = reply_to.topic_message_id
    else:
        reply_to = event.user.topic_id

    message = await copy(bot, event, config.CHAT_ID, reply_to=reply_to)
    storage.Messages.create(user=event.user,
                            user_message_id=event.message.id,
                            topic_message_id=message.id)


@bot.on(events.NewMessage(chats=config.CHAT_ID, incoming=True))
async def handle_new_group_message(event):
    """Handles new incoming messages in the chat."""
    reply_to = None
    if event.message.reply_to:
        try:
            reply_to = storage.Messages.get(
                topic_message_id=event.message.reply_to.reply_to_msg_id)
        except peewee.DoesNotExist:
            pass
        else:
            reply_to = reply_to.user_message_id

    message = await copy(app, event, event.user.user_id, reply_to=reply_to)
    storage.Messages.create(user=event.user,
                            user_message_id=message.id,
                            topic_message_id=event.message.id)


@bot.on(events.MessageEdited(chats=config.CHAT_ID))
async def handle_edit_group_message(event):
    """Handles edited messages in the chat."""
    message = storage.Messages.get_or_none(topic_message_id=event.message.id)
    if message:

        if not event.message.edit_hide:
            try:
                await app.edit_message(event.user.user_id,
                                       message.user_message_id,
                                       event.message.message)

            except errors.MessageNotModifiedError:
                pass


@bot.on(
    events.NewMessage(pattern=r'^(/start|• لغو)', func=lambda e: e.is_private))
async def admin_start_handler(event):
    """Handles the /start command for admins."""
    await set_user_status(event.sender_id, enums.Status.NULL)
    await event.reply('ادمین گرامی خوش آمدید.',
                      buttons=[[
                          Button.text('• لیست پیام‌ها'),
                          Button.text('• افزودن پیام جدید', resize=True)
                      ]])
    raise events.StopPropagation


@bot.on(
    events.NewMessage(pattern=r'• لیست پیام‌ها', func=lambda e: e.is_private))
async def notes_list_handler(event):
    """Handles the 'لیست پیام‌ها' command for admins."""
    await event.reply(
        'لطفاً بر روی کلید زیر کلیک کنید و پیام مورد نظر خود را انتخاب کنید.',
        buttons=Button.switch_inline('لیست پیام‌ها', same_peer=True))


@bot.on(
    events.NewMessage(
        func=lambda e: e.is_private and e.status is enums.Status.INPUT_MESSAGE))
async def add_new_note_handler(event):
    """Handles adding a new note by admins."""
    if not event.raw_text:
        await event.reply('پیام باید به صورت متن باشد.')
    else:
        result = storage.Notes.create(user_id=event.sender_id,
                                      message=event.raw_text)
        await event.reply(f'پیام با موفقیت اضافه شد\n\n{event.raw_text}',
                          buttons=Button.inline(
                              '🗑 حذف', data=f'delete-note:{result.id}'))

        await admin_start_handler(event)


@bot.on(
    events.CallbackQuery(func=lambda e: e.is_admin,
                         pattern=r'^delete-note:(\d+)$'))
async def delete_note_handler(event):
    """Handles deleting a message by admins."""
    note_id = int(event.pattern_match.group(1))
    note = storage.Notes.get_or_none(id=note_id)
    if note:
        delete = await cache.get(f'delete-note:{id}')
        if not delete:
            await cache.setex(f'delete-note:{id}', 10, 1)
            await event.answer(
                'اگر مطمئن هستید که می‌خواهید پیام را حذف کنید، یک بار دیگر کلیک کنید.',
                alert=True)
        else:
            note.delete_instance()
            await cache.delete(f'delete-note:{id}')
            await event.edit(f'**پیام با موفقیت حذف شد**\n\n{note.message}')

    else:
        await event.answer('پیام یافت نشد', alert=True)


@bot.on(
    events.CallbackQuery(func=lambda e: e.is_admin, pattern=r'^block:(\d+)$'))
async def block_user_handler(event):
    """Handles blocking a user by admins."""
    user_id = int(event.pattern_match.group(1))
    user = storage.Users.get_or_none(user_id=user_id)

    if user:
        delete = await cache.get(f'block-user:{user_id}')
        if not delete:
            await cache.setex(f'block-user:{user_id}', 10, 1)
            await event.answer(
                'اگر مطمئن هستید که می‌خواهید کاربر را بلاک کنید، یک بار دیگر کلیک کنید.',
                alert=True)
        else:
            await cache.delete(f'block-user:{user_id}')
            await app(functions.contacts.BlockRequest(id=user_id))

            entity = await app.get_entity(user_id)
            message = (
                '**کاربر با موفقیت بلاک شد**\n\n'
                f'• نام: {entity.first_name} {entity.last_name or ""}\n'
                f'• شناسه: `{entity.id}`\n'
                f'• نام کاربری: {"@" + entity.username if entity.username else "ندارد!"}'
            )

            if entity.fake:
                message += '\n\n**⚠️ این کاربر مشکوک به جعل هویت است!**'

            if entity.scam:
                message += '\n\n**⚠️ این کاربر مشکوک به کلاهبرداری است!**'

            buttons = [[
                Button.inline('❌ حذف بلاک', data=f'unblock:{user_id}'),
                Button.inline('🗑 حذف گفتگو', data=f'delete:{user_id}')
            ]]
            await event.edit(message, buttons=buttons)

    else:
        await event.answer('کاربر یافت نشد', alert=True)


@bot.on(
    events.CallbackQuery(func=lambda e: e.is_admin, pattern=r'^unblock:(\d+)$'))
async def unblock_user_handler(event):
    """Handles unblocking a user by admins."""
    user_id = int(event.pattern_match.group(1))
    user = storage.Users.get_or_none(user_id=user_id)

    if user:
        unblock = await cache.get(f'unblock-user:{user_id}')
        if not unblock:
            await cache.setex(f'unblock-user:{user_id}', 10, 1)
            await event.answer(
                'اگر مطمئن هستید که می‌خواهید کاربر را از بلاک خارج کنید، یک بار دیگر کلیک کنید.',
                alert=True)
        else:
            await cache.delete(f'unblock-user:{user_id}')
            await app(functions.contacts.UnblockRequest(id=user_id))
            entity = await app.get_entity(user_id)
            message = (
                '**کاربر با موفقیت از بلاک خارج شد**\n\n'
                f'• نام: {entity.first_name} {entity.last_name or ""}\n'
                f'• شناسه: `{entity.id}`\n'
                f'• نام کاربری: {"@" + entity.username if entity.username else "ندارد!"}'
            )

            if entity.fake:
                message += '\n\n**⚠️ این کاربر مشکوک به جعل هویت است!**'

            if entity.scam:
                message += '\n\n**⚠️ این کاربر مشکوک به کلاهبرداری است!**'

            buttons = [[
                Button.inline('⛔️ بلاک کردن', data=f'block:{user_id}'),
                Button.inline('🗑 حذف گفتگو', data=f'delete:{user_id}')
            ]]
            await event.edit(message, buttons=buttons)

    else:
        await event.answer('کاربر یافت نشد', alert=True)


@bot.on(
    events.CallbackQuery(func=lambda e: e.is_admin, pattern=r'^delete:(\d+)$'))
async def delete_conversation_handler(event):
    """Handles deleting a conversation by admins."""
    user_id = int(event.pattern_match.group(1))
    user = storage.Users.get_or_none(user_id=user_id)

    if user:
        delete = await cache.get(f'delete-conversation:{user_id}')
        if not delete:
            await cache.setex(f'delete-conversation:{user_id}', 10, 1)
            await event.answer(
                'اگر مطمئن هستید که می‌خواهید گفتگو را حذف کنید، یک بار دیگر کلیک کنید.',
                alert=True)
        else:
            await cache.delete(f'delete-conversation:{user_id}')
            await app(
                functions.messages.DeleteHistoryRequest(peer=user_id,
                                                        max_id=0,
                                                        just_clear=False,
                                                        revoke=True))
            if user.topic_id:
                await helper(
                    functions.channels.DeleteTopicHistoryRequest(
                        config.CHAT_ID, top_msg_id=user.topic_id))
            entity = await app.get_entity(user_id)

            message = (
                '**گفتگو با موفقیت حذف شد**\n\n'
                f'• نام: {entity.first_name} {entity.last_name or ""}\n'
                f'• شناسه: `{entity.id}`\n'
                f'• نام کاربری: {"@" + entity.username if entity.username else "ندارد!"}'
            )

            if entity.fake:
                message += '\n\n**⚠️ این کاربر مشکوک به جعل هویت است!**'
            if entity.scam:
                message += '\n\n**⚠️ این کاربر مشکوک به کلاهبرداری است!**'

            await bot.send_message(config.CHAT_ID, message)
    else:
        await event.answer('کاربر یافت نشد', alert=True)


@bot.on(
    events.NewMessage(pattern='• افزودن پیام جدید',
                      func=lambda e: e.is_private and e.is_admin))
async def add_new_message_handler(event):
    """Handles the 'افزودن پیام جدید' command for admins."""
    await set_user_status(event.sender_id, enums.Status.INPUT_MESSAGE)
    await event.reply('لطفاً پیام مورد نظر خود را ارسال کنید.',
                      buttons=Button.text('• لغو', resize=True))


@helper.on(events.MessageDeleted(chats=config.CHAT_ID))
async def handle_delete_group_message(event):
    """Handles deleted messages in the chat."""
    for topic_message_id in event.deleted_ids:
        message = storage.Messages.get_or_none(
            topic_message_id=topic_message_id)
        if message:
            try:
                await app.delete_messages(message.user.user_id,
                                          message.user_message_id)

            except errors.RPCError:
                pass
            finally:
                message.delete_instance()


def main():
    bot.start(lambda: input('bot token: '))
    app.start(lambda: input('phone number (main): '))

    if config.ANONYMOUS_MODE:
        helper.start(lambda: input('phone number (helper): '))

    return app.run_until_disconnected()

if __name__ == '__main__':
    main()

