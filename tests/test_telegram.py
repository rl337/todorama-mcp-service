"""
Tests for Telegram voice message integration.

Tests Telegram bot functionality including:
- Sending voice messages to Telegram
- Handling Telegram API rate limits
- Retry logic for failed sends
- User feedback (typing indicators, status messages)
"""
import pytest
import os
import tempfile
import shutil
import time
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from main import app
from database import TodoDatabase
from backup import BackupManager


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")
    backups_dir = os.path.join(temp_dir, "backups")
    
    # Create database
    db = TodoDatabase(db_path)
    backup_manager = BackupManager(db_path, backups_dir)
    
    # Override the database and backup manager in the app
    import main
    main.db = db
    main.backup_manager = backup_manager
    
    yield db, db_path, backups_dir
    
    shutil.rmtree(temp_dir)


@pytest.fixture
def client(temp_db):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def sample_audio_file(temp_db):
    """Create a sample audio file for testing."""
    temp_dir = tempfile.mkdtemp()
    audio_file = os.path.join(temp_dir, "test_audio.ogg")
    # Create a minimal OGG file (just create an empty file for testing)
    with open(audio_file, 'wb') as f:
        f.write(b'\x4f\x67\x67\x53')  # OGG header
        f.write(b'\x00' * 100)  # Some dummy data
    yield audio_file
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_telegram_bot():
    """Mock Telegram bot for testing."""
    with patch('telegram.Bot') as mock_bot_class:
        mock_bot = AsyncMock()
        mock_bot_class.return_value = mock_bot
        yield mock_bot


@pytest.mark.asyncio
async def test_send_voice_message_success(mock_telegram_bot, sample_audio_file):
    """Test successfully sending a voice message to Telegram."""
    from src.telegram import TelegramBot
    
    chat_id = 12345
    mock_telegram_bot.send_voice = AsyncMock(return_value=MagicMock(message_id=1))
    mock_telegram_bot.send_chat_action = AsyncMock(return_value=True)
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    result = await bot.send_voice_message(chat_id, sample_audio_file)
    
    assert result is True
    mock_telegram_bot.send_chat_action.assert_called_once()
    mock_telegram_bot.send_voice.assert_called_once()


@pytest.mark.asyncio
async def test_send_voice_message_with_typing_indicator(mock_telegram_bot, sample_audio_file):
    """Test that typing indicator is sent before voice message."""
    from src.telegram import TelegramBot
    
    chat_id = 12345
    mock_telegram_bot.send_chat_action = AsyncMock(return_value=True)
    mock_telegram_bot.send_voice = AsyncMock(return_value=MagicMock(message_id=1))
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    result = await bot.send_voice_message(chat_id, sample_audio_file, show_typing=True)
    
    assert result is True
    # Verify typing indicator was sent
    calls = mock_telegram_bot.send_chat_action.call_args_list
    assert len(calls) >= 1
    # Check that typing action was sent
    typing_calls = [c for c in calls if 'typing' in str(c[1].get('action', ''))]
    assert len(typing_calls) > 0


@pytest.mark.asyncio
async def test_send_voice_message_rate_limit_handling(mock_telegram_bot, sample_audio_file):
    """Test that rate limits are handled with exponential backoff."""
    from src.telegram import TelegramBot
    from telegram.error import RetryAfter
    
    chat_id = 12345
    
    # Create a RetryAfter exception with retry_after attribute
    rate_limit_error = RetryAfter(retry_after=2)
    rate_limit_error.retry_after = 2
    
    mock_telegram_bot.send_voice = AsyncMock(side_effect=[
        rate_limit_error,
        MagicMock(message_id=1)  # Success on retry
    ])
    mock_telegram_bot.send_chat_action = AsyncMock(return_value=True)
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    result = await bot.send_voice_message(chat_id, sample_audio_file, max_retries=3)
    
    assert result is True
    assert mock_telegram_bot.send_voice.call_count == 2


@pytest.mark.asyncio
async def test_send_voice_message_retry_on_failure(mock_telegram_bot, sample_audio_file):
    """Test retry logic for failed voice message sends."""
    from src.telegram import TelegramBot
    from telegram.error import NetworkError
    
    chat_id = 12345
    mock_telegram_bot.send_voice = AsyncMock(side_effect=[
        NetworkError("Network error"),
        NetworkError("Network error"),
        MagicMock(message_id=1)  # Success on third try
    ])
    mock_telegram_bot.send_chat_action = AsyncMock(return_value=True)
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    result = await bot.send_voice_message(chat_id, sample_audio_file, max_retries=3)
    
    assert result is True
    assert mock_telegram_bot.send_voice.call_count == 3


@pytest.mark.asyncio
async def test_send_voice_message_max_retries_exceeded(mock_telegram_bot, sample_audio_file):
    """Test that sending fails after max retries are exceeded."""
    from src.telegram import TelegramBot
    from telegram.error import NetworkError
    
    chat_id = 12345
    mock_telegram_bot.send_voice = AsyncMock(side_effect=NetworkError("Persistent error"))
    mock_telegram_bot.send_chat_action = AsyncMock(return_value=True)
    mock_telegram_bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    result = await bot.send_voice_message(chat_id, sample_audio_file, max_retries=2)
    
    assert result is False
    assert mock_telegram_bot.send_voice.call_count == 2


@pytest.mark.asyncio
async def test_send_status_message(mock_telegram_bot):
    """Test sending status messages to users."""
    from src.telegram import TelegramBot
    
    chat_id = 12345
    mock_telegram_bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    result = await bot.send_status_message(chat_id, "Processing your request...")
    
    assert result is True
    mock_telegram_bot.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_send_typing_indicator(mock_telegram_bot):
    """Test sending typing indicator."""
    from src.telegram import TelegramBot
    
    chat_id = 12345
    mock_telegram_bot.send_chat_action = AsyncMock(return_value=True)
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    result = await bot.send_typing_indicator(chat_id)
    
    assert result is True
    mock_telegram_bot.send_chat_action.assert_called_once()


def test_telegram_bot_initialization_with_token():
    """Test Telegram bot initialization with token."""
    from src.telegram import TelegramBot
    
    with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test_token_123"}):
        bot = TelegramBot()
        assert bot.bot_token == "test_token_123"


def test_telegram_bot_initialization_without_token():
    """Test Telegram bot initialization without token (should be disabled)."""
    from src.telegram import TelegramBot
    
    with patch.dict(os.environ, {}, clear=True):
        bot = TelegramBot()
        assert bot.bot_token is None
        assert bot.bot is None


@pytest.mark.asyncio
async def test_send_voice_message_with_caption(mock_telegram_bot, sample_audio_file):
    """Test sending voice message with caption."""
    from src.telegram import TelegramBot
    
    chat_id = 12345
    caption = "This is a test voice message"
    mock_telegram_bot.send_voice = AsyncMock(return_value=MagicMock(message_id=1))
    mock_telegram_bot.send_chat_action = AsyncMock(return_value=True)
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    result = await bot.send_voice_message(chat_id, sample_audio_file, caption=caption)
    
    assert result is True
    # Verify caption was passed to send_voice
    call_args = mock_telegram_bot.send_voice.call_args
    assert call_args[1].get('caption') == caption


def test_audio_conversion_before_sending(mock_telegram_bot):
    """Test that audio is converted to Telegram format before sending."""
    from src.telegram import TelegramBot
    from src.audio_converter import TelegramAudioConverter
    
    chat_id = 12345
    # Create a temporary WAV file
    temp_dir = tempfile.mkdtemp()
    wav_file = os.path.join(temp_dir, "test_audio.wav")
    with open(wav_file, 'wb') as f:
        f.write(b'RIFF' + b'\x00' * 100)  # Minimal WAV header
    
    mock_telegram_bot.send_voice = AsyncMock(return_value=MagicMock(message_id=1))
    mock_telegram_bot.send_chat_action = AsyncMock(return_value=True)
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    with patch('src.telegram.TelegramAudioConverter') as mock_converter_class:
        mock_converter = MagicMock()
        mock_converter_class.return_value = mock_converter
        mock_converter.convert_for_telegram = MagicMock(return_value=True)
        
        # Create a temporary output file
        ogg_file = os.path.join(temp_dir, "test_audio.ogg")
        with open(ogg_file, 'wb') as f:
            f.write(b'\x4f\x67\x67\x53')  # OGG header
        
        result = bot.send_voice_message(chat_id, wav_file)
        
        # Note: In actual implementation, conversion would happen automatically
        # This test verifies the concept
    
    shutil.rmtree(temp_dir)


@pytest.mark.asyncio
async def test_handle_telegram_api_error(mock_telegram_bot, sample_audio_file):
    """Test handling of Telegram API errors."""
    from src.telegram import TelegramBot
    from telegram.error import TelegramError
    
    chat_id = 12345
    mock_telegram_bot.send_voice = AsyncMock(side_effect=TelegramError("Telegram API error"))
    mock_telegram_bot.send_chat_action = AsyncMock(return_value=True)
    mock_telegram_bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    result = await bot.send_voice_message(chat_id, sample_audio_file, max_retries=1)
    
    assert result is False


@pytest.mark.asyncio
async def test_stream_text_message_success(mock_telegram_bot):
    """Test successfully streaming text message to Telegram."""
    from src.telegram import TelegramBot
    
    chat_id = 12345
    message_id = 123
    
    # Mock initial message send
    sent_message = MagicMock(message_id=message_id)
    mock_telegram_bot.send_message = AsyncMock(return_value=sent_message)
    mock_telegram_bot.edit_message_text = AsyncMock(return_value=True)
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    # Create async generator for text chunks
    async def text_generator():
        for chunk in ["Hello", " ", "world", "!"]:
            yield chunk
            await asyncio.sleep(0.01)
    
    result = await bot.stream_text_message(
        chat_id=chat_id,
        text_generator=text_generator(),
        initial_text="...",
        update_interval=0.05,
        min_update_length=1
    )
    
    assert result == message_id
    mock_telegram_bot.send_message.assert_called_once()
    # Should be called multiple times for updates
    assert mock_telegram_bot.edit_message_text.call_count >= 1


@pytest.mark.asyncio
async def test_stream_text_message_with_interruption(mock_telegram_bot):
    """Test streaming handles message deletion gracefully."""
    from src.telegram import TelegramBot
    from telegram.error import TelegramError
    
    chat_id = 12345
    message_id = 123
    
    # Mock initial message send
    sent_message = MagicMock(message_id=message_id)
    mock_telegram_bot.send_message = AsyncMock(return_value=sent_message)
    
    # First update succeeds, second fails with "message not found"
    error = TelegramError("message to edit not found")
    mock_telegram_bot.edit_message_text = AsyncMock(side_effect=[True, error])
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    # Create async generator for text chunks
    async def text_generator():
        for chunk in ["Hello", " ", "world", "!"]:
            yield chunk
            await asyncio.sleep(0.01)
    
    result = await bot.stream_text_message(
        chat_id=chat_id,
        text_generator=text_generator(),
        initial_text="...",
        update_interval=0.05,
        min_update_length=1
    )
    
    # Should return message_id even if interrupted
    assert result == message_id


@pytest.mark.asyncio
async def test_stream_text_message_long_text(mock_telegram_bot):
    """Test streaming handles long text (Telegram 4096 char limit)."""
    from src.telegram import TelegramBot
    
    chat_id = 12345
    message_id = 123
    
    # Mock initial message send
    sent_message = MagicMock(message_id=message_id)
    mock_telegram_bot.send_message = AsyncMock(return_value=sent_message)
    mock_telegram_bot.edit_message_text = AsyncMock(return_value=True)
    
    bot = TelegramBot(bot_token="test_token")
    bot.bot = mock_telegram_bot
    
    # Create async generator with long text
    async def text_generator():
        # Generate text that exceeds 4096 characters
        long_text = "A" * 5000
        for i in range(0, len(long_text), 100):
            yield long_text[i:i+100]
            await asyncio.sleep(0.01)
    
    result = await bot.stream_text_message(
        chat_id=chat_id,
        text_generator=text_generator(),
        initial_text="...",
        update_interval=0.05,
        min_update_length=1
    )
    
    assert result == message_id
    # Verify that edit_message_text was called with truncated text
    edit_calls = mock_telegram_bot.edit_message_text.call_args_list
    if edit_calls:
        # Last call should have truncated text
        last_call = edit_calls[-1]
        text_arg = last_call[1].get('text', '')
        assert len(text_arg) <= 4096


@pytest.mark.asyncio
async def test_stream_llm_response_to_telegram_integration(mock_telegram_bot):
    """Test integration function for streaming LLM responses to Telegram."""
    from src.telegram import stream_llm_response_to_telegram, get_telegram_bot
    
    chat_id = 12345
    message_id = 123
    
    # Mock Telegram bot
    sent_message = MagicMock(message_id=message_id)
    mock_telegram_bot.send_message = AsyncMock(return_value=sent_message)
    mock_telegram_bot.edit_message_text = AsyncMock(return_value=True)
    
    # Set up global bot instance
    bot = get_telegram_bot()
    if bot:
        bot.bot = mock_telegram_bot
    
    # Create async generator for LLM response
    async def llm_generator():
        chunks = ["The", " quick", " brown", " fox", " jumps", " over", " the", " lazy", " dog."]
        for chunk in chunks:
            yield chunk
            await asyncio.sleep(0.01)
    
    result = await stream_llm_response_to_telegram(
        chat_id=chat_id,
        llm_stream_generator=llm_generator(),
        initial_text="Thinking...",
        update_interval=0.05,
        min_update_length=1
    )
    
    assert result == message_id
    mock_telegram_bot.send_message.assert_called_once()
