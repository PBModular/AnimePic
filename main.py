from pyrogram import Client, errors, filters, enums
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
import aiohttp
import random
from base.module import BaseModule, command, allowed_for, callback_query
from .db import Base, ChatState
from sqlalchemy import select
from typing import List, Dict, Tuple, Set, Optional, Any
import asyncio
import os


class AnimePicModule(BaseModule):
    GELBOORU_API_URL = "https://gelbooru.com/index.php"

    def on_init(self):
        self.api_key, self.user_id = "None", "None"
        self.sent_photos: Dict[int, Set[str]] = {}
        self.ratings = {
            "re": "rating%3aexplicit",
            "rq": "rating%3aquestionable",
            "rs": "rating%3asafe"
        }
        self.task_pended: Dict[int, int] = {}
        self.message_tags: Dict[int, List[str]] = {}
        self.processing_locks: Dict[int, asyncio.Lock] = {}
        self.cache_cleanup_tasks: Dict[int, asyncio.Task] = {}
        
        self.fallback_image = os.path.join(self.module_path, "pavel-durov.png")
        
        if not os.path.exists(self.fallback_image):
            self.logger.warning(f"Fallback image not found at {self.fallback_image}")

        self.http_session = aiohttp.ClientSession()

    def on_stop(self):
        if self.http_session and not self.http_session.closed:
            asyncio.create_task(self.http_session.close())

    async def _make_api_request(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        params.update({
            "page": "dapi",
            "q": "index",
            "json": 1,
            "api_key": self.api_key,
            "user_id": self.user_id,
        })

        try:
            async with self.http_session.get(self.GELBOORU_API_URL, params=params) as response:
                if response.status != 200:
                    self.logger.error(f"Gelbooru API request failed with status {response.status}: {params}")
                    return None

                text_response = await response.text()
                if not text_response:
                    return {}
                return await response.json(content_type=None)
        except aiohttp.ClientError as e:
            self.logger.error(f"AIOHTTP client error during Gelbooru API request: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error decoding Gelbooru API response: {e}")
            return None

    async def gelbooru_search_tags(self, name_pattern: str, limit: int = 1000) -> List[Dict[str, Any]]:
        params = {
            "s": "tag",
            "name_pattern": name_pattern,
            "limit": limit,
            "orderby": "count",
        }
        data = await self._make_api_request(params)

        if not data or "tag" not in data:
            return []

        tags = data["tag"]
        if isinstance(tags, dict):
            return [tags]
        return tags

    async def gelbooru_search_posts(self, tags: List[str], limit: int, random_posts: bool) -> List[Dict[str, Any]]:
        """Searches for posts on Gelbooru."""
        tag_str = " ".join(tags)

        if random_posts:
            count_params = {"s": "post", "tags": tag_str, "limit": 0}
            count_data = await self._make_api_request(count_params)

            if not count_data or "@attributes" not in count_data or "count" not in count_data["@attributes"]:
                self.logger.warning(f"Could not retrieve post count for tags: {tag_str}")
                return []

            count = int(count_data["@attributes"]["count"])
            if count == 0:
                return []

            max_pid = (count - 1) // limit if limit > 0 else 0
            random_pid = random.randint(0, max_pid)

            fetch_params = {"s": "post", "tags": tag_str, "limit": limit, "pid": random_pid}
        else:
            fetch_params = {"s": "post", "tags": tag_str, "limit": limit, "pid": 0}

        data = await self._make_api_request(fetch_params)

        if not data or "post" not in data:
            return []

        posts = data["post"]
        if isinstance(posts, dict):
            return [posts]
        return posts

    @property
    def help_page(self):
        return self.S["help"]

    @property
    def db_meta(self):
        return Base.metadata    
    
    async def clear_cache(self, chat_id: int, message_id: int) -> None:
        self.task_pended[chat_id] = 1
        try:
            await asyncio.sleep(3600)
            
            self.sent_photos.pop(chat_id, None)
            self.message_tags.pop(message_id, None)
            
            if chat_id in self.processing_locks and not self.processing_locks[chat_id].locked():
                self.processing_locks.pop(chat_id, None)
                
        except asyncio.CancelledError:
            self.logger.debug(f"Cache cleanup for chat {chat_id} was cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Error in clear_cache for chat {chat_id}: {e}")
        finally:
            self.task_pended[chat_id] = 0

    async def get_chat_rating(self, chat_id: int) -> str:
        async with self.db.session_maker() as session:
            chat_state = await session.scalar(select(ChatState).where(ChatState.chat_id == chat_id))
            if chat_state is not None and chat_state.rating is not None:
                return chat_state.rating
        return "rating%3asafe"

    async def set_chat_rating(self, chat_id: int, rating: str) -> bool:
        if not isinstance(rating, str):
            return False
            
        async with self.db.session_maker() as session:
            try:
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
            except Exception as e:
                self.logger.error(f"Error setting chat rating: {e}")
                await session.rollback()
                return False

    async def get_chat_limit(self, chat_id: int) -> int:
        async with self.db.session_maker() as session:
            chat_state = await session.scalar(select(ChatState).where(ChatState.chat_id == chat_id))
            if chat_state is not None and chat_state.limit is not None:
                return chat_state.limit
        return 1

    async def set_chat_limit(self, chat_id: int, limit: int) -> None:
        if not isinstance(limit, int) or limit < 0:
            limit = 1
            
        limit = min(limit, 100)
            
        async with self.db.session_maker() as session:
            try:
                chat_state = await session.scalar(select(ChatState).where(ChatState.chat_id == chat_id))
                
                if chat_state is None:
                    chat_state = ChatState(chat_id=chat_id)
                    
                chat_state.limit = limit
                session.add(chat_state)
                await session.commit()
            except Exception as e:
                self.logger.error(f"Error setting chat limit: {e}")
                await session.rollback()

    @command("pic")
    async def pic_cmd(self, bot: Client, message: Message) -> None:
        args = message.text.split()[1:]
        
        if not args:
            await message.reply(self.S["pic"]["arg_not_found"])
            return
            
        chat_id = message.chat.id
        requested_limit = 1
        
        if args and args[0].isdigit():
            requested_limit = int(args[0])
            tags = args[1:]
        else:
            tags = args
            
        max_limit = await self.get_chat_limit(chat_id)
        
        if max_limit > 0 and requested_limit > max_limit:
            await message.reply(self.S["pic"]["limit_exceeded"].format(limit=max_limit))
            return
            
        limit = requested_limit
        rating = await self.get_chat_rating(chat_id)
        if rating != "random":
            tags.insert(0, rating)
            
        self.message_tags[message.id] = tags
        await self.process(bot, message, tags, limit)
        
        if self.task_pended.get(chat_id, 0) == 0:
            if chat_id in self.cache_cleanup_tasks:
                self.cache_cleanup_tasks[chat_id].cancel()
                
            self.cache_cleanup_tasks[chat_id] = asyncio.create_task(
                self.clear_cache(chat_id, message.id)
            )

    @allowed_for(["chat_admins", "chat_owner"])
    @command("rating")
    async def rating_cmd(self, bot: Client, message: Message) -> None:
        args = message.text.split()[1:]
        chat_id = message.chat.id

        if not args:
            rating = await self.get_chat_rating(chat_id)
            if rating != "random":
                rating = rating.replace("rating%3a", "")
                
            await message.reply(self.S["rating"]["current"].format(rating=rating))
            return

        user_rating = args[0].lower()
        success = await self.set_chat_rating(chat_id, user_rating)
        
        rating = await self.get_chat_rating(chat_id)
        if rating != "random":
            rating = rating.replace("rating%3a", "")
        
        if success:
            await message.reply(self.S["rating"]["success"].format(rating=rating))
        else:
            await message.reply(self.S["rating"]["failure"].format(rating=rating))

    @allowed_for(["chat_admins", "chat_owner"])
    @command("limit")
    async def limit_cmd(self, bot: Client, message: Message) -> None:
        args = message.text.split()[1:]
        chat_id = message.chat.id

        if not args:
            limit = await self.get_chat_limit(chat_id)
            await message.reply(self.S["limit"]["current_limit"].format(limit=limit))
            return
        
        if not args[0].isdigit():
            await message.reply(self.S["limit"]["arg_invalid"])
            return

        limit = int(args[0])
        
        if limit == 0:
            await self.set_chat_limit(chat_id, limit)
            await message.reply(self.S["limit"]["success_no_limit"])
        elif limit > 100:
            await message.reply(self.S["limit"]["api_exceeded"])
            await self.set_chat_limit(chat_id, limit=100)
        else:
            await self.set_chat_limit(chat_id, limit)
            await message.reply(self.S["limit"]["success"].format(limit=limit))

    @command("tagsearch")
    async def tagsearch_cmd(self, bot: Client, message: Message) -> None:
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

    async def search_tags(self, query: str, page: int) -> Tuple[List[str], int]:
        if not query or not isinstance(page, int) or page < 1:
            return [], 1
            
        try:
            all_tags = await self.gelbooru_search_tags(name_pattern=f"%{query}%")
            if not all_tags:
                return [], 1

            tags_per_page = 15
            total_pages = (len(all_tags) + tags_per_page - 1) // tags_per_page
            
            start = (page - 1) * tags_per_page
            end = start + tags_per_page
            
            tags = [tag['name'] for tag in all_tags[start:end]]
            
            return tags, total_pages
        except Exception as e:
            self.logger.error(f"Unexpected error in search_tags: {e}")
            return [], 1

    async def send_tag_list(self, message: Message, tags: List[str], query: str, page: int, total_pages: int) -> None:
        tag_list = "\n".join(f"• `{tag}`" for tag in tags)
        
        buttons = []
        
        if page > 1:
            buttons.append(InlineKeyboardButton(
                self.S["tagsearch"]["prev"], 
                callback_data=f"tagsearch_prev_{query}_{page - 1}"
            ))
        
        buttons.append(InlineKeyboardButton(
            f"{page}/{total_pages}", 
            callback_data="dummy"
        ))
        
        if page < total_pages:
            buttons.append(InlineKeyboardButton(
                self.S["tagsearch"]["next"], 
                callback_data=f"tagsearch_next_{query}_{page + 1}"
            ))
        
        keyboard = InlineKeyboardMarkup([buttons])
        
        try:
            if message.from_user and message.from_user.is_bot:
                await message.edit_text(
                    tag_list, 
                    reply_markup=keyboard, 
                    parse_mode=enums.ParseMode.MARKDOWN
                )
            else:
                await message.reply(
                    tag_list, 
                    reply_markup=keyboard, 
                    parse_mode=enums.ParseMode.MARKDOWN
                )
        except Exception as e:
            self.logger.error(f"Error sending tag list: {e}")

    @callback_query(filters.regex(r"tagsearch_(prev|next)_(.+?)_(\d+)"))
    async def handle_pagination(self, bot: Client, callback_query) -> None:
        try:
            action, query, page = callback_query.data.split("_")[1:]
            page = int(page)
            
            tags, total_pages = await self.search_tags(query, page)
            
            await self.send_tag_list(callback_query.message, tags, query, page, total_pages)
            await callback_query.answer()
        except Exception as e:
            self.logger.error(f"Error handling pagination: {e}")
            await callback_query.answer()

    @callback_query(filters.regex(r"dummy"))
    async def dummy_callback(self, bot: Client, callback_query) -> None:
        await callback_query.answer()
        
    async def process(self, bot: Client, message: Message, tags: List[str], limit: int) -> None:
        if not tags or not isinstance(limit, int) or limit < 1:
            await message.reply(self.S["pic"]["arg_not_found"])
            return
            
        limit = min(limit, 100)
        chat_id = message.chat.id
        
        results = await self.gelbooru_search_posts(tags, limit=limit, random_posts=True)
        if results is None:
            await message.reply(self.S["process"]["error"])
            return
        if not results:
            await message.reply(self.S["process"]["tags_not_found"])
            return
            
        if chat_id not in self.sent_photos:
            self.sent_photos[chat_id] = set()
            
        new_photos = []
        for photo in results:
            file_url = str(photo.get('file_url', ''))
            if file_url and file_url not in self.sent_photos[chat_id]:
                new_photos.append(photo)
        
        if not new_photos:
            await message.reply(self.S["process"]["no_results"])
            return
        
        for photo in new_photos:
            file_url = str(photo.get('file_url', ''))
            
            try:
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        self.S["process"]["button"].format(file_url=file_url), 
                        url=file_url
                    )]
                ])
                
                if limit == 1:
                    keyboard.inline_keyboard.append([
                        InlineKeyboardButton(
                            self.S["process"]["next_image"], 
                            callback_data="refresh_status"
                        )
                    ])
                
                await message.reply_photo(
                    photo=file_url,
                    caption=self.S["process"]['credit'],
                    reply_markup=keyboard
                )
                
                self.sent_photos[chat_id].add(file_url)
                await asyncio.sleep(1)
                
            except (errors.WebpageCurlFailed, errors.WebpageMediaEmpty, errors.MediaEmpty):
                await message.reply_photo(
                    photo=self.fallback_image,
                    caption=self.S["process"]["curl_error"],
                    reply_markup=keyboard
                )
                self.sent_photos[chat_id].add(file_url)
                
            except errors.FloodWait as e:
                self.logger.warning(f"Hit FloodWait: waiting {e.value} seconds")
                await asyncio.sleep(e.value)
                
            except Exception as e:
                await message.reply(self.S["process"]["error"])
                self.logger.error(f"Error sending photo: {e}")

    @callback_query(filters.regex("refresh_status"))
    async def handle_callback_query(self, bot: Client, callback_query) -> None:
        try:
            chat_id = callback_query.message.chat.id
            message_id = callback_query.message.reply_to_message.id
            
            if chat_id not in self.processing_locks:
                self.processing_locks[chat_id] = asyncio.Lock()
                
            lock = self.processing_locks[chat_id]
            
            if lock.locked():
                await callback_query.answer(self.S["process"]["lock"])
                return
            
            async with lock:
                await self.update_image(bot, callback_query, chat_id, message_id)
                
        except Exception as e:
            self.logger.error(f"Error handling callback query: {e}")
            await callback_query.answer(self.S["process"]["error"], show_alert=True)

    async def update_image(self, bot: Client, callback_query, chat_id: int, message_id: int) -> None:
        tags = self.message_tags.get(message_id, [])
        if not tags:
            await callback_query.answer()
            return
        
        max_attempts = 5
        attempt = 0
        photo = None
        file_url = None
        
        while attempt < max_attempts:
            results = await self.gelbooru_search_posts(tags, limit=1, random_posts=True)
            if not results:
                if attempt == 0:
                    await callback_query.answer(self.S["process"]["tags_not_found"], show_alert=True)
                    return
                break

            candidate_photo = results[0]
            candidate_url = str(candidate_photo.get('file_url', ''))

            if chat_id not in self.sent_photos or candidate_url not in self.sent_photos[chat_id]:
                photo = candidate_photo
                file_url = candidate_url
                break
            
            attempt += 1

        if not photo:
            await callback_query.answer(self.S["process"]["no_results"], show_alert=True)
            return
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                self.S["process"]["button"].format(file_url=file_url), 
                url=file_url
            )],
            [InlineKeyboardButton(
                self.S["process"]["next_image"], 
                callback_data="refresh_status"
            )]
        ])
        
        try:
            await callback_query.message.edit_media(
                media=InputMediaPhoto(file_url),
                reply_markup=keyboard
            )
            
            if chat_id not in self.sent_photos:
                self.sent_photos[chat_id] = set()
            self.sent_photos[chat_id].add(file_url)
            
            await callback_query.answer()
            
        except (errors.WebpageCurlFailed, errors.WebpageMediaEmpty, errors.MediaEmpty):
            try:
                await callback_query.message.edit_media(
                    media=InputMediaPhoto(self.fallback_image),
                    reply_markup=keyboard
                )
                self.sent_photos[chat_id].add(file_url)
                await callback_query.answer(self.S["process"]["curl_error"], show_alert=True)
            except Exception as e:
                self.logger.error(f"Error sending fallback image: {e}")
                await callback_query.answer(self.S["process"]["error"], show_alert=True)
                
        except errors.FloodWait as e:
            self.logger.warning(f"Hit FloodWait: waiting {e.value} seconds")
            await callback_query.answer(self.S["pic"]["rate_limit"].format(value=e.value), show_alert=True)
            
        except errors.QueryIdInvalid:
            pass
            
        except Exception as e:
            self.logger.error(f"Error updating image: {e}")
            try:
                await callback_query.answer(self.S["process"]["error"], show_alert=True)
            except:
                pass
