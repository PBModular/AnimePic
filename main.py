from pyrogram import Client, errors, filters, enums
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from python_gelbooru import AsyncGelbooru
from base.module import BaseModule, command, allowed_for, callback_query
from .db import Base, ChatState
from sqlalchemy import select
import asyncio

class AnimePicModule(BaseModule):
    def on_init(self):
        self.api_key, self.user_id = "None", "None"  # Optional
        self.sent_photos = {}
        self.ratings = {
            "re": "rating%3aexplicit",
            "rq": "rating%3aquestionable",
            "rs": "rating%3asafe"
        }
        self.task_pended = {}
        self.message_tags = {}

    @property
    def help_page(self):
        return self.S["help"]

    @property
    def db_meta(self):
        return Base.metadata    
    
    async def clear_cache(self, chat_id, message_id):
        self.task_pended[chat_id] = 1
        await asyncio.sleep(3600)
        if chat_id in self.sent_photos:
            del self.sent_photos[chat_id]
        if message_id in self.message_tags:
            del self.message_tags[message_id]
        self.task_pended[chat_id] = 0

    async def get_chat_rating(self, chat_id):
        async with self.db.session_maker() as session:
            chat_state = await session.scalar(select(ChatState).where(ChatState.chat_id == chat_id))
            if chat_state is not None:
                return chat_state.rating
        return "rating%3asafe"

    async def set_chat_rating(self, chat_id, rating):
        async with self.db.session_maker() as session:
            chat_state = await session.scalar(select(ChatState).where(ChatState.chat_id == chat_id))
            if chat_state is None:
                chat_state = ChatState(chat_id=chat_id)
            if rating in self.ratings:
                chat_state.rating = self.ratings[rating]
            elif rating == "r":
                chat_state.rating = "random"
            else:
                await session.rollback()
                return False
            session.add(chat_state)
            await session.commit()
            return True 

    async def get_chat_limit(self, chat_id):
        async with self.db.session_maker() as session:
            chat_state = await session.scalar(select(ChatState).where(ChatState.chat_id == chat_id))
            if chat_state is not None and chat_state.limit is not None:
                return chat_state.limit
        return 1

    async def set_chat_limit(self, chat_id, limit):
        async with self.db.session_maker() as session:
            chat_state = await session.scalar(select(ChatState).where(ChatState.chat_id == chat_id))
            if chat_state is None:
                chat_state = ChatState(chat_id=chat_id)
            chat_state.limit = limit
            session.add(chat_state)
            await session.commit()

    @command("pic")
    async def pic_cmd(self, bot: Client, message: Message):
        args = message.text.split()[1:]
        limit = await self.get_chat_limit(message.chat.id)
        tags = []

        if args:
            if args[0].isdigit():
                requested_limit = int(args[0])
                if limit > 0 and requested_limit > limit:
                    await message.reply(self.S["pic"]["limit_exceeded"].format(limit=limit))
                    return
                limit = requested_limit
                tags = args[1:]
            else:
                limit = 1
                tags = args

        if not tags:
            await message.reply(self.S["pic"]["arg_not_found"])
            return

        chat_id = message.chat.id
        rating = await self.get_chat_rating(chat_id)
        if rating != "random":
            tags.insert(0, rating)

        self.message_tags[message.id] = tags

        await self.process(bot, message, tags, limit)

        if self.task_pended.get(message.chat.id, 0) == 0:
            asyncio.create_task(self.clear_cache(message.chat.id, message.id))

    @allowed_for(["chat_admins", "chat_owner"])
    @command("setrating")
    async def set_rating_cmd(self, bot: Client, message: Message):
        args = message.text.split()[1:]

        if not args:
            await message.reply(self.S["rating"]["arg_invalid"])
            return

        rating = args[0]
        success = await self.set_chat_rating(message.chat.id, rating)
        if success:
            await message.reply(self.S["rating"]["success"].format(rating=rating))
        else:
            await message.reply(self.S["rating"]["failure"].format(rating=rating))

    @command("getrating")
    async def get_rating_cmd(self, bot: Client, message: Message):
        rating = await self.get_chat_rating(message.chat.id)
        if not "random" in rating:
            rating = rating.replace("rating%3a", "")

        await message.reply(self.S["rating"]["current"].format(rating=rating))

    @allowed_for(["chat_admins", "chat_owner"])
    @command("limit")
    async def limit_cmd(self, bot: Client, message: Message):
        args = message.text.split()[1:]

        if not args:
            limit = await self.get_chat_limit(message.chat.id)
            await message.reply(self.S["limit"]["current_limit"].format(limit=limit))
            return
        
        if not args[0].isdigit():
            await message.reply(self.S["limit"]["arg_invalid"])
            return

        limit = int(args[0])
        await self.set_chat_limit(message.chat.id, limit)
        if limit == 0:
            await message.reply(self.S["limit"]["success_no_limit"])
        elif limit > 100:
            await message.reply(self.S["limit"]["api_exceeded"])
            await self.set_chat_limit(message.chat.id, limit=100)
        else:
            await message.reply(self.S["limit"]["success"].format(limit=limit))

    @command("tagsearch")
    async def tagsearch_cmd(self, bot: Client, message: Message):
        args = message.text.split()[1:]
        if not args:
            await message.reply(self.S["tagsearch"]["arg_invalid"])
            return

        query = args[0]
        page = 1
        tags, total_pages = await self.search_tags(query, page)
        
        if not tags:
            await message.reply(self.S["tagsearch"]["tags_not_found"])
            return
        
        await self.send_tag_list(message, tags, query, page, total_pages)

    async def search_tags(self, query, page):
        async with AsyncGelbooru(api_key=self.api_key, user_id=self.user_id) as gel:
            try:
                all_tags = await gel.search_tags(name_pattern=f"%{query}%", limit=1000)
            except Exception as e:
                self.logger.error(e)
                return [], 1

        tags_per_page = 15
        total_pages = (len(all_tags) + tags_per_page - 1) // tags_per_page
        start = (page - 1) * tags_per_page
        end = start + tags_per_page

        tags = [tag.name for tag in all_tags[start:end]]

        return tags, total_pages

    async def send_tag_list(self, message, tags, query, page, total_pages):
        tag_list = "\n".join(f"• `{tag}`" for tag in tags)

        buttons = []

        if page > 1:
            buttons.append(InlineKeyboardButton(self.S["tagsearch"]["prev"], callback_data=f"tagsearch_prev_{query}_{page - 1}"))
        
        buttons.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="dummy"))
        
        if page < total_pages:
            buttons.append(InlineKeyboardButton(self.S["tagsearch"]["next"], callback_data=f"tagsearch_next_{query}_{page + 1}"))

        keyboard = InlineKeyboardMarkup([buttons])

        if message.from_user.is_bot:
            await message.edit_text(tag_list, reply_markup=keyboard, parse_mode=enums.ParseMode.MARKDOWN)
        else:
            await message.reply(tag_list, reply_markup=keyboard, parse_mode=enums.ParseMode.MARKDOWN)

    @callback_query(filters.regex(r"tagsearch_(prev|next)_(.+?)_(\d+)"))
    async def handle_pagination(self, bot: Client, callback_query):
        action, query, page = callback_query.data.split("_")[1:]
        page = int(page)

        tags, total_pages = await self.search_tags(query, page)
        
        await self.send_tag_list(callback_query.message, tags, query, page, total_pages)
        await callback_query.answer()

    @callback_query(filters.regex(r"dummy"))
    async def dummy_callback(self, bot: Client, callback_query):
        await callback_query.answer()
        
    async def process(self, bot, message, tags, limit):
        async with AsyncGelbooru(api_key=self.api_key, user_id=self.user_id) as gel:
            try:
                results = await gel.search_posts(tags, limit=int(limit), random=True)
                # self.logger.info(results)
            except KeyError:
                await message.reply(self.S["process"]["tags_not_found"])
                return

        chat_id = message.chat.id
        new_photos = []

        for photo in results:
            file_url = str(photo.file_url)
            if chat_id not in self.sent_photos or file_url not in self.sent_photos[chat_id]:
                new_photos.append(photo)

        if not new_photos:
            await message.reply(self.S["process"]["no_results"])
            return

        for photo in new_photos:
            file_url = str(photo.file_url)
            try:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(self.S["process"]["button"].format(file_url=file_url), url=file_url)]
                ])
                
                if limit == 1:
                    keyboard.inline_keyboard.append([InlineKeyboardButton(self.S["process"]["next_image"], callback_data="refresh_status")])

                await message.reply_photo(
                    photo=file_url,
                    caption=self.S["process"]['credit'],
                    reply_markup=keyboard
                )

                self.sent_photos.setdefault(chat_id, []).append(file_url)
                await asyncio.sleep(1)

            except errors.WebpageCurlFailed or errors.WebpageMediaEmpty:
                await message.reply(self.S["process"]["curl_error"])
            except errors.FloodWait:
                await asyncio.sleep(31)
            except Exception as e:
                await message.reply(self.S["process"]["error"])
                self.logger.error(e)
            continue

    @callback_query(filters.regex("refresh_status"))
    async def handle_callback_query(self, bot: Client, callback_query):
        chat_id = callback_query.message.chat.id
        message_id = callback_query.message.reply_to_message.id
        await self.update_image(bot, callback_query, chat_id, message_id)

    async def update_image(self, bot: Client, callback_query, chat_id, message_id):
        tags = self.message_tags.get(message_id, [])
        if not tags:
            return

        attempt = 0
        new_photo = False
        photo = None

        while attempt < 5 and not new_photo:
            async with AsyncGelbooru(api_key=self.api_key, user_id=self.user_id) as gel:
                try:
                    results = await gel.search_posts(tags, limit=1, random=True)
                except KeyError:
                    await callback_query.answer(self.S["process"]["tags_not_found"], show_alert=True)
                    return

            photo = results[0]
            file_url = str(photo.file_url)
            if chat_id not in self.sent_photos or file_url not in self.sent_photos[chat_id]:
                new_photo = True
            else:
                attempt += 1

        if not new_photo:
            await callback_query.answer(self.S["process"]["no_results"])
            return

        try:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(self.S["process"]["button"].format(file_url=file_url), url=file_url)],
                [InlineKeyboardButton(self.S["process"]["next_image"], callback_data="refresh_status")]
            ])
            await callback_query.message.edit_media(
                media=InputMediaPhoto(file_url),
                reply_markup=keyboard
            )

            self.sent_photos.setdefault(chat_id, []).append(file_url)
            await callback_query.answer()

        except errors.WebpageCurlFailed or errors.WebpageMediaEmpty:
            await callback_query.answer(self.S["process"]["curl_error"], show_alert=True)
        except errors.FloodWait:
            await asyncio.sleep(31)
        except Exception as e:
            await callback_query.answer(self.S["process"]["error"], show_alert=True)
            self.logger.error(e)
