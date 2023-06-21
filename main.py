from pyrogram import Client, errors
from pyrogram.types import Message
from base.module import BaseModule, command
from python_gelbooru import AsyncGelbooru
import asyncio

class AnimeModule(BaseModule):
    def on_init(self):
        self.api_key, self.user_id = "ddef325ed8ede716bc0857999f4a8e5ccf5d3be4662a4c89dc71734b3c609e04", "1269231"
        self.sent_photos = {}
        
    async def clear_sent_photos(self, chat_id):
        await asyncio.sleep(3600)
        if chat_id in self.sent_photos:
            del self.sent_photos[chat_id]
        
    @command("pic")
    async def get_gelImage(self, bot: Client, message: Message):
        args = message.text.split(" ")[1:]
        
        if len(args) == 0 or not args[0].isdigit():
            limit = 1
            tags = args
        else:
            limit = int(args[0])
            tags = args[1:]
        
        await self.process(bot, message, tags, limit)
        asyncio.ensure_future(self.clear_sent_photos(message.chat.id))
        
    async def process(self, bot, message, tags, limit):
        async with AsyncGelbooru(api_key=self.api_key, user_id=self.user_id) as gel:
            try:
                results = await gel.search_posts(tags, limit=int(limit), random=True)
                self.logger.info(tags)
                self.logger.info(limit)
            except KeyError:
                await message.reply_text(self.S["tags_not_found"])
                return
            
        if results:
            for photo in results:
                file_url = str(photo.file_url)
                chat_id = message.chat.id
                if chat_id not in self.sent_photos or file_url not in self.sent_photos[chat_id]:
                    try: 
                        await message.reply_photo(
                            photo=file_url,
                            caption=self.S['credit'].format(file_url=file_url)
                        )
                        
                        self.sent_photos.setdefault(chat_id, []).append(file_url)
                        await asyncio.sleep(1)
                        
                    except errors.WebpageCurlFailed as e:
                        self.logger.warning(e)
                        await message.reply(self.S["curl_error"])
                        continue
                
                    except errors.FloodWait as e:
                        self.logger.warning(e)
                        await asyncio.sleep(31)
                        continue
