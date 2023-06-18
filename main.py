from pyrogram import Client
from pyrogram.types import Message
from base.module import BaseModule, command
from python_gelbooru import AsyncGelbooru

class AnimeModule(BaseModule):
    def on_init(self):
        self.api_key, self.user_id = "api_id", "user_id"
        
    @command("pic")
    async def get_gelImage(self, bot: Client, message: Message):
        args = message.text.split(" ")[1:]
        
        if len(args) == 0 or not args[0].isdigit():
            limit = 1
            tags = args
        else:
            limit = int(args[0])
            tags = args[1:]
        
        async with AsyncGelbooru(api_key=self.api_key, user_id=self.user_id) as gel:
            try:
                results = await gel.search_posts(tags, limit=int(limit), random=True)
                self.logger.info(tags)
                self.logger.info(limit)
            except KeyError:
                await message.reply_text(self.S["tags_not_found"])
                return
            
            if results:
                for i in results:
                    await message.reply_photo(
                        photo=str(i.file_url),
                        caption=self.S["credit"]
                    )
