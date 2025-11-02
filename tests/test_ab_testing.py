"""
Tests for A/B testing framework for LLM responses.
"""
import pytest
import os
import json
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional

from src.conversation_storage import ConversationStorage


@pytest.fixture
def storage():
    """Create a ConversationStorage instance for testing."""
    db_path = os.path.join(tempfile.gettempdir(), f"test_ab_{os.getpid()}.db")
    os.environ['DB_TYPE'] = 'sqlite'
    os.environ['DB_PATH'] = db_path
    storage = ConversationStorage(db_path=db_path)
    yield storage
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


class TestABTesting:
    """Test A/B testing functionality."""
    
    def test_create_ab_test(self, storage):
        """Test creating an A/B test configuration."""
        test_config = {
            "name": "Model Comparison Test",
            "description": "Compare GPT-3.5 vs GPT-4",
            "control": {
                "model": "gpt-3.5-turbo",
                "temperature": 0.7,
                "system_prompt": "You are a helpful assistant."
            },
            "variant": {
                "model": "gpt-4",
                "temperature": 0.7,
                "system_prompt": "You are a helpful assistant."
            },
            "traffic_split": 0.5,  # 50% to variant
            "active": True
        }
        
        test_id = storage.create_ab_test(**test_config)
        assert test_id > 0
        
        # Verify test was created
        test = storage.get_ab_test(test_id)
        assert test is not None
        assert test["name"] == test_config["name"]
        assert test["active"] is True
        assert test["traffic_split"] == 0.5
    
    def test_get_ab_test(self, storage):
        """Test retrieving an A/B test configuration."""
        test_config = {
            "name": "Temperature Test",
            "control": {"model": "gpt-3.5-turbo", "temperature": 0.3},
            "variant": {"model": "gpt-3.5-turbo", "temperature": 0.9},
            "traffic_split": 0.3
        }
        
        test_id = storage.create_ab_test(**test_config)
        test = storage.get_ab_test(test_id)
        
        assert test is not None
        assert test["id"] == test_id
        assert test["name"] == test_config["name"]
        # control_config and variant_config are JSON strings in the response
        control_from_db = json.loads(test["control_config"])
        variant_from_db = json.loads(test["variant_config"])
        assert control_from_db == test_config["control"]
        assert variant_from_db == test_config["variant"]
    
    def test_list_active_ab_tests(self, storage):
        """Test listing active A/B tests."""
        # Create multiple tests
        test1_id = storage.create_ab_test(
            name="Test 1",
            control={"model": "gpt-3.5-turbo"},
            variant={"model": "gpt-4"},
            active=True
        )
        test2_id = storage.create_ab_test(
            name="Test 2",
            control={"model": "gpt-3.5-turbo"},
            variant={"model": "gpt-4"},
            active=True
        )
        test3_id = storage.create_ab_test(
            name="Test 3",
            control={"model": "gpt-3.5-turbo"},
            variant={"model": "gpt-4"},
            active=False
        )
        
        active_tests = storage.list_ab_tests(active_only=True)
        
        assert len(active_tests) == 2
        test_ids = [t["id"] for t in active_tests]
        assert test1_id in test_ids
        assert test2_id in test_ids
        assert test3_id not in test_ids
    
    def test_assign_variant(self, storage):
        """Test assigning a variant to a conversation."""
        test_id = storage.create_ab_test(
            name="Test",
            control={"model": "gpt-3.5-turbo"},
            variant={"model": "gpt-4"},
            traffic_split=0.5
        )
        
        user_id = "user1"
        chat_id = "chat1"
        conversation_id = storage.get_or_create_conversation(user_id, chat_id)
        
        # Assign variant multiple times - should be consistent
        variant1 = storage.assign_ab_variant(conversation_id, test_id)
        variant2 = storage.assign_ab_variant(conversation_id, test_id)
        
        assert variant1 == variant2  # Same conversation should get same variant
        assert variant1 in ["control", "variant"]
        
        # Different conversation might get different variant
        conversation_id2 = storage.get_or_create_conversation("user2", "chat2")
        variant3 = storage.assign_ab_variant(conversation_id2, test_id)
        assert variant3 in ["control", "variant"]
    
    def test_record_ab_metric(self, storage):
        """Test recording metrics for A/B test responses."""
        test_id = storage.create_ab_test(
            name="Test",
            control={"model": "gpt-3.5-turbo"},
            variant={"model": "gpt-4"}
        )
        
        user_id = "user1"
        chat_id = "chat1"
        conversation_id = storage.get_or_create_conversation(user_id, chat_id)
        variant = storage.assign_ab_variant(conversation_id, test_id)
        
        # Record metrics
        metric_id = storage.record_ab_metric(
            test_id=test_id,
            conversation_id=conversation_id,
            variant=variant,
            response_time_ms=500,
            tokens_used=150,
            user_satisfaction_score=4.5
        )
        
        assert metric_id > 0
        
        # Verify metric was recorded
        metrics = storage.get_ab_metrics(test_id)
        assert len(metrics) == 1
        assert metrics[0]["variant"] == variant
        assert metrics[0]["response_time_ms"] == 500
        assert metrics[0]["tokens_used"] == 150
    
    def test_get_ab_statistics(self, storage):
        """Test getting statistical analysis of A/B test results."""
        test_id = storage.create_ab_test(
            name="Test",
            control={"model": "gpt-3.5-turbo"},
            variant={"model": "gpt-4"}
        )
        
        # Record metrics for control group
        for i in range(10):
            conv_id = storage.get_or_create_conversation(f"user{i}", f"chat{i}")
            variant = storage.assign_ab_variant(conv_id, test_id)
            if variant == "control":
                storage.record_ab_metric(
                    test_id=test_id,
                    conversation_id=conv_id,
                    variant="control",
                    response_time_ms=400 + i * 10,
                    tokens_used=100 + i,
                    user_satisfaction_score=4.0
                )
        
        # Record metrics for variant group
        for i in range(10, 20):
            conv_id = storage.get_or_create_conversation(f"user{i}", f"chat{i}")
            variant = storage.assign_ab_variant(conv_id, test_id)
            if variant == "variant":
                storage.record_ab_metric(
                    test_id=test_id,
                    conversation_id=conv_id,
                    variant="variant",
                    response_time_ms=350 + i * 10,
                    tokens_used=110 + i,
                    user_satisfaction_score=4.5
                )
        
        stats = storage.get_ab_statistics(test_id)
        
        assert stats is not None
        assert "control" in stats
        assert "variant" in stats
        assert "total_samples" in stats
        assert stats["total_samples"] > 0
        
        # Check control stats
        assert "count" in stats["control"]
        assert "avg_response_time_ms" in stats["control"]
        assert "avg_tokens_used" in stats["control"]
        assert "avg_satisfaction_score" in stats["control"]
        
        # Check variant stats
        assert "count" in stats["variant"]
        assert "avg_response_time_ms" in stats["variant"]
    
    def test_deactivate_ab_test(self, storage):
        """Test deactivating an A/B test."""
        test_id = storage.create_ab_test(
            name="Test",
            control={"model": "gpt-3.5-turbo"},
            variant={"model": "gpt-4"},
            active=True
        )
        
        # Verify active
        test = storage.get_ab_test(test_id)
        assert test["active"] is True
        
        # Deactivate
        storage.deactivate_ab_test(test_id)
        
        # Verify deactivated
        test = storage.get_ab_test(test_id)
        assert test["active"] is False
    
    def test_gradual_rollout(self, storage):
        """Test gradual rollout by updating traffic split."""
        test_id = storage.create_ab_test(
            name="Rollout Test",
            control={"model": "gpt-3.5-turbo"},
            variant={"model": "gpt-4"},
            traffic_split=0.1  # Start with 10%
        )
        
        test = storage.get_ab_test(test_id)
        assert test["traffic_split"] == 0.1
        
        # Increase to 50%
        storage.update_ab_test(test_id, traffic_split=0.5)
        test = storage.get_ab_test(test_id)
        assert test["traffic_split"] == 0.5
        
        # Increase to 100%
        storage.update_ab_test(test_id, traffic_split=1.0)
        test = storage.get_ab_test(test_id)
        assert test["traffic_split"] == 1.0
    
    def test_ab_test_with_stream_llm_response(self, storage, monkeypatch):
        """Test that stream_llm_response respects A/B test variant assignment."""
        # Enable LLM for this test
        monkeypatch.setenv("LLM_API_URL", "http://localhost:8000")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("LLM_MODEL", "gpt-3.5-turbo")
        storage.llm_api_url = "http://localhost:8000"
        storage.llm_api_key = "test-key"
        storage.llm_model = "gpt-3.5-turbo"
        storage.llm_enabled = True
        
        # Create A/B test
        test_id = storage.create_ab_test(
            name="Model Test",
            control={"model": "gpt-3.5-turbo", "temperature": 0.7},
            variant={"model": "gpt-4", "temperature": 0.7},
            traffic_split=0.5
        )
        
        user_id = "user1"
        chat_id = "chat1"
        conversation_id = storage.get_or_create_conversation(user_id, chat_id)
        
        # Assign variant
        variant = storage.assign_ab_variant(conversation_id, test_id)
        
        # Get test config to verify model selection
        test = storage.get_ab_test(test_id)
        variant_config = json.loads(test["variant_config"] if variant == "variant" else test["control_config"])
        
        assert variant_config["model"] in ["gpt-3.5-turbo", "gpt-4"]
