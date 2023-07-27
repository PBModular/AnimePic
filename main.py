from pyrogram import Client, errors
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from python_gelbooru import AsyncGelbooru
from base.module import BaseModule, command, allowed_for
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
        
    @property
    def help_page(self):
        return self.S["help"]
 
    @property
    def db_meta(self):
        return Base.metadata    
    
    async def clear_sent_photos(self, chat_id):
        await asyncio.sleep(3600)
        if chat_id in self.sent_photos:
            del self.sent_photos[chat_id]
            
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
                return False  # Invalid rating
            session.add(chat_state)
            await session.commit()
            return True 
            
    @command("pic")
    async def pic_cmd(self, bot: Client, message: Message):
        args = message.text.split()[1:]
        limit = 1
        tags = []

        if args:
            if args[0].isdigit():
                limit = int(args[0])
                tags = args[1:]
            else:
                tags = args

        if not tags:
            await message.reply(self.S["pic"]["arg_not_found"])
            return

        chat_id = message.chat.id
        rating = await self.get_chat_rating(chat_id)
        if rating != "random":
            tags.insert(0, rating)

        await self.process(bot, message, tags, limit)
        asyncio.create_task(self.clear_sent_photos(message.chat.id))


    @allowed_for("chat_admins")
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

    async def process(self, bot, message, tags, limit):
        async with AsyncGelbooru(api_key=self.api_key, user_id=self.user_id) as gel:
            try:
                results = await gel.search_posts(tags, limit=int(limit), random=True)
            except KeyError:
                await message.reply(self.S["process"]["tags_not_found"])
                return
            
        if results:
            for photo in results:
                file_url = str(photo.file_url)
                chat_id = message.chat.id
                if chat_id not in self.sent_photos or file_url not in self.sent_photos[chat_id]:
                    try:
                        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(self.S["process"]["button"].format(file_url=file_url), url=file_url)]])
                        await message.reply_photo(
                            photo=file_url,
                            caption=self.S["process"]['credit'],
                            reply_markup=keyboard
                        )
                        
                        self.sent_photos.setdefault(chat_id, []).append(file_url)
                        await asyncio.sleep(1)
                        
                    except (errors.WebpageCurlFailed, errors.FloodWait, Exception) as e:
                        self.logger.error(e)
                        if isinstance(e, errors.WebpageCurlFailed):
                            await message.reply(self.S["process"]["curl_error"])
                        elif isinstance(e, errors.FloodWait):
                            await asyncio.sleep(31)
                        else:
                            await message.reply(self.S["process"]["error"])
                        continue
