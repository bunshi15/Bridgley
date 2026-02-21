#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Bot Example

Demonstrates how to use the universal engine with different bot types.
Shows how easy it is to switch between bots or use multiple bots in the same application.

Run from project root:
    python examples/multi_bot_example.py
"""
import sys
import os
from pathlib import Path

# Fix Windows console encoding for Cyrillic text
if sys.platform == 'win32':
    import codecs
    sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
    sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.core.universal_engine import UniversalEngine
from app.core.bot_handler import BotHandlerRegistry
# Import handlers to ensure they're registered
import app.core.handlers  # noqa: F401


def demo_moving_bot():
    """Demonstrate moving bot conversation"""
    print("\n" + "="*60)
    print("MOVING BOT DEMO")
    print("="*60 + "\n")

    # Create a new session for moving bot
    session = UniversalEngine.new_session(
        tenant_id="demo_tenant",
        chat_id="demo_user_1",
        bot_type="moving_bot_v1",
        language="ru"
    )
    print(f"✓ Created session: {session.lead_id}")
    print(f"  Bot Type: {session.bot_type}")
    print(f"  Step: {session.step}\n")

    # Simulate conversation
    conversations = [
        ("Привет", "User says hello"),
        ("Мебель из квартиры", "User describes cargo"),
        ("Москва → Санкт-Петербург, ул. Ленина 10", "User provides addresses"),
        ("завтра", "User selects time"),
        ("1", "User wants to upload photos"),
        ("готово", "User finished uploading photos"),
        ("нет", "User doesn't need extra services"),
    ]

    for user_input, description in conversations:
        print(f"User: {user_input}  ({description})")
        session, reply, is_done = UniversalEngine.handle_text(session, user_input)
        print(f"Bot:  {reply}")
        print(f"      Step: {session.step}, Done: {is_done}\n")

        if is_done:
            print("✓ Conversation completed!")
            payload = UniversalEngine.get_payload(session)
            print(f"  Final payload: {payload}\n")
            break


def demo_list_available_bots():
    """List all registered bot types"""
    print("\n" + "="*60)
    print("AVAILABLE BOT TYPES")
    print("="*60 + "\n")

    bot_types = BotHandlerRegistry.list_types()
    print(f"Found {len(bot_types)} registered bot type(s):\n")

    for bot_type in bot_types:
        handler = BotHandlerRegistry.get(bot_type)
        config = handler.config
        print(f"• {bot_type}")
        print(f"  Name: {config.name.ru} (ru) / {config.name.en} (en)")
        print(f"  Description: {config.description.ru}")
        print(f"  Initial Step: {config.initial_step}")
        print(f"  Final Step: {config.final_step}")
        print()


def demo_multi_tenant():
    """Demonstrate multiple tenants using different bot types"""
    print("\n" + "="*60)
    print("MULTI-TENANT DEMO (Different bots per tenant)")
    print("="*60 + "\n")

    # Tenant A uses moving bot
    session_a = UniversalEngine.new_session(
        tenant_id="tenant_a",
        chat_id="user_001",
        bot_type="moving_bot_v1"
    )
    print(f"Tenant A (Moving Bot):")
    print(f"  Session ID: {session_a.lead_id}")
    print(f"  Bot Type: {session_a.bot_type}")
    session_a, reply_a, _ = UniversalEngine.handle_text(session_a, "Hello")
    print(f"  First Message: {reply_a[:50]}...\n")

    # Future: Tenant B uses restaurant bot
    # session_b = UniversalEngine.new_session(
    #     tenant_id="tenant_b",
    #     chat_id="user_002",
    #     bot_type="restaurant_bot_v1"
    # )
    print(f"Tenant B (Restaurant Bot): [Not yet implemented]")
    print(f"  Would use: restaurant_bot_v1")
    print(f"  Would ask: 'What cuisine are you interested in?'\n")


def demo_error_handling():
    """Demonstrate error handling for unknown bot types"""
    print("\n" + "="*60)
    print("ERROR HANDLING DEMO")
    print("="*60 + "\n")

    try:
        session = UniversalEngine.new_session(
            tenant_id="demo",
            chat_id="user",
            bot_type="unknown_bot_v1"  # Invalid bot type
        )
    except ValueError as e:
        print(f"✓ Caught expected error:")
        print(f"  {e}\n")


def demo_flexible_data_storage():
    """Demonstrate flexible data storage in LeadData"""
    print("\n" + "="*60)
    print("FLEXIBLE DATA STORAGE DEMO")
    print("="*60 + "\n")

    session = UniversalEngine.new_session(
        tenant_id="demo",
        chat_id="user",
        bot_type="moving_bot_v1"
    )

    # Moving bot uses predefined fields
    print("Moving Bot - Predefined fields:")
    session.data.cargo_description = "Furniture"
    session.data.addr_from = "NYC, 5th Ave 100"
    session.data.floor_from = "3rd floor, elevator"
    session.data.addr_to = "Boston, Main St 50"
    session.data.floor_to = "1st floor"
    print(f"  cargo_description: {session.data.cargo_description}")
    print(f"  addr_from: {session.data.addr_from} (floor: {session.data.floor_from})")
    print(f"  addr_to: {session.data.addr_to} (floor: {session.data.floor_to})\n")

    # Any bot can use custom dict
    print("Any Bot - Custom fields (for new bot types):")
    session.data.custom["cuisine"] = "italian"
    session.data.custom["party_size"] = 4
    session.data.custom["special_request"] = "Window seat please"
    print(f"  custom['cuisine']: {session.data.custom['cuisine']}")
    print(f"  custom['party_size']: {session.data.custom['party_size']}")
    print(f"  custom['special_request']: {session.data.custom['special_request']}\n")

    # Use get/set methods
    session.data.set("reservation_time", "19:00")
    print(f"  get('reservation_time'): {session.data.get('reservation_time')}")
    print(f"  get('nonexistent', 'default'): {session.data.get('nonexistent', 'default')}\n")


def main():
    """Run all demos"""
    print("\n" + "="*70)
    print(" "*15 + "UNIVERSAL ENGINE DEMO")
    print("="*70)

    demo_list_available_bots()
    demo_moving_bot()
    demo_multi_tenant()
    demo_flexible_data_storage()
    demo_error_handling()

    print("\n" + "="*70)
    print("Demo completed! Check UNIVERSAL_ENGINE_GUIDE.md for more info.")
    print("="*70 + "\n")


if __name__ == "__main__":
    main()
