# AnimePic
### Description: 
This module for [PBModular](https://github.com/PBModular/bot) is designed to request and view pictures from Gelbooru directly in Telegram.

### Installation
- <code>/mod_install https://github.com/PBModularModules/AnimePic</code>

**Optional:**

- Set <code>api_key</code> and <code>user_id</code> in main.py

### Usage
<b>Example:</b> <code>/pic 5 cyberpunk</code>

- <code>/pic</code> – <i>Main command for image search</i>
- <code>5</code> – <i>Number of images (Optional, 1 if not specified)</i>
- <code>cyberpunk</code> – <i>Tag for search (Can be many)</i>

<b>Example:</b> <code>/setrating rs</code>

- <code>/setrating</code> – <i>Command for setting the rating</i>
- <code>rs</code> – <i>Rating</i>

<b>Available ratings:</b>

- <code>rs</code> <i>– Safe (Default)</i>
- <code>rq</code> <i>– Questionable</i>
- <code>re</code> <i>– Explicit</i>
- <code>r</code> <i>– Random</i>
