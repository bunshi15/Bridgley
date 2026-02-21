# app/core/bots/example/__init__.py
"""
Example bot — template for creating new bot packages.

To create a new bot:
1. Copy this directory: ``cp -r example/ my_new_bot/``
2. Edit ``config.py`` — define your BotConfig, translations, choices
3. Register in ``app/core/bots/__init__.py``::

       from app.core.bots.my_new_bot.config import MY_BOT_CONFIG
       BotRegistry.register("my_new_bot", MY_BOT_CONFIG)

4. Create a handler in ``app/core/handlers/my_new_bot_handler.py``
5. Add tests in ``tests/test_my_new_bot.py``

See ``moving_bot_v1/`` for a complete real-world example.
"""
