"""
Tests for cost tracking functionality.
"""
import pytest
import os
import tempfile
from datetime import datetime, timedelta
from src.cost_tracking import CostTracker, ServiceType
from src.conversation_storage import ConversationStorage


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    os.unlink(path)
    
    # Use PostgreSQL test database if available, otherwise SQLite
    db_type = os.getenv("DB_TYPE", "sqlite").lower()
    if db_type == "postgresql":
        # Use test database connection
        storage = ConversationStorage()
    else:
        storage = ConversationStorage(db_path=path)
    
    yield storage
    
    # Cleanup
    if db_type == "sqlite" and os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def cost_tracker(temp_db):
    """Create a cost tracker instance."""
    return CostTracker(db_path=temp_db.db_path if hasattr(temp_db, 'db_path') else None)


class TestCostTracker:
    """Test cost tracking functionality."""
    
    def test_record_stt_cost(self, cost_tracker, temp_db):
        """Test recording STT costs."""
        user_id = "user123"
        chat_id = "chat456"
        
        # Create conversation
        conversation_id = temp_db.get_or_create_conversation(user_id, chat_id)
        
        # Record STT cost
        cost_id = cost_tracker.record_cost(
            service_type=ServiceType.STT,
            user_id=user_id,
            conversation_id=conversation_id,
            cost=0.006,  # $0.006 per minute
            tokens=None,
            duration_seconds=60,  # 1 minute
            metadata={"model": "google", "audio_length": 60}
        )
        
        assert cost_id is not None
        assert cost_id > 0
    
    def test_record_llm_cost(self, cost_tracker, temp_db):
        """Test recording LLM costs."""
        user_id = "user123"
        chat_id = "chat456"
        
        conversation_id = temp_db.get_or_create_conversation(user_id, chat_id)
        
        # Record LLM cost
        cost_id = cost_tracker.record_cost(
            service_type=ServiceType.LLM,
            user_id=user_id,
            conversation_id=conversation_id,
            cost=0.002,
            tokens=1500,  # 500 input + 1000 output tokens
            metadata={"model": "gpt-3.5-turbo", "input_tokens": 500, "output_tokens": 1000}
        )
        
        assert cost_id is not None
    
    def test_record_tts_cost(self, cost_tracker, temp_db):
        """Test recording TTS costs."""
        user_id = "user123"
        chat_id = "chat456"
        
        conversation_id = temp_db.get_or_create_conversation(user_id, chat_id)
        
        # Record TTS cost
        cost_id = cost_tracker.record_cost(
            service_type=ServiceType.TTS,
            user_id=user_id,
            conversation_id=conversation_id,
            cost=0.015,  # $0.015 per 1000 characters
            tokens=2000,  # 2000 characters
            metadata={"model": "tts-1", "characters": 2000}
        )
        
        assert cost_id is not None
    
    def test_get_costs_for_user(self, cost_tracker, temp_db):
        """Test getting costs for a specific user."""
        user_id = "user123"
        chat_id = "chat456"
        
        conversation_id = temp_db.get_or_create_conversation(user_id, chat_id)
        
        # Record multiple costs
        cost_tracker.record_cost(
            ServiceType.LLM, user_id, conversation_id, 0.002, tokens=1000
        )
        cost_tracker.record_cost(
            ServiceType.STT, user_id, conversation_id, 0.006, duration_seconds=60
        )
        cost_tracker.record_cost(
            ServiceType.TTS, user_id, conversation_id, 0.015, tokens=2000
        )
        
        # Get costs for user
        costs = cost_tracker.get_costs_for_user(user_id)
        
        assert len(costs) == 3
        total = sum(c['cost'] for c in costs)
        assert abs(total - 0.023) < 0.0001  # Allow floating point precision
    
    def test_get_costs_for_conversation(self, cost_tracker, temp_db):
        """Test getting costs for a specific conversation."""
        user_id = "user123"
        chat_id = "chat456"
        
        conversation_id = temp_db.get_or_create_conversation(user_id, chat_id)
        
        # Record costs
        cost_tracker.record_cost(
            ServiceType.LLM, user_id, conversation_id, 0.002, tokens=1000
        )
        cost_tracker.record_cost(
            ServiceType.STT, user_id, conversation_id, 0.006, duration_seconds=60
        )
        
        # Get costs for conversation
        costs = cost_tracker.get_costs_for_conversation(conversation_id)
        
        assert len(costs) == 2
        total = sum(c['cost'] for c in costs)
        assert abs(total - 0.008) < 0.0001
    
    def test_get_total_cost_for_user(self, cost_tracker, temp_db):
        """Test getting total cost for a user."""
        user_id = "user123"
        chat_id = "chat456"
        
        conversation_id = temp_db.get_or_create_conversation(user_id, chat_id)
        
        # Record multiple costs
        cost_tracker.record_cost(
            ServiceType.LLM, user_id, conversation_id, 0.002, tokens=1000
        )
        cost_tracker.record_cost(
            ServiceType.LLM, user_id, conversation_id, 0.003, tokens=1500
        )
        
        # Get total cost
        total = cost_tracker.get_total_cost_for_user(user_id)
        
        assert abs(total - 0.005) < 0.0001
    
    def test_generate_billing_report(self, cost_tracker, temp_db):
        """Test generating billing report."""
        user_id = "user123"
        chat_id = "chat456"
        
        conversation_id = temp_db.get_or_create_conversation(user_id, chat_id)
        
        # Record costs for different services
        cost_tracker.record_cost(
            ServiceType.LLM, user_id, conversation_id, 0.002, tokens=1000,
            metadata={"model": "gpt-3.5-turbo"}
        )
        cost_tracker.record_cost(
            ServiceType.STT, user_id, conversation_id, 0.006, duration_seconds=60,
            metadata={"model": "google"}
        )
        cost_tracker.record_cost(
            ServiceType.TTS, user_id, conversation_id, 0.015, tokens=2000,
            metadata={"model": "tts-1"}
        )
        
        # Generate report
        report = cost_tracker.generate_billing_report(user_id)
        
        assert report['user_id'] == user_id
        assert report['total_cost'] > 0
        assert len(report['service_breakdown']) == 3
        assert 'LLM' in report['service_breakdown']
        assert 'STT' in report['service_breakdown']
        assert 'TTS' in report['service_breakdown']
    
    def test_get_costs_by_date_range(self, cost_tracker, temp_db):
        """Test getting costs by date range."""
        user_id = "user123"
        chat_id = "chat456"
        
        conversation_id = temp_db.get_or_create_conversation(user_id, chat_id)
        
        # Record costs
        cost_tracker.record_cost(
            ServiceType.LLM, user_id, conversation_id, 0.002, tokens=1000
        )
        
        # Get costs for today
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)
        tomorrow = today + timedelta(days=1)
        
        costs = cost_tracker.get_costs_by_date_range(user_id, yesterday, tomorrow)
        
        assert len(costs) >= 1
    
    def test_calculate_llm_cost(self, cost_tracker):
        """Test calculating LLM cost from usage."""
        # Test GPT-3.5-turbo pricing
        cost = cost_tracker.calculate_llm_cost(
            model="gpt-3.5-turbo",
            input_tokens=1000,
            output_tokens=500
        )
        
        # GPT-3.5-turbo: $0.0015 per 1K input tokens, $0.002 per 1K output tokens
        expected = (1000 / 1000) * 0.0015 + (500 / 1000) * 0.002
        assert abs(cost - expected) < 0.0001
    
    def test_calculate_stt_cost(self, cost_tracker):
        """Test calculating STT cost from usage."""
        # Google STT: $0.006 per minute
        cost = cost_tracker.calculate_stt_cost(
            provider="google",
            duration_seconds=120  # 2 minutes
        )
        
        expected = (120 / 60) * 0.006
        assert abs(cost - expected) < 0.0001
    
    def test_calculate_tts_cost(self, cost_tracker):
        """Test calculating TTS cost from usage."""
        # OpenAI TTS: $0.015 per 1000 characters
        cost = cost_tracker.calculate_tts_cost(
            provider="openai",
            characters=3000
        )
        
        expected = (3000 / 1000) * 0.015
        assert abs(cost - expected) < 0.0001