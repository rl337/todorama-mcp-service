"""
Tests for audio format conversion utility.
"""
import pytest
import os
import tempfile
import wave
import struct
import io
from pathlib import Path

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from audio_converter import AudioConverter, AudioConversionError, TelegramAudioConverter


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
    frequency = 440  # A4 note
    num_samples = sample_rate * duration
    
    with wave.open(wav_path, 'w') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        
        # Generate a sine wave
        for i in range(num_samples):
            value = int(32767 * 0.3 * 
                       (struct.pack('<f', 2 * 3.14159 * frequency * i / sample_rate)[0] / 127.0))
            wav_file.writeframes(struct.pack('<h', value))
    
    return wav_path


@pytest.fixture
def long_wav_file(temp_dir):
    """Create a long WAV file (>1 minute) for duration limit testing."""
    wav_path = os.path.join(temp_dir, "long_test.wav")
    
    # Create a 90 second WAV file
    sample_rate = 16000
    duration = 90  # 90 seconds
    frequency = 440
    num_samples = sample_rate * duration
    
    with wave.open(wav_path, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        for i in range(num_samples):
            value = int(32767 * 0.3 * 
                       (struct.pack('<f', 2 * 3.14159 * frequency * i / sample_rate)[0] / 127.0))
            wav_file.writeframes(struct.pack('<h', value))
    
    return wav_path


class TestAudioConverter:
    """Test basic audio converter functionality."""
    
    def test_convert_wav_to_opus(self, temp_dir, sample_wav_file):
        """Test converting WAV to OPUS format."""
        converter = AudioConverter()
        output_path = os.path.join(temp_dir, "output.opus")
        
        result = converter.convert_to_opus(sample_wav_file, output_path)
        
        assert result is True
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0
    
    def test_convert_wav_to_ogg_opus(self, temp_dir, sample_wav_file):
        """Test converting WAV to OGG/OPUS format."""
        converter = AudioConverter()
        output_path = os.path.join(temp_dir, "output.ogg")
        
        result = converter.convert_to_ogg_opus(sample_wav_file, output_path)
        
        assert result is True
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0
    
    def test_invalid_input_file(self, temp_dir):
        """Test error handling for invalid input file."""
        converter = AudioConverter()
        output_path = os.path.join(temp_dir, "output.opus")
        
        with pytest.raises(AudioConversionError):
            converter.convert_to_opus("nonexistent.wav", output_path)
    
    def test_get_audio_duration(self, sample_wav_file):
        """Test getting audio duration."""
        converter = AudioConverter()
        duration = converter.get_audio_duration(sample_wav_file)
        
        assert duration is not None
        assert 0.9 <= duration <= 1.1  # Should be approximately 1 second


class TestTelegramAudioConverter:
    """Test Telegram-specific audio converter."""
    
    def test_convert_for_telegram_short_audio(self, temp_dir, sample_wav_file):
        """Test converting short audio (<1 minute) for Telegram."""
        converter = TelegramAudioConverter()
        output_path = os.path.join(temp_dir, "telegram_output.ogg")
        
        result = converter.convert_for_telegram(sample_wav_file, output_path)
        
        assert result is True
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 0
        
        # Verify duration is within Telegram limits
        duration = converter.get_audio_duration(output_path)
        assert duration <= 60  # Telegram max ~1 minute
    
    def test_convert_for_telegram_long_audio(self, temp_dir, long_wav_file):
        """Test converting long audio (>1 minute) - should be truncated."""
        converter = TelegramAudioConverter()
        output_path = os.path.join(temp_dir, "telegram_output.ogg")
        
        result = converter.convert_for_telegram(long_wav_file, output_path)
        
        assert result is True
        assert os.path.exists(output_path)
        
        # Verify duration is truncated to Telegram limit
        duration = converter.get_audio_duration(output_path)
        assert duration <= 60  # Should be truncated to ~60 seconds
    
    def test_optimize_audio_quality(self, temp_dir, sample_wav_file):
        """Test audio quality optimization."""
        converter = TelegramAudioConverter()
        output_path = os.path.join(temp_dir, "optimized.ogg")
        
        result = converter.convert_for_telegram(
            sample_wav_file, 
            output_path,
            bitrate=64000  # Lower bitrate for smaller file
        )
        
        assert result is True
        assert os.path.exists(output_path)
        
        # File should be reasonably sized
        file_size = os.path.getsize(output_path)
        assert file_size > 0
        assert file_size < 500000  # Should be less than 500KB for 1 second
    
    def test_compress_audio(self, temp_dir, sample_wav_file):
        """Test audio compression."""
        converter = TelegramAudioConverter()
        output_path = os.path.join(temp_dir, "compressed.ogg")
        
        result = converter.convert_for_telegram(
            sample_wav_file,
            output_path,
            compress=True
        )
        
        assert result is True
        assert os.path.exists(output_path)
    
    def test_handle_pcm_input(self, temp_dir):
        """Test handling PCM raw audio input."""
        # Create a simple PCM file
        pcm_path = os.path.join(temp_dir, "test.pcm")
        sample_rate = 16000
        duration = 1
        num_samples = sample_rate * duration
        
        with open(pcm_path, 'wb') as f:
            for i in range(num_samples):
                # Generate simple PCM data
                value = int(32767 * 0.3 * (i % 100) / 100)
                f.write(struct.pack('<h', value))
        
        converter = TelegramAudioConverter()
        output_path = os.path.join(temp_dir, "pcm_output.ogg")
        
        # First convert PCM to WAV, then to OGG
        wav_path = os.path.join(temp_dir, "temp.wav")
        result = converter.convert_pcm_to_ogg(
            pcm_path,
            output_path,
            sample_rate=16000,
            channels=1,
            sample_width=2
        )
        
        assert result is True
        assert os.path.exists(output_path)
    
    def test_validate_output_format(self, temp_dir, sample_wav_file):
        """Test that output is valid OGG/OPUS format."""
        converter = TelegramAudioConverter()
        output_path = os.path.join(temp_dir, "output.ogg")
        
        converter.convert_for_telegram(sample_wav_file, output_path)
        
        # Verify file exists and has correct extension
        assert os.path.exists(output_path)
        assert output_path.endswith('.ogg') or output_path.endswith('.opus')
        
        # Verify file is not empty
        assert os.path.getsize(output_path) > 0
        
        # Try to get duration (this will fail if format is invalid)
        duration = converter.get_audio_duration(output_path)
        assert duration is not None
        assert duration > 0
