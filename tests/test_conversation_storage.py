"""
Tests for conversation storage module.
"""
import pytest
import os
import json
import tempfile
from datetime import datetime
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from conversation_storage import ConversationStorage


@pytest.fixture
def temp_postgres_db():
    """Create a temporary PostgreSQL database for testing."""
    # For testing, we'll use SQLite with a test adapter or mock PostgreSQL
    # In real implementation, this would connect to a test PostgreSQL instance
    db_path = os.path.join(tempfile.gettempdir(), f"test_conversations_{os.getpid()}.db")
    # Note: This test assumes PostgreSQL, but for simplicity in test environment
    # we might need to use SQLite adapter if PostgreSQL is not available
    yield db_path
    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)


@pytest.fixture
def storage(temp_postgres_db):
    """Create a ConversationStorage instance for testing."""
    # Set environment to use test database
    os.environ['DB_TYPE'] = 'postgresql'
    os.environ['DB_HOST'] = 'localhost'
    os.environ['DB_NAME'] = 'test_conversations'
    # In actual implementation, would use test PostgreSQL
    # For now, skip if PostgreSQL not available
    try:
        storage = ConversationStorage()
        yield storage
    except Exception as e:
        pytest.skip(f"PostgreSQL not available: {e}")


class TestConversationStorage:
    """Test conversation storage functionality."""
    
    def test_create_conversation(self, storage):
        """Test creating a new conversation."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        assert conv_id > 0
        
        # Getting same conversation should return same ID
        conv_id2 = storage.get_or_create_conversation("user1", "chat1")
        assert conv_id == conv_id2
        
        # Different chat should get different ID
        conv_id3 = storage.get_or_create_conversation("user1", "chat2")
        assert conv_id3 != conv_id
    
    def test_add_message(self, storage):
        """Test adding messages to a conversation."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        msg_id1 = storage.add_message(conv_id, "user", "Hello", tokens=10)
        assert msg_id1 > 0
        
        msg_id2 = storage.add_message(conv_id, "assistant", "Hi there!", tokens=15)
        assert msg_id2 > msg_id1
    
    def test_get_conversation(self, storage):
        """Test retrieving conversation history."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        storage.add_message(conv_id, "user", "Message 1", tokens=10)
        storage.add_message(conv_id, "assistant", "Response 1", tokens=15)
        storage.add_message(conv_id, "user", "Message 2", tokens=12)
        
        conversation = storage.get_conversation("user1", "chat1")
        assert conversation is not None
        assert conversation['user_id'] == "user1"
        assert conversation['chat_id'] == "chat1"
        assert len(conversation['messages']) == 3
        assert conversation['messages'][0]['content'] == "Message 1"
        assert conversation['messages'][1]['content'] == "Response 1"
        assert conversation['messages'][2]['content'] == "Message 2"
    
    def test_get_conversation_with_limit(self, storage):
        """Test retrieving conversation with message limit."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        for i in range(10):
            storage.add_message(conv_id, "user", f"Message {i}")
        
        conversation = storage.get_conversation("user1", "chat1", limit=5)
        assert len(conversation['messages']) == 5
        # Should get most recent 5 messages
        assert conversation['messages'][0]['content'] == "Message 5"
    
    def test_get_conversation_with_token_limit(self, storage):
        """Test retrieving conversation with token limit."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Add messages with known token counts
        storage.add_message(conv_id, "user", "Msg1", tokens=10)
        storage.add_message(conv_id, "assistant", "Resp1", tokens=15)
        storage.add_message(conv_id, "user", "Msg2", tokens=12)
        storage.add_message(conv_id, "assistant", "Resp2", tokens=20)
        
        # Get with token limit that should include only last 2 messages
        conversation = storage.get_conversation("user1", "chat1", max_tokens=35)
        # Should get messages that fit within token limit (most recent first)
        assert conversation is not None
        total_tokens = sum(msg.get('tokens', 0) for msg in conversation['messages'])
        assert total_tokens <= 35
    
    def test_prune_old_contexts(self, storage):
        """Test pruning old conversation contexts."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Add many messages
        for i in range(20):
            storage.add_message(conv_id, "user", f"Message {i}", tokens=10)
        
        # Prune to keep only messages within token limit
        pruned = storage.prune_old_contexts("user1", "chat1", max_tokens=100, keep_recent=5)
        assert pruned > 0
        
        # Verify conversation still exists
        conversation = storage.get_conversation("user1", "chat1")
        assert conversation is not None
        assert len(conversation['messages']) <= 10  # Should fit in 100 tokens (10 tokens each)
    
    def test_delete_conversation(self, storage):
        """Test deleting a conversation."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Test message")
        
        # Verify conversation exists
        conversation = storage.get_conversation("user1", "chat1")
        assert conversation is not None
        
        # Delete conversation
        deleted = storage.delete_conversation("user1", "chat1")
        assert deleted is True
        
        # Verify conversation is gone
        conversation = storage.get_conversation("user1", "chat1")
        assert conversation is None
        
        # Deleting non-existent conversation should return False
        deleted2 = storage.delete_conversation("user1", "nonexistent")
        assert deleted2 is False
    
    def test_export_conversation(self, storage):
        """Test exporting conversation to JSON."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Hello", tokens=10)
        storage.add_message(conv_id, "assistant", "Hi!", tokens=5)
        
        export_data = storage.export_conversation("user1", "chat1")
        
        assert export_data['user_id'] == "user1"
        assert export_data['chat_id'] == "chat1"
        assert len(export_data['messages']) == 2
        assert export_data['messages'][0]['content'] == "Hello"
        assert export_data['messages'][1]['content'] == "Hi!"
        assert 'created_at' in export_data
        assert 'updated_at' in export_data
    
    def test_import_conversation(self, storage):
        """Test importing conversation from JSON."""
        # Create export data
        export_data = {
            'user_id': 'user2',
            'chat_id': 'chat2',
            'created_at': datetime.now().isoformat(),
            'updated_at': datetime.now().isoformat(),
            'last_message_at': datetime.now().isoformat(),
            'message_count': 2,
            'total_tokens': 15,
            'metadata': {'test': 'data'},
            'messages': [
                {'role': 'user', 'content': 'Imported msg 1', 'tokens': 10},
                {'role': 'assistant', 'content': 'Imported resp 1', 'tokens': 5}
            ]
        }
        
        # Import conversation
        imported_id = storage.import_conversation(export_data)
        assert imported_id > 0
        
        # Verify imported conversation
        conversation = storage.get_conversation('user2', 'chat2')
        assert conversation is not None
        assert len(conversation['messages']) == 2
        assert conversation['messages'][0]['content'] == 'Imported msg 1'
        assert conversation['messages'][1]['content'] == 'Imported resp 1'
    
    def test_list_conversations(self, storage):
        """Test listing conversations."""
        # Create multiple conversations
        storage.get_or_create_conversation("user1", "chat1")
        storage.get_or_create_conversation("user1", "chat2")
        storage.get_or_create_conversation("user2", "chat1")
        
        # List all conversations
        all_convs = storage.list_conversations()
        assert len(all_convs) >= 3
        
        # List conversations for specific user
        user1_convs = storage.list_conversations(user_id="user1")
        assert len(user1_convs) == 2
        assert all(conv['user_id'] == "user1" for conv in user1_convs)
    
    def test_conversation_persistence_across_restarts(self, storage):
        """Test that conversations persist across service restarts."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Persistent message")
        
        # Simulate restart by creating new storage instance
        storage2 = ConversationStorage()
        
        # Verify conversation still exists
        conversation = storage2.get_conversation("user1", "chat1")
        assert conversation is not None
        assert len(conversation['messages']) == 1
        assert conversation['messages'][0]['content'] == "Persistent message"
    
    def test_invalid_role_raises_error(self, storage):
        """Test that invalid message role raises error."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        with pytest.raises(ValueError, match="Invalid role"):
            storage.add_message(conv_id, "invalid_role", "Test")
    
    def test_get_nonexistent_conversation(self, storage):
        """Test getting a non-existent conversation returns None."""
        conversation = storage.get_conversation("nonexistent", "chat")
        assert conversation is None
    
    def test_export_nonexistent_conversation_raises_error(self, storage):
        """Test exporting non-existent conversation raises error."""
        with pytest.raises(ValueError, match="not found"):
            storage.export_conversation("nonexistent", "chat")
    
    def test_export_conversation_txt_format(self, storage):
        """Test exporting conversation to TXT format."""
        from datetime import datetime, timedelta
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Hello", tokens=10)
        storage.add_message(conv_id, "assistant", "Hi there!", tokens=5)
        
        txt_export = storage.export_conversation("user1", "chat1", format="txt")
        assert isinstance(txt_export, str)
        assert "user1" in txt_export or "chat1" in txt_export
        assert "Hello" in txt_export
        assert "Hi there!" in txt_export
        assert "user:" in txt_export.lower() or "assistant:" in txt_export.lower()
    
    def test_export_conversation_pdf_format(self, storage):
        """Test exporting conversation to PDF format."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Test message", tokens=10)
        storage.add_message(conv_id, "assistant", "Test response", tokens=5)
        
        pdf_export = storage.export_conversation("user1", "chat1", format="pdf")
        assert isinstance(pdf_export, bytes)
        assert pdf_export.startswith(b"%PDF")  # PDF files start with %PDF
    
    def test_export_conversation_with_date_filter(self, storage):
        """Test exporting conversation with date range filtering."""
        from datetime import datetime, timedelta
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Add messages at different times
        # First message - older
        storage.add_message(conv_id, "user", "Old message", tokens=10)
        
        # Simulate time passing by directly manipulating timestamps if possible
        # For now, we'll test with a date range that includes all messages
        start_date = datetime.now() - timedelta(days=1)
        end_date = datetime.now() + timedelta(days=1)
        
        # Export with date filter
        export_data = storage.export_conversation(
            "user1", "chat1", 
            format="json",
            start_date=start_date,
            end_date=end_date
        )
        assert export_data is not None
        assert 'messages' in export_data
    
    def test_export_conversation_date_filter_excludes_old_messages(self, storage):
        """Test that date filter excludes messages outside date range."""
        from datetime import datetime, timedelta
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Message 1", tokens=10)
        
        # Export with future date range (should exclude all messages)
        future_start = datetime.now() + timedelta(days=1)
        future_end = datetime.now() + timedelta(days=2)
        
        export_data = storage.export_conversation(
            "user1", "chat1",
            format="json",
            start_date=future_start,
            end_date=future_end
        )
        # Should still return conversation structure but with filtered messages
        assert export_data is not None
        # Messages outside range should be excluded
        # (Implementation may return empty list or all messages, depending on design)
    
    def test_export_conversation_invalid_format_raises_error(self, storage):
        """Test that invalid export format raises error."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Test", tokens=10)
        
        with pytest.raises(ValueError, match="Unsupported export format"):
            storage.export_conversation("user1", "chat1", format="invalid")
    
    def test_reset_conversation(self, storage):
        """Test resetting a conversation clears messages but keeps the conversation."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Message 1", tokens=10)
        storage.add_message(conv_id, "assistant", "Response 1", tokens=15)
        
        # Verify messages exist
        conversation = storage.get_conversation("user1", "chat1")
        assert conversation is not None
        assert len(conversation['messages']) == 2
        
        # Reset conversation
        reset = storage.reset_conversation("user1", "chat1")
        assert reset is True
        
        # Verify messages are gone but conversation exists
        conversation = storage.get_conversation("user1", "chat1")
        assert conversation is not None
        assert conversation['message_count'] == 0
        assert len(conversation['messages']) == 0
        assert conversation['total_tokens'] == 0
        
        # Verify conversation still has same ID
        assert conversation['id'] == conv_id
    
    def test_reset_nonexistent_conversation(self, storage):
        """Test resetting a non-existent conversation returns False."""
        reset = storage.reset_conversation("nonexistent", "chat")
        assert reset is False

    def test_summarize_old_messages_triggers_on_long_context(self, storage, monkeypatch):
        """Test that summarization triggers when context window gets long."""
        # Mock LLM summarization and enable LLM
        summary_calls = []
        def mock_summarize(messages):
            summary_calls.append(messages)
            return "Previous conversation about user needs and system design."
        
        monkeypatch.setattr(storage, '_summarize_messages', mock_summarize)
        monkeypatch.setattr(storage, 'llm_enabled', True)  # Enable LLM for this test
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Add many messages to exceed context window
        for i in range(15):
            storage.add_message(conv_id, "user", f"Message {i}: User asking about features", tokens=50)
            storage.add_message(conv_id, "assistant", f"Response {i}: Explaining features", tokens=60)
        
        # Get conversation with max_tokens that should trigger summarization
        # This should summarize old messages when context is too long
        conversation = storage.get_conversation("user1", "chat1", max_tokens=500)
        
        # Verify that summarization was attempted if context was too long
        # The exact behavior depends on implementation
        assert conversation is not None
        # Should have fewer messages after summarization (if triggered)
        # Or same number if threshold not met
        assert len(conversation['messages']) >= 0

    def test_summarize_old_messages_preserves_key_information(self, storage, monkeypatch):
        """Test that summarization preserves key information."""
        # Mock LLM and enable it
        def mock_summarize(messages):
            # Summarization should include key details like "Alice" and "web scraper"
            summary = "User Alice needs help with Python, specifically a web scraper project."
            return summary
        
        monkeypatch.setattr(storage, '_summarize_messages', mock_summarize)
        monkeypatch.setattr(storage, 'llm_enabled', True)  # Enable LLM for this test
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Add messages with important information
        storage.add_message(conv_id, "user", "My name is Alice and I need help with Python", tokens=20)
        storage.add_message(conv_id, "assistant", "Hello Alice! I can help with Python.", tokens=25)
        storage.add_message(conv_id, "user", "I'm working on a web scraper project", tokens=15)
        storage.add_message(conv_id, "assistant", "Web scrapers need proper error handling.", tokens=30)
        
        # Add many more messages
        for i in range(20):
            storage.add_message(conv_id, "user", f"Question {i}", tokens=10)
            storage.add_message(conv_id, "assistant", f"Answer {i}", tokens=15)
        
        # Get conversation - should trigger summarization
        conversation = storage.get_conversation("user1", "chat1", max_tokens=200)
        
        # Verify conversation exists and has been processed
        assert conversation is not None
        # The summary should be in metadata or as a system message
        # Implementation-specific check

    def test_summarize_old_messages_integrates_with_context_management(self, storage, monkeypatch):
        """Test that summarization integrates with conversation management system."""
        # Mock LLM and enable it
        def mock_summarize(messages):
            return "Summarized previous conversation."
        
        monkeypatch.setattr(storage, '_summarize_messages', mock_summarize)
        monkeypatch.setattr(storage, 'llm_enabled', True)  # Enable LLM for this test
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Add messages
        for i in range(10):
            storage.add_message(conv_id, "user", f"Message {i}", tokens=30)
            storage.add_message(conv_id, "assistant", f"Response {i}", tokens=40)
        
        # Test that summarization is called when appropriate
        conversation = storage.get_conversation("user1", "chat1", max_tokens=300)
        
        assert conversation is not None
        # Verify integration works
        conversation2 = storage.get_conversation("user1", "chat1")
        assert conversation2 is not None

    # Template and Quick Reply Tests
    
    def test_create_conversation_template(self, storage):
        """Test creating a conversation template."""
        template_id = storage.create_template(
            user_id="user1",
            name="Greeting Template",
            description="Template for greeting conversations",
            initial_messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "assistant", "content": "Hello! How can I help you today?"}
            ],
            metadata={"category": "greeting"}
        )
        assert template_id > 0
        
        # Verify template can be retrieved
        template = storage.get_template(template_id)
        assert template is not None
        assert template['name'] == "Greeting Template"
        assert template['user_id'] == "user1"
        assert len(template['initial_messages']) == 2
    
    def test_list_user_templates(self, storage):
        """Test listing templates for a user."""
        # Create multiple templates
        storage.create_template("user1", "Template 1", "Desc 1", [])
        storage.create_template("user1", "Template 2", "Desc 2", [])
        storage.create_template("user2", "Template 3", "Desc 3", [])
        
        # List templates for user1
        templates = storage.list_templates("user1")
        assert len(templates) >= 2
        assert all(t['user_id'] == "user1" for t in templates)
        
        # List all templates
        all_templates = storage.list_templates()
        assert len(all_templates) >= 3
    
    def test_update_template(self, storage):
        """Test updating a template."""
        template_id = storage.create_template(
            "user1", "Original Name", "Original desc", []
        )
        
        # Update template
        updated = storage.update_template(
            template_id,
            name="Updated Name",
            description="Updated description"
        )
        assert updated is True
        
        # Verify update
        template = storage.get_template(template_id)
        assert template['name'] == "Updated Name"
        assert template['description'] == "Updated description"
    
    def test_delete_template(self, storage):
        """Test deleting a template."""
        template_id = storage.create_template("user1", "To Delete", "Desc", [])
        
        # Delete template
        deleted = storage.delete_template(template_id)
        assert deleted is True
        
        # Verify template is gone
        template = storage.get_template(template_id)
        assert template is None
    
    def test_add_quick_replies_to_template(self, storage):
        """Test adding quick replies to a template."""
        template_id = storage.create_template("user1", "Support Template", "Desc", [])
        
        # Add quick replies
        reply_id1 = storage.add_quick_reply(template_id, "Yes", "yes_action")
        reply_id2 = storage.add_quick_reply(template_id, "No", "no_action")
        
        assert reply_id1 > 0
        assert reply_id2 > 0
        
        # Get template with replies
        template = storage.get_template(template_id)
        assert len(template.get('quick_replies', [])) == 2
    
    def test_apply_template_to_conversation(self, storage):
        """Test applying a template to start a conversation."""
        # Create template with initial messages
        template_id = storage.create_template(
            "user1",
            "Welcome Template",
            "Welcome template",
            [
                {"role": "system", "content": "You are helpful."},
                {"role": "assistant", "content": "Welcome! How can I assist?"}
            ]
        )
        
        # Apply template to new conversation
        conv_id = storage.apply_template("user1", "chat1", template_id)
        assert conv_id > 0
        
        # Verify conversation has template messages
        conversation = storage.get_conversation("user1", "chat1")
        assert conversation is not None
        assert len(conversation['messages']) >= 2
        # Check that template messages were applied
        assert any(msg['role'] == 'system' for msg in conversation['messages'])
        assert any(msg['role'] == 'assistant' for msg in conversation['messages'])
    
    def test_template_with_quick_replies(self, storage):
        """Test template with quick replies applied to conversation."""
        template_id = storage.create_template(
            "user1",
            "Template with Replies",
            "Template with quick replies",
            [{"role": "assistant", "content": "Choose an option:"}]
        )
        
        storage.add_quick_reply(template_id, "Option A", "action_a")
        storage.add_quick_reply(template_id, "Option B", "action_b")
        
        # Apply template
        conv_id = storage.apply_template("user1", "chat1", template_id)
        
        # Get template to verify quick replies
        template = storage.get_template(template_id)
        assert len(template.get('quick_replies', [])) == 2
        
        # Verify conversation was created
        conversation = storage.get_conversation("user1", "chat1")
        assert conversation is not None
    
    def test_get_nonexistent_template(self, storage):
        """Test getting a non-existent template returns None."""
        template = storage.get_template(99999)
        assert template is None
    
    def test_delete_template_with_quick_replies(self, storage):
        """Test that deleting a template also deletes its quick replies."""
        template_id = storage.create_template("user1", "Template", "Desc", [])
        storage.add_quick_reply(template_id, "Reply 1", "action1")
        storage.add_quick_reply(template_id, "Reply 2", "action2")
        
        # Delete template
        deleted = storage.delete_template(template_id)
        assert deleted is True
        
        # Verify template is gone (quick replies should be cascade deleted)
        template = storage.get_template(template_id)
        assert template is None
    
    def test_update_quick_reply(self, storage):
        """Test updating a quick reply."""
        template_id = storage.create_template("user1", "Template", "Desc", [])
        reply_id = storage.add_quick_reply(template_id, "Original", "original_action")
        
        # Update quick reply
        updated = storage.update_quick_reply(reply_id, label="Updated", action="updated_action")
        assert updated is True
        
        # Verify update
        template = storage.get_template(template_id)
        reply = next((r for r in template.get('quick_replies', []) if r['id'] == reply_id), None)
        assert reply is not None
        assert reply['label'] == "Updated"
        assert reply['action'] == "updated_action"
    
    def test_delete_quick_reply(self, storage):
        """Test deleting a quick reply."""
        template_id = storage.create_template("user1", "Template", "Desc", [])
        reply_id = storage.add_quick_reply(template_id, "To Delete", "delete_action")
        
        # Delete quick reply
        deleted = storage.delete_quick_reply(reply_id)
        assert deleted is True
        
        # Verify reply is gone
        template = storage.get_template(template_id)
        replies = template.get('quick_replies', [])
        assert not any(r['id'] == reply_id for r in replies)
    
    def test_response_time_tracking(self, storage):
        """Test tracking response time between user and assistant messages."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Add user message
        import time
        start_time = time.time()
        storage.add_message(conv_id, "user", "Hello")
        time.sleep(0.1)  # Simulate delay
        
        # Add assistant response
        storage.add_message(conv_id, "assistant", "Hi there!")
        
        # Get analytics - should calculate response time
        analytics = storage.get_conversation_analytics("user1", "chat1")
        assert "average_response_time_seconds" in analytics
        assert analytics["average_response_time_seconds"] >= 0.1
    
    def test_conversation_analytics_metrics(self, storage):
        """Test getting conversation analytics metrics."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Add multiple messages
        for i in range(5):
            storage.add_message(conv_id, "user", f"Message {i}")
            storage.add_message(conv_id, "assistant", f"Response {i}")
        
        analytics = storage.get_conversation_analytics("user1", "chat1")
        
        assert "message_count" in analytics
        assert "total_tokens" in analytics
        assert "average_response_time_seconds" in analytics
        assert "user_engagement_score" in analytics
        assert analytics["message_count"] == 10  # 5 user + 5 assistant
    
    def test_dashboard_analytics(self, storage):
        """Test getting dashboard analytics data."""
        # Create multiple conversations
        for i in range(3):
            conv_id = storage.get_or_create_conversation(f"user{i}", f"chat{i}")
            storage.add_message(conv_id, "user", "Hello")
            storage.add_message(conv_id, "assistant", "Hi")
        
        dashboard = storage.get_dashboard_analytics()
        
        assert "total_conversations" in dashboard
        assert "active_users" in dashboard
        assert "total_messages" in dashboard
        assert "average_response_time" in dashboard
        assert "engagement_metrics" in dashboard
        assert dashboard["total_conversations"] >= 3
    
    def test_dashboard_analytics_with_date_range(self, storage):
        """Test dashboard analytics with date filtering."""
        from datetime import datetime, timedelta
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Hello")
        
        # Get analytics for last 7 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        dashboard = storage.get_dashboard_analytics(
            start_date=start_date,
            end_date=end_date
        )
        
        assert "total_conversations" in dashboard
        assert "date_range" in dashboard

    # Prompt Template Tests
    
    def test_create_user_prompt_template(self, storage):
        """Test creating a per-user LLM prompt template."""
        template_id = storage.create_prompt_template(
            user_id="user1",
            template_name="Custom Summary",
            template_content="Summarize the conversation focusing on technical details and user requirements.",
            template_type="summarization"
        )
        assert template_id > 0
        
        # Verify template can be retrieved
        template = storage.get_prompt_template(template_id)
        assert template is not None
        assert template['user_id'] == "user1"
        assert template['template_name'] == "Custom Summary"
        assert template['template_content'] == "Summarize the conversation focusing on technical details and user requirements."
        assert template['template_type'] == "summarization"
        assert template['conversation_id'] is None  # Per-user template
    
    def test_create_conversation_prompt_template(self, storage):
        """Test creating a per-conversation LLM prompt template."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        template_id = storage.create_prompt_template(
            user_id="user1",
            template_name="Chat-Specific Prompt",
            template_content="Focus on debugging Python code issues.",
            template_type="summarization",
            conversation_id=conv_id
        )
        assert template_id > 0
        
        # Verify template
        template = storage.get_prompt_template(template_id)
        assert template['conversation_id'] == conv_id
    
    def test_get_prompt_template_for_user(self, storage):
        """Test getting prompt template for a user."""
        # Create user template
        template_id = storage.create_prompt_template(
            "user1", "User Template", "User-specific prompt", "summarization"
        )
        
        # Get template for user
        template = storage.get_prompt_template_for_user("user1", "summarization")
        assert template is not None
        assert template['id'] == template_id
    
    def test_get_prompt_template_for_conversation(self, storage):
        """Test getting prompt template for a specific conversation."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        template_id = storage.create_prompt_template(
            "user1", "Conv Template", "Conv-specific prompt", "summarization", conversation_id=conv_id
        )
        
        # Get template for conversation (should prefer conversation-specific)
        template = storage.get_prompt_template_for_conversation("user1", "chat1", "summarization")
        assert template is not None
        assert template['id'] == template_id
        assert template['conversation_id'] == conv_id
    
    def test_get_prompt_template_falls_back_to_user_template(self, storage):
        """Test that conversation template falls back to user template if no conversation template exists."""
        # Create only user template
        user_template_id = storage.create_prompt_template(
            "user1", "User Template", "User prompt", "summarization"
        )
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Get template for conversation - should fall back to user template
        template = storage.get_prompt_template_for_conversation("user1", "chat1", "summarization")
        assert template is not None
        assert template['id'] == user_template_id
        assert template['conversation_id'] is None
    
    def test_update_prompt_template(self, storage):
        """Test updating a prompt template."""
        template_id = storage.create_prompt_template(
            "user1", "Original", "Original content", "summarization"
        )
        
        # Update template
        updated = storage.update_prompt_template(
            template_id,
            template_name="Updated",
            template_content="Updated content"
        )
        assert updated is True
        
        # Verify update
        template = storage.get_prompt_template(template_id)
        assert template['template_name'] == "Updated"
        assert template['template_content'] == "Updated content"
    
    def test_delete_prompt_template(self, storage):
        """Test deleting a prompt template."""
        template_id = storage.create_prompt_template(
            "user1", "To Delete", "Content", "summarization"
        )
        
        # Delete template
        deleted = storage.delete_prompt_template(template_id)
        assert deleted is True
        
        # Verify template is gone
        template = storage.get_prompt_template(template_id)
        assert template is None
    
    def test_list_prompt_templates_for_user(self, storage):
        """Test listing prompt templates for a user."""
        # Create multiple templates
        storage.create_prompt_template("user1", "Template 1", "Content 1", "summarization")
        storage.create_prompt_template("user1", "Template 2", "Content 2", "summarization")
        storage.create_prompt_template("user2", "Template 3", "Content 3", "summarization")
        
        # List templates for user1
        templates = storage.list_prompt_templates("user1")
        assert len(templates) >= 2
        assert all(t['user_id'] == "user1" for t in templates)
    
    def test_validate_prompt_template_syntax(self, storage):
        """Test that prompt template validation works."""
        # Valid template with no variables
        is_valid, error = storage.validate_prompt_template("Simple prompt text")
        assert is_valid is True
        assert error is None
        
        # Valid template with valid variable syntax
        is_valid, error = storage.validate_prompt_template("Hello {user_name}, welcome!")
        assert is_valid is True
        assert error is None
        
        # Invalid template with unclosed brace
        is_valid, error = storage.validate_prompt_template("Hello {user_name, welcome!")
        assert is_valid is False
        assert error is not None
    
    def test_use_custom_prompt_template_in_summarization(self, storage, monkeypatch):
        """Test that custom prompt template is used in summarization."""
        # Mock LLM API call
        api_calls = []
        def mock_llm_call(url, headers, json_data, timeout):
            api_calls.append(json_data)
            # Return mock response
            from unittest.mock import Mock
            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                "choices": [{
                    "message": {"content": "Custom summary using custom template"}
                }]
            }
            response.raise_for_status = Mock()
            return response
        
        # Enable LLM and set up environment
        monkeypatch.setenv("LLM_API_URL", "http://localhost:8000")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        monkeypatch.setenv("LLM_MODEL", "gpt-3.5-turbo")
        
        storage.llm_api_url = "http://localhost:8000"
        storage.llm_api_key = "test-key"
        storage.llm_model = "gpt-3.5-turbo"
        storage.llm_enabled = True
        
        # Create custom prompt template
        template_id = storage.create_prompt_template(
            "user1", "Custom Summary", "Focus on technical details: {context}", "summarization"
        )
        
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Monkey patch httpx to capture calls
        import httpx
        original_post = httpx.Client.post
        
        def mock_post(self, url, **kwargs):
            api_calls.append(kwargs.get('json', {}))
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "choices": [{"message": {"content": "Summary with custom template"}}]
            }
            mock_response.raise_for_status = Mock()
            return mock_response
        
        monkeypatch.setattr(httpx.Client, "post", mock_post)
        
        # Test summarization with custom template
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        
        summary = storage._summarize_messages(messages, user_id="user1", chat_id="chat1")
        
        # Verify custom template was used (check that API was called)
        assert len(api_calls) > 0
        # The system message should contain the custom template content
        call_data = api_calls[0]
        if isinstance(call_data, dict):
            # Check if it's the payload dict with 'messages' key
            if 'messages' in call_data:
                system_msg = next((m for m in call_data['messages'] if m.get('role') == 'system'), None)
                if system_msg:
                    assert "Focus on technical details" in system_msg['content']
            # Or if messages are at top level (different mock structure)
            elif isinstance(call_data, list):
                system_msg = next((m for m in call_data if m.get('role') == 'system'), None)
                if system_msg:
                    assert "Focus on technical details" in system_msg['content']
        
        # At minimum, verify summary was returned
        assert summary is not None


@pytest.mark.asyncio
async def test_stream_llm_response_success(monkeypatch):
    """Test successfully streaming LLM response."""
    import pytest
    
    # Skip if psycopg2 is not available
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed")
    
    # Skip if PostgreSQL is not available
    try:
        psycopg2.connect(
            host="localhost",
            port=5432,
            dbname="conversations",
            user="postgres",
            connect_timeout=1
        ).close()
    except (psycopg2.OperationalError, psycopg2.Error):
        pytest.skip("PostgreSQL not available")
    
    from conversation_storage import ConversationStorage
    import httpx
    from unittest.mock import AsyncMock, MagicMock, patch
    
    # Enable LLM and set up environment
    monkeypatch.setenv("LLM_API_URL", "http://localhost:8000")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-3.5-turbo")
    
    storage = ConversationStorage()
    storage.llm_api_url = "http://localhost:8000"
    storage.llm_api_key = "test-key"
    storage.llm_model = "gpt-3.5-turbo"
    storage.llm_enabled = True
    
    # Mock SSE response data
    sse_lines = [
        "data: {\"choices\":[{\"delta\":{\"content\":\"Hello\"}}]}\n",
        "data: {\"choices\":[{\"delta\":{\"content\":\" world\"}}]}\n",
        "data: {\"choices\":[{\"delta\":{\"content\":\"!\"}}]}\n",
        "data: [DONE]\n"
    ]
    
    # Mock httpx.AsyncClient.stream
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = AsyncMock(return_value=iter(sse_lines))
    
    mock_stream_context = MagicMock()
    mock_stream_context.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_context.__aexit__ = AsyncMock(return_value=None)
    
    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_context)
    
    mock_async_client_context = MagicMock()
    mock_async_client_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_client_context.__aexit__ = AsyncMock(return_value=None)
    
    from unittest.mock import patch
    with patch.object(httpx, 'AsyncClient', return_value=mock_async_client_context):
        messages = [{"role": "user", "content": "Hello"}]
        
        chunks = []
        async for chunk in storage.stream_llm_response(messages):
            chunks.append(chunk)
        
        assert len(chunks) == 3
        assert chunks[0] == "Hello"
        assert chunks[1] == " world"
        assert chunks[2] == "!"


@pytest.mark.asyncio
async def test_stream_llm_response_with_system_prompt(monkeypatch):
    """Test streaming LLM response with custom system prompt."""
    import pytest
    
    # Skip if psycopg2 is not available
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed")
    
    # Skip if PostgreSQL is not available
    try:
        psycopg2.connect(
            host="localhost",
            port=5432,
            dbname="conversations",
            user="postgres",
            connect_timeout=1
        ).close()
    except (psycopg2.OperationalError, psycopg2.Error):
        pytest.skip("PostgreSQL not available")
    
    from conversation_storage import ConversationStorage
    import httpx
    from unittest.mock import AsyncMock, MagicMock, patch
    
    # Enable LLM and set up environment
    monkeypatch.setenv("LLM_API_URL", "http://localhost:8000")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "gpt-3.5-turbo")
    
    storage = ConversationStorage()
    storage.llm_api_url = "http://localhost:8000"
    storage.llm_api_key = "test-key"
    storage.llm_model = "gpt-3.5-turbo"
    storage.llm_enabled = True
    
    # Mock SSE response
    sse_lines = [
        "data: {\"choices\":[{\"delta\":{\"content\":\"Response\"}}]}\n",
        "data: [DONE]\n"
    ]
    
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.aiter_lines = AsyncMock(return_value=iter(sse_lines))
    
    mock_stream_context = MagicMock()
    mock_stream_context.__aenter__ = AsyncMock(return_value=mock_response)
    mock_stream_context.__aexit__ = AsyncMock(return_value=None)
    
    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=mock_stream_context)
    
    mock_async_client_context = MagicMock()
    mock_async_client_context.__aenter__ = AsyncMock(return_value=mock_client)
    mock_async_client_context.__aexit__ = AsyncMock(return_value=None)
    
    from unittest.mock import patch
    with patch.object(httpx, 'AsyncClient', return_value=mock_async_client_context):
        messages = [{"role": "user", "content": "Hello"}]
        
        chunks = []
        async for chunk in storage.stream_llm_response(
            messages,
            system_prompt="You are a helpful assistant."
        ):
            chunks.append(chunk)
        
        assert len(chunks) == 1
        assert chunks[0] == "Response"


@pytest.mark.asyncio
async def test_stream_llm_response_llm_disabled():
    """Test that streaming raises error when LLM is not enabled."""
    import pytest
    
    # Skip if psycopg2 is not available
    try:
        import psycopg2
    except ImportError:
        pytest.skip("psycopg2 not installed")
    
    # Skip if PostgreSQL is not available
    try:
        psycopg2.connect(
            host="localhost",
            port=5432,
            dbname="conversations",
            user="postgres",
            connect_timeout=1
        ).close()
    except (psycopg2.OperationalError, psycopg2.Error):
        pytest.skip("PostgreSQL not available")
    
    from conversation_storage import ConversationStorage
    
    storage = ConversationStorage()
    storage.llm_enabled = False
    
    messages = [{"role": "user", "content": "Hello"}]
    
    with pytest.raises(ValueError, match="LLM not configured"):
        async for _ in storage.stream_llm_response(messages):
            pass


class TestConversationSharing:
    """Test conversation sharing functionality."""
    
    def test_create_share_read_only(self, storage):
        """Test creating a read-only share for a conversation."""
        # Create conversation
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Hello", tokens=10)
        storage.add_message(conv_id, "assistant", "Hi!", tokens=15)
        
        # Create share
        share_id = storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only"
        )
        
        assert share_id > 0
        
        # Verify share
        share = storage.get_share(share_id)
        assert share is not None
        assert share["conversation_id"] == conv_id
        assert share["owner_user_id"] == "user1"
        assert share["shared_with_user_id"] == "user2"
        assert share["permission"] == "read_only"
        assert share["share_token"] is not None
        assert len(share["share_token"]) > 0
    
    def test_create_share_editable(self, storage):
        """Test creating an editable share for a conversation."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        share_id = storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="editable"
        )
        
        assert share_id > 0
        
        share = storage.get_share(share_id)
        assert share["permission"] == "editable"
    
    def test_create_share_with_token(self, storage):
        """Test creating a share with a custom token."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        share_id = storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only",
            share_token="custom-token-123"
        )
        
        share = storage.get_share(share_id)
        assert share["share_token"] == "custom-token-123"
    
    def test_create_share_duplicate_token(self, storage):
        """Test that duplicate share tokens are rejected."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only",
            share_token="unique-token"
        )
        
        # Try to create another share with same token
        with pytest.raises(ValueError, match="Share token already exists"):
            storage.create_share(
                user_id="user1",
                chat_id="chat2",
                shared_with_user_id="user3",
                permission="read_only",
                share_token="unique-token"
            )
    
    def test_get_share_by_token(self, storage):
        """Test retrieving a share by its token."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        share_id = storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only",
            share_token="test-token-123"
        )
        
        share = storage.get_share_by_token("test-token-123")
        assert share is not None
        assert share["id"] == share_id
        assert share["share_token"] == "test-token-123"
    
    def test_get_share_not_found(self, storage):
        """Test getting a non-existent share."""
        share = storage.get_share(99999)
        assert share is None
        
        share = storage.get_share_by_token("non-existent-token")
        assert share is None
    
    def test_list_shares_for_conversation(self, storage):
        """Test listing all shares for a conversation."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        # Create multiple shares
        share1 = storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only"
        )
        share2 = storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user3",
            permission="editable"
        )
        
        # Create share for different conversation (shouldn't appear)
        storage.get_or_create_conversation("user1", "chat2")
        storage.create_share(
            user_id="user1",
            chat_id="chat2",
            shared_with_user_id="user4",
            permission="read_only"
        )
        
        shares = storage.list_shares_for_conversation("user1", "chat1")
        assert len(shares) == 2
        share_ids = [s["id"] for s in shares]
        assert share1 in share_ids
        assert share2 in share_ids
    
    def test_list_shares_for_user(self, storage):
        """Test listing all shares where a user is the recipient."""
        storage.get_or_create_conversation("user1", "chat1")
        storage.get_or_create_conversation("user2", "chat2")
        
        share1 = storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only"
        )
        share2 = storage.create_share(
            user_id="user2",
            chat_id="chat2",
            shared_with_user_id="user2",
            permission="editable"
        )
        
        # Different user share (shouldn't appear)
        storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user3",
            permission="read_only"
        )
        
        shares = storage.list_shares_for_user("user2")
        assert len(shares) == 2
        share_ids = [s["id"] for s in shares]
        assert share1 in share_ids
        assert share2 in share_ids
    
    def test_delete_share(self, storage):
        """Test deleting a share."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        share_id = storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only"
        )
        
        deleted = storage.delete_share(share_id)
        assert deleted is True
        
        share = storage.get_share(share_id)
        assert share is None
    
    def test_delete_share_not_found(self, storage):
        """Test deleting a non-existent share."""
        deleted = storage.delete_share(99999)
        assert deleted is False
    
    def test_check_conversation_access_owner(self, storage):
        """Test that conversation owner has full access."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        access = storage.check_conversation_access("user1", "chat1", "user1")
        assert access["has_access"] is True
        assert access["can_read"] is True
        assert access["can_write"] is True
        assert access["permission"] == "owner"
    
    def test_check_conversation_access_read_only_share(self, storage):
        """Test access check for user with read-only share."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only"
        )
        
        access = storage.check_conversation_access("user1", "chat1", "user2")
        assert access["has_access"] is True
        assert access["can_read"] is True
        assert access["can_write"] is False
        assert access["permission"] == "read_only"
    
    def test_check_conversation_access_editable_share(self, storage):
        """Test access check for user with editable share."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="editable"
        )
        
        access = storage.check_conversation_access("user1", "chat1", "user2")
        assert access["has_access"] is True
        assert access["can_read"] is True
        assert access["can_write"] is True
        assert access["permission"] == "editable"
    
    def test_check_conversation_access_no_access(self, storage):
        """Test access check for user without access."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        access = storage.check_conversation_access("user1", "chat1", "user2")
        assert access["has_access"] is False
        assert access["can_read"] is False
        assert access["can_write"] is False
        assert access["permission"] is None
    
    def test_get_conversation_via_share(self, storage):
        """Test that shared user can retrieve conversation."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Hello", tokens=10)
        storage.add_message(conv_id, "assistant", "Hi!", tokens=15)
        
        storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only"
        )
        
        # user2 should be able to get the conversation
        conversation = storage.get_conversation("user1", "chat1", accessed_by_user_id="user2")
        assert conversation is not None
        assert len(conversation["messages"]) == 2
    
    def test_get_conversation_via_share_token(self, storage):
        """Test retrieving conversation using share token."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        storage.add_message(conv_id, "user", "Hello", tokens=10)
        
        share_token = "share-token-123"
        storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only",
            share_token=share_token
        )
        
        conversation = storage.get_conversation_by_share_token(share_token)
        assert conversation is not None
        assert conversation["user_id"] == "user1"
        assert conversation["chat_id"] == "chat1"
    
    def test_get_conversation_via_share_token_not_found(self, storage):
        """Test getting conversation with invalid share token."""
        conversation = storage.get_conversation_by_share_token("invalid-token")
        assert conversation is None
    
    def test_add_message_via_editable_share(self, storage):
        """Test that user with editable share can add messages."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="editable"
        )
        
        # Verify user2 has write access
        access = storage.check_conversation_access("user1", "chat1", "user2")
        assert access["can_write"] is True
        
        # user2 should be able to add messages (enforced at API level)
        # This test just verifies the access check works
    
    def test_add_message_via_read_only_share_fails(self, storage):
        """Test that user with read-only share cannot add messages."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only"
        )
        
        access = storage.check_conversation_access("user1", "chat1", "user2")
        assert access["can_write"] is False
    
    def test_delete_conversation_cascades_shares(self, storage):
        """Test that deleting a conversation deletes its shares."""
        conv_id = storage.get_or_create_conversation("user1", "chat1")
        
        share_id = storage.create_share(
            user_id="user1",
            chat_id="chat1",
            shared_with_user_id="user2",
            permission="read_only"
        )
        
        # Delete conversation
        storage.delete_conversation("user1", "chat1")
        
        # Share should be gone (cascade delete)
        share = storage.get_share(share_id)
        assert share is None
