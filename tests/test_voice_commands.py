"""
Tests for voice command recognition functionality.

Tests voice command recognition including:
- Speech-to-text conversion
- Command keyword detection
- Intent classification
- Command parsing and extraction
"""
import pytest
import os
import tempfile
import wave
import struct
from unittest.mock import Mock, patch, MagicMock

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from voice_commands import (
        VoiceCommandRecognizer,
        VoiceCommandError,
        CommandType,
        VoiceCommand
    )
except ImportError:
    # Handle case where module doesn't exist yet
    VoiceCommandRecognizer = None
    VoiceCommandError = Exception
    CommandType = None
    VoiceCommand = None


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    temp_path = tempfile.mkdtemp()
    yield temp_path
    import shutil
    shutil.rmtree(temp_path)


@pytest.fixture
def sample_wav_file(temp_dir):
    """Create a sample WAV file for testing."""
    wav_path = os.path.join(temp_dir, "test.wav")
    
    # Create a simple WAV file (1 second, 16kHz, mono, 16-bit)
    sample_rate = 16000
    duration = 1  # 1 second
    num_samples = sample_rate * duration
    
    with wave.open(wav_path, 'w') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        
        # Generate simple audio data
        for i in range(num_samples):
            value = int(32767 * 0.3)
            wav_file.writeframes(struct.pack('<h', value))
    
    return wav_path


@pytest.fixture
def recognizer():
    """Create voice command recognizer instance."""
    return VoiceCommandRecognizer()


class TestVoiceCommandRecognizer:
    """Test voice command recognition."""
    
    def test_recognizer_initialization(self):
        """Test that recognizer initializes correctly."""
        recognizer = VoiceCommandRecognizer()
        assert recognizer is not None
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_recognize_command_new_conversation(self, mock_recognizer_class, mock_sr):
        """Test recognizing 'new conversation' command."""
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        mock_recognizer.recognize_google.return_value = "new conversation"
        
        # Mock AudioFile context manager
        mock_audio_file = MagicMock()
        mock_audio_file.__enter__ = MagicMock(return_value=MagicMock())
        mock_audio_file.__exit__ = MagicMock(return_value=False)
        mock_sr.AudioFile.return_value = mock_audio_file
        
        recognizer = VoiceCommandRecognizer()
        command = recognizer.recognize_command("test.wav")
        
        assert command is not None
        assert command.command_type == CommandType.NEW_CONVERSATION
        assert command.confidence > 0.0
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_recognize_command_clear_history(self, mock_recognizer_class, mock_sr):
        """Test recognizing 'clear history' command."""
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        mock_recognizer.recognize_google.return_value = "clear history"
        
        # Mock AudioFile context manager
        mock_audio_file = MagicMock()
        mock_audio_file.__enter__ = MagicMock(return_value=MagicMock())
        mock_audio_file.__exit__ = MagicMock(return_value=False)
        mock_sr.AudioFile.return_value = mock_audio_file
        
        recognizer = VoiceCommandRecognizer()
        command = recognizer.recognize_command("test.wav")
        
        assert command is not None
        assert command.command_type == CommandType.CLEAR_HISTORY
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_recognize_command_change_language(self, mock_recognizer_class, mock_sr):
        """Test recognizing 'change language' command."""
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        mock_recognizer.recognize_google.return_value = "change language to Spanish"
        
        # Mock AudioFile context manager
        mock_audio_file = MagicMock()
        mock_audio_file.__enter__ = MagicMock(return_value=MagicMock())
        mock_audio_file.__exit__ = MagicMock(return_value=False)
        mock_sr.AudioFile.return_value = mock_audio_file
        
        recognizer = VoiceCommandRecognizer()
        command = recognizer.recognize_command("test.wav")
        
        assert command is not None
        assert command.command_type == CommandType.CHANGE_LANGUAGE
        assert command.parameters.get("language") == "Spanish"
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_recognize_command_unknown(self, mock_recognizer_class, mock_sr):
        """Test handling unknown commands."""
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        mock_recognizer.recognize_google.return_value = "this is not a command"
        
        # Mock AudioFile context manager
        mock_audio_file = MagicMock()
        mock_audio_file.__enter__ = MagicMock(return_value=MagicMock())
        mock_audio_file.__exit__ = MagicMock(return_value=False)
        mock_sr.AudioFile.return_value = mock_audio_file
        
        recognizer = VoiceCommandRecognizer()
        command = recognizer.recognize_command("test.wav")
        
        assert command is not None
        assert command.command_type == CommandType.UNKNOWN
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_recognize_command_with_keywords(self, mock_recognizer_class, mock_sr):
        """Test keyword-based detection for various phrasings."""
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        
        # Mock AudioFile context manager
        mock_audio_file = MagicMock()
        mock_audio_file.__enter__ = MagicMock(return_value=MagicMock())
        mock_audio_file.__exit__ = MagicMock(return_value=False)
        mock_sr.AudioFile.return_value = mock_audio_file
        
        test_cases = [
            ("start new conversation", CommandType.NEW_CONVERSATION),
            ("begin new chat", CommandType.NEW_CONVERSATION),
            ("clear my history", CommandType.CLEAR_HISTORY),
            ("delete history", CommandType.CLEAR_HISTORY),
            ("switch to French", CommandType.CHANGE_LANGUAGE),
            ("set language to German", CommandType.CHANGE_LANGUAGE),
        ]
        
        recognizer = VoiceCommandRecognizer()
        
        for text, expected_command in test_cases:
            mock_recognizer.recognize_google.return_value = text
            command = recognizer.recognize_command("test.wav")
            assert command.command_type == expected_command, \
                f"Failed for text: {text}"
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_stt_error_handling(self, mock_recognizer_class, mock_sr):
        """Test handling of STT errors."""
        # Create exception class
        UnknownValueError = type('UnknownValueError', (Exception,), {})
        mock_sr.UnknownValueError = UnknownValueError
        
        # Create a mock recognizer that raises error
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        mock_recognizer.recognize_google.side_effect = UnknownValueError()
        
        # Mock AudioFile context manager
        mock_audio_file = MagicMock()
        mock_audio_file.__enter__ = MagicMock(return_value=MagicMock())
        mock_audio_file.__exit__ = MagicMock(return_value=False)
        mock_sr.AudioFile.return_value = mock_audio_file
        
        recognizer = VoiceCommandRecognizer()
        
        with pytest.raises(VoiceCommandError):
            recognizer.recognize_command("test.wav")
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_stt_connection_error(self, mock_recognizer_class, mock_sr):
        """Test handling of STT connection errors."""
        # Create exception class
        RequestError = type('RequestError', (Exception,), {})
        mock_sr.RequestError = RequestError
        
        # Create a mock recognizer that raises error
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        mock_recognizer.recognize_google.side_effect = RequestError("Connection failed")
        
        # Mock AudioFile context manager
        mock_audio_file = MagicMock()
        mock_audio_file.__enter__ = MagicMock(return_value=MagicMock())
        mock_audio_file.__exit__ = MagicMock(return_value=False)
        mock_sr.AudioFile.return_value = mock_audio_file
        
        recognizer = VoiceCommandRecognizer()
        
        with pytest.raises(VoiceCommandError) as exc_info:
            recognizer.recognize_command("test.wav")
        
        assert "error" in str(exc_info.value).lower()
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_recognize_command_file_not_found(self, mock_recognizer_class, mock_sr):
        """Test handling of missing audio file."""
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        
        recognizer = VoiceCommandRecognizer()
        
        with pytest.raises(VoiceCommandError) as exc_info:
            recognizer.recognize_command("nonexistent.wav")
        
        assert "not found" in str(exc_info.value).lower()
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_case_insensitive_recognition(self, mock_recognizer_class, mock_sr):
        """Test that command recognition is case-insensitive."""
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        mock_recognizer.recognize_google.return_value = "NEW CONVERSATION"
        
        # Mock AudioFile context manager
        mock_audio_file = MagicMock()
        mock_audio_file.__enter__ = MagicMock(return_value=MagicMock())
        mock_audio_file.__exit__ = MagicMock(return_value=False)
        mock_sr.AudioFile.return_value = mock_audio_file
        
        recognizer = VoiceCommandRecognizer()
        command = recognizer.recognize_command("test.wav")
        
        assert command.command_type == CommandType.NEW_CONVERSATION
    
    @patch('voice_commands.sr')
    @patch('voice_commands.sr.Recognizer')
    def test_command_with_extra_words(self, mock_recognizer_class, mock_sr):
        """Test that commands are recognized even with extra words."""
        mock_recognizer = MagicMock()
        mock_recognizer_class.return_value = mock_recognizer
        mock_recognizer.recognize_google.return_value = "please start a new conversation now"
        
        # Mock AudioFile context manager
        mock_audio_file = MagicMock()
        mock_audio_file.__enter__ = MagicMock(return_value=MagicMock())
        mock_audio_file.__exit__ = MagicMock(return_value=False)
        mock_sr.AudioFile.return_value = mock_audio_file
        
        recognizer = VoiceCommandRecognizer()
        command = recognizer.recognize_command("test.wav")
        
        assert command.command_type == CommandType.NEW_CONVERSATION
