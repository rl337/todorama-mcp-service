"""
Tests for voice message quality scoring.
"""
import pytest
import os
import tempfile
import wave
import struct
import numpy as np
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from voice_quality import VoiceQualityScorer, VoiceQualityError


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    temp_path = tempfile.mkdtemp()
    yield temp_path
    import shutil
    shutil.rmtree(temp_path)


@pytest.fixture
def high_quality_wav(temp_dir):
    """Create a high quality WAV file (clear, loud, no noise)."""
    wav_path = os.path.join(temp_dir, "high_quality.wav")
    sample_rate = 16000
    duration = 2  # 2 seconds
    frequency = 440  # A4 note (speech-like frequency)
    num_samples = sample_rate * duration
    
    with wave.open(wav_path, 'w') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        
        # Generate a clear sine wave with good amplitude
        for i in range(num_samples):
            value = int(20000 * np.sin(2 * np.pi * frequency * i / sample_rate))
            wav_file.writeframes(struct.pack('<h', value))
    
    return wav_path


@pytest.fixture
def low_volume_wav(temp_dir):
    """Create a low volume WAV file."""
    wav_path = os.path.join(temp_dir, "low_volume.wav")
    sample_rate = 16000
    duration = 2
    frequency = 440
    num_samples = sample_rate * duration
    
    with wave.open(wav_path, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        # Generate very quiet audio
        for i in range(num_samples):
            value = int(500 * np.sin(2 * np.pi * frequency * i / sample_rate))  # Much quieter
            wav_file.writeframes(struct.pack('<h', value))
    
    return wav_path


@pytest.fixture
def noisy_wav(temp_dir):
    """Create a noisy WAV file (signal with background noise)."""
    wav_path = os.path.join(temp_dir, "noisy.wav")
    sample_rate = 16000
    duration = 2
    frequency = 440
    num_samples = sample_rate * duration
    
    with wave.open(wav_path, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        # Generate signal with noise
        np.random.seed(42)  # For reproducible tests
        for i in range(num_samples):
            signal = 10000 * np.sin(2 * np.pi * frequency * i / sample_rate)
            noise = np.random.normal(0, 3000)  # Background noise
            value = int(np.clip(signal + noise, -32768, 32767))
            wav_file.writeframes(struct.pack('<h', value))
    
    return wav_path


@pytest.fixture
def unclear_wav(temp_dir):
    """Create an unclear WAV file (multiple overlapping frequencies, distortion)."""
    wav_path = os.path.join(temp_dir, "unclear.wav")
    sample_rate = 16000
    duration = 2
    num_samples = sample_rate * duration
    
    with wave.open(wav_path, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        # Generate distorted audio with multiple conflicting frequencies
        np.random.seed(42)
        for i in range(num_samples):
            # Multiple overlapping frequencies create unclear audio
            value = int(10000 * (
                0.3 * np.sin(2 * np.pi * 200 * i / sample_rate) +
                0.3 * np.sin(2 * np.pi * 600 * i / sample_rate) +
                0.3 * np.sin(2 * np.pi * 1000 * i / sample_rate) +
                0.1 * np.random.normal(0, 2000)
            ))
            value = int(np.clip(value, -32768, 32767))
            wav_file.writeframes(struct.pack('<h', value))
    
    return wav_path


class TestVoiceQualityScorer:
    """Test voice quality scorer functionality."""
    
    def test_score_high_quality_audio(self, high_quality_wav):
        """Test scoring high quality audio."""
        scorer = VoiceQualityScorer()
        score = scorer.score_voice_message(high_quality_wav)
        
        assert score is not None
        assert "overall_score" in score
        assert "volume_score" in score
        assert "clarity_score" in score
        assert "noise_score" in score
        assert "feedback" in score
        assert "suggestions" in score
        
        # High quality should have good scores
        assert score["overall_score"] >= 70  # Should be good
        assert score["volume_score"] >= 70  # Good volume
        assert score["clarity_score"] >= 70  # Clear audio
        assert score["noise_score"] >= 70  # Low noise
    
    def test_score_low_volume_audio(self, low_volume_wav):
        """Test scoring low volume audio."""
        scorer = VoiceQualityScorer()
        score = scorer.score_voice_message(low_volume_wav)
        
        assert score is not None
        # Low volume should be detected
        assert score["volume_score"] < 50
        assert "volume" in score["feedback"].lower() or "quiet" in score["feedback"].lower()
        
        # Should suggest increasing volume
        suggestions = " ".join(score["suggestions"]).lower()
        assert "volume" in suggestions or "louder" in suggestions or "speak" in suggestions
    
    def test_score_noisy_audio(self, noisy_wav):
        """Test scoring noisy audio."""
        scorer = VoiceQualityScorer()
        score = scorer.score_voice_message(noisy_wav)
        
        assert score is not None
        # Noise should be detected
        assert score["noise_score"] < 70  # Noise reduces score
        
        # Should mention noise in feedback
        feedback_lower = score["feedback"].lower()
        suggestions_lower = " ".join(score["suggestions"]).lower()
        assert ("noise" in feedback_lower or 
                "background" in feedback_lower or
                "noise" in suggestions_lower or
                "quiet" in suggestions_lower)
    
    def test_score_unclear_audio(self, unclear_wav):
        """Test scoring unclear audio."""
        scorer = VoiceQualityScorer()
        score = scorer.score_voice_message(unclear_wav)
        
        assert score is not None
        # Clarity should be lower
        assert score["clarity_score"] < 70
        
        # Should suggest clearer speech
        suggestions_lower = " ".join(score["suggestions"]).lower()
        assert ("clear" in suggestions_lower or 
                "speak" in suggestions_lower or
                "enunciate" in suggestions_lower)
    
    def test_score_invalid_file(self, temp_dir):
        """Test error handling for invalid file."""
        scorer = VoiceQualityScorer()
        
        with pytest.raises(VoiceQualityError):
            scorer.score_voice_message("nonexistent.wav")
    
    def test_score_empty_file(self, temp_dir):
        """Test error handling for empty file."""
        empty_wav = os.path.join(temp_dir, "empty.wav")
        
        # Create empty file
        with open(empty_wav, 'w') as f:
            pass
        
        scorer = VoiceQualityScorer()
        
        # Should handle gracefully
        with pytest.raises(VoiceQualityError):
            scorer.score_voice_message(empty_wav)
    
    def test_score_returns_all_required_fields(self, high_quality_wav):
        """Test that score returns all required fields."""
        scorer = VoiceQualityScorer()
        score = scorer.score_voice_message(high_quality_wav)
        
        required_fields = [
            "overall_score",
            "volume_score",
            "clarity_score",
            "noise_score",
            "feedback",
            "suggestions"
        ]
        
        for field in required_fields:
            assert field in score, f"Missing required field: {field}"
    
    def test_score_suggestions_is_list(self, high_quality_wav):
        """Test that suggestions is a list."""
        scorer = VoiceQualityScorer()
        score = scorer.score_voice_message(high_quality_wav)
        
        assert isinstance(score["suggestions"], list)
        assert len(score["suggestions"]) > 0
    
    def test_score_values_are_in_range(self, high_quality_wav):
        """Test that all scores are in valid range (0-100)."""
        scorer = VoiceQualityScorer()
        score = scorer.score_voice_message(high_quality_wav)
        
        score_fields = ["overall_score", "volume_score", "clarity_score", "noise_score"]
        for field in score_fields:
            assert 0 <= score[field] <= 100, f"{field} should be between 0 and 100, got {score[field]}"
