# AnimePic
### Description: 
This module for [PBModular](https://github.com/PBModular/bot) is designed to request and view pictures from Gelbooru directly in Telegram.

### Installation
- <code>/mod_install https://github.com/PBModular/AnimePic</code>

**Optional:**

- Set <code>api_key</code> and <code>user_id</code> in main.py

### Usage
<b>Example:</b> <code>/pic 5 cyberpunk</code>

- <code>/pic</code> – <i>Main command for image search</i>
- <code>5</code> – <i>Number of images (Optional, 1 if not specified)</i>
- <code>cyberpunk</code> – <i>Tag for search (Can be many)</i>

<b>Example:</b> <code>/rating rs</code>

- <code>/rating</code> – <i>Command to set/view the rating in the current chat</i>
- <code>rs</code> – <i>Rating</i>

<b>Example:</b> <code>/limit 10</code>

- <code>/limit</code> - <i>Command to set/view the current image request limit</i>
- <code>10</code> - <i>Limit (If not specified, the current limit will be shown)</i>

<b>Example:</b> <code>/tagsearch cat_girl</code>

- <code>/tagsearch</code> – <i>Command to search for tags on Gelbooru</i>
- <code>cat_girl</code> – <i>The query to search for tags (e.g., "blue_hair", "1girl")</i>

<b>Available ratings:</b>

- <code>rs</code> <i>– Safe (Default)</i>
- <code>rq</code> <i>– Questionable</i>
- <code>re</code> <i>– Explicit</i>
- <code>r</code> <i>– Random</i>
