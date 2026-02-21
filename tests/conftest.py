# tests/conftest.py
"""Pytest configuration and fixtures"""
import pytest
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Register bot handlers (engine is decoupled from specific handlers)
import app.core.handlers  # noqa: F401


@pytest.fixture
def sample_twilio_form_data():
    """Sample Twilio webhook form data"""
    return {
        "From": "+12345678900",
        "To": "+10987654321",
        "Body": "Test message",
        "MessageSid": "SM1234567890abcdef",
        "NumMedia": "0",
        "AccountSid": "AC1234567890abcdef"
    }


@pytest.fixture
def sample_twilio_mms_form_data():
    """Sample Twilio MMS webhook form data"""
    return {
        "From": "+12345678900",
        "To": "+10987654321",
        "Body": "Check this out",
        "MessageSid": "MM1234567890abcdef",
        "NumMedia": "1",
        "MediaUrl0": "https://api.twilio.com/2010-04-01/Accounts/.../Media/ME123",
        "MediaContentType0": "image/jpeg",
        "AccountSid": "AC1234567890abcdef"
    }


@pytest.fixture
def tenant_id():
    """Default tenant ID for tests"""
    return "test_tenant"


@pytest.fixture
def chat_id():
    """Default chat ID for tests"""
    return "+12345678900"
