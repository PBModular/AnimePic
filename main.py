from pyrogram import Client, errors
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from base.module import BaseModule, command, allowed_for
from .db import Base, ChatState
from sqlalchemy import select
from cunnypy.errors import CunnyPyError
import asyncio
import cunnypy

class AnimePicModule(BaseModule):
    def on_init(self):
        self.sent_photos = {}
        self.ratings = {
            "re": "explicit",
            "rq": "questionable",
            "rs": "safe"
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
        return "safe"
        
    async def set_chat_rating(self, chat_id, rating):
        async with self.db.session_maker() as session:
            chat_state = await session.scalar(select(ChatState).where(ChatState.chat_id == chat_id))
            if chat_state is None:
                chat_state = ChatState(chat_id=chat_id)
            if rating in self.ratings:
                chat_state.rating = self.ratings[rating]
            elif rating == "r":
                chat_state.rating = None
            else:
                await session.rollback()
                return False  # Invalid rating
            session.add(chat_state)
            await session.commit()
            return True 

    async def get_chat_limit(self, chat_id):
        async with self.db.session_maker() as session:
            chat_state = await session.scalar(select(ChatState).where(ChatState.chat_id == chat_id))
            if chat_state is not None:
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

        await self.process(bot, message, tags, limit, rating)
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

    @command("getrating")
    async def get_rating_cmd(self, bot: Client, message: Message):
        rating = await self.get_chat_rating(message.chat.id)
        if rating is None:
            rating = "random"

        await message.reply(self.S["rating"]["current"].format(rating=rating))

    @allowed_for("chat_admins")
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

    async def process(self, bot, message, tags, limit, rating):
        try:
            results = await cunnypy.search("gelbooru", " ".join(tags), limit=limit, rating=rating, gatcha=True)

        except CunnyPyError:
            await message.reply(self.S["process"]["error"])
            return
        
        if not results:
            await message.reply(self.S["process"]["no_results"])
            return
        
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
