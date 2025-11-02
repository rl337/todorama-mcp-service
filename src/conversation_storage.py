"""
Conversation context persistence module.

Stores conversation history in PostgreSQL instead of memory, with support for:
- Conversation retrieval by user/chat ID
- Context pruning for old conversations
- Conversation summarization for long contexts
- Conversation export/import
- Conversation analytics and reporting
"""
import os
import json
import secrets
from typing import Optional, List, Dict, Any, Tuple, Union
from datetime import datetime, timedelta
import logging
import httpx

from db_adapter import get_database_adapter, DatabaseType

logger = logging.getLogger(__name__)

# Try to import dateutil for flexible date parsing, fallback to datetime.fromisoformat
try:
    from dateutil.parser import parse as parse_date
    HAS_DATEUTIL = True
except ImportError:
    HAS_DATEUTIL = False
    def parse_date(date_str):
        """Fallback date parser using datetime.fromisoformat."""
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except:
            try:
                return datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
            except:
                return None


class ConversationStorage:
    """Manage conversation history persistence in PostgreSQL."""
    
    def __init__(self, db_path: str = None):
        """
        Initialize conversation storage.
        
        Args:
            db_path: Database connection string (for PostgreSQL) or None to use environment variables.
        """
        # Determine database type - conversation storage requires PostgreSQL
        db_type = os.getenv("DB_TYPE", "postgresql").lower()
        
        if db_path is None:
            db_host = os.getenv("DB_HOST", "localhost")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME", "conversations")
            db_user = os.getenv("DB_USER", "postgres")
            db_password = os.getenv("DB_PASSWORD", "")
            
            if db_password:
                self.db_path = f"host={db_host} port={db_port} dbname={db_name} user={db_user} password={db_password}"
            else:
                self.db_path = f"host={db_host} port={db_port} dbname={db_name} user={db_user}"
        else:
            self.db_path = db_path
        
        self.db_type = db_type
        self.adapter = get_database_adapter(self.db_path)
        self._init_schema()
        
        # LLM configuration for summarization
        self.llm_api_url = os.getenv("LLM_API_URL", "")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", "gpt-3.5-turbo")
        self.llm_enabled = bool(self.llm_api_url and self.llm_api_key)
    
    def _get_connection(self):
        """Get database connection using adapter."""
        return self.adapter.connect()
    
    def _normalize_sql(self, query: str) -> str:
        """Normalize SQL query for the current database backend."""
        return self.adapter.normalize_query(query)
    
    def _init_schema(self):
        """Initialize conversation storage schema."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Conversations table - one row per user/chat
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    last_message_at TIMESTAMP,
                    message_count INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    metadata TEXT,
                    UNIQUE(user_id, chat_id)
                )
            """)
            cursor.execute(query)
            
            # Conversation messages table - stores individual messages
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
                    content TEXT NOT NULL,
                    tokens INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            cursor.execute(query)
            
            # Create indexes for efficient queries
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_conversations_user_chat "
                "ON conversations(user_id, chat_id)"
            ))
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_conversations_updated "
                "ON conversations(updated_at)"
            ))
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_messages_conversation "
                "ON conversation_messages(conversation_id, created_at)"
            ))
            
            # Conversation shares table - stores conversation sharing information
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS conversation_shares (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id INTEGER NOT NULL,
                    owner_user_id TEXT NOT NULL,
                    shared_with_user_id TEXT,
                    share_token TEXT NOT NULL UNIQUE,
                    permission TEXT NOT NULL CHECK(permission IN ('read_only', 'editable')),
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            cursor.execute(query)
            
            # Create indexes for shares
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_shares_conversation "
                "ON conversation_shares(conversation_id)"
            ))
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_shares_token "
                "ON conversation_shares(share_token)"
            ))
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_shares_shared_with "
                "ON conversation_shares(shared_with_user_id)"
            ))
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_shares_owner "
                "ON conversation_shares(owner_user_id)"
            ))
            
            # Conversation templates table - stores reusable conversation templates
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS conversation_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    initial_messages TEXT NOT NULL,
                    metadata TEXT,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(query)
            
            # Quick replies table - stores quick reply buttons for templates
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS quick_replies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    action TEXT NOT NULL,
                    order_index INTEGER DEFAULT 0,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (template_id) REFERENCES conversation_templates(id) ON DELETE CASCADE
                )
            """)
            cursor.execute(query)
            
            # Create indexes for templates
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_templates_user "
                "ON conversation_templates(user_id)"
            ))
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_quick_replies_template "
                "ON quick_replies(template_id)"
            ))
            
            # Prompt templates table - stores custom LLM prompt templates
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS prompt_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    conversation_id INTEGER,
                    template_name TEXT NOT NULL,
                    template_content TEXT NOT NULL,
                    template_type TEXT NOT NULL DEFAULT 'summarization',
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            cursor.execute(query)
            
            # Create indexes for prompt templates
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_prompt_templates_user "
                "ON prompt_templates(user_id, template_type)"
            ))
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_prompt_templates_conversation "
                "ON prompt_templates(conversation_id, template_type)"
            ))
            
            # AB tests table - stores A/B test configurations
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS ab_tests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    control_config TEXT NOT NULL,
                    variant_config TEXT NOT NULL,
                    traffic_split REAL NOT NULL DEFAULT 0.5 CHECK(traffic_split >= 0 AND traffic_split <= 1),
                    active BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(query)
            
            # AB test assignments table - tracks which conversations are in which variant
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS ab_test_assignments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_id INTEGER NOT NULL,
                    conversation_id INTEGER NOT NULL,
                    variant TEXT NOT NULL CHECK(variant IN ('control', 'variant')),
                    assigned_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (test_id) REFERENCES ab_tests(id) ON DELETE CASCADE,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE,
                    UNIQUE(test_id, conversation_id)
                )
            """)
            cursor.execute(query)
            
            # AB test metrics table - stores metrics for each response
            query = self._normalize_sql("""
                CREATE TABLE IF NOT EXISTS ab_test_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    test_id INTEGER NOT NULL,
                    conversation_id INTEGER NOT NULL,
                    variant TEXT NOT NULL CHECK(variant IN ('control', 'variant')),
                    response_time_ms INTEGER,
                    tokens_used INTEGER,
                    user_satisfaction_score REAL,
                    error_occurred BOOLEAN DEFAULT 0,
                    metadata TEXT,
                    recorded_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (test_id) REFERENCES ab_tests(id) ON DELETE CASCADE,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                )
            """)
            cursor.execute(query)
            
            # Create indexes for AB testing
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_ab_tests_active "
                "ON ab_tests(active)"
            ))
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_ab_assignments_test_conversation "
                "ON ab_test_assignments(test_id, conversation_id)"
            ))
            cursor.execute(self._normalize_sql(
                "CREATE INDEX IF NOT EXISTS idx_ab_metrics_test_variant "
                "ON ab_test_metrics(test_id, variant, recorded_at)"
            ))
            
            conn.commit()
            logger.info("Conversation storage schema initialized")
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to initialize conversation schema: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_or_create_conversation(self, user_id: str, chat_id: str) -> int:
        """
        Get existing conversation or create a new one.
        
        Args:
            user_id: User identifier
            chat_id: Chat/conversation identifier
            
        Returns:
            Conversation ID
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Try to get existing conversation
            query = self._normalize_sql("""
                SELECT id FROM conversations 
                WHERE user_id = ? AND chat_id = ?
            """)
            cursor.execute(query, (user_id, chat_id))
            row = cursor.fetchone()
            
            if row:
                conversation_id = row[0]
                logger.debug(f"Found existing conversation {conversation_id} for user {user_id}, chat {chat_id}")
                return conversation_id
            
            # Create new conversation
            query = self._normalize_sql("""
                INSERT INTO conversations (user_id, chat_id, last_message_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            """)
            cursor.execute(query, (user_id, chat_id))
            conversation_id = self.adapter.get_last_insert_id(cursor)
            conn.commit()
            logger.info(f"Created new conversation {conversation_id} for user {user_id}, chat {chat_id}")
            return conversation_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to get/create conversation: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        tokens: Optional[int] = None
    ) -> int:
        """
        Add a message to a conversation.
        
        Args:
            conversation_id: Conversation ID
            role: Message role ('user', 'assistant', 'system')
            content: Message content
            tokens: Optional token count for this message
            
        Returns:
            Message ID
        """
        if role not in ['user', 'assistant', 'system']:
            raise ValueError(f"Invalid role: {role}")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Insert message
            query = self._normalize_sql("""
                INSERT INTO conversation_messages (conversation_id, role, content, tokens)
                VALUES (?, ?, ?, ?)
            """)
            cursor.execute(query, (conversation_id, role, content, tokens))
            message_id = self.adapter.get_last_insert_id(cursor)
            
            # Update conversation stats
            query = self._normalize_sql("""
                UPDATE conversations 
                SET message_count = message_count + 1,
                    total_tokens = COALESCE(total_tokens, 0) + COALESCE(?, 0),
                    last_message_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """)
            cursor.execute(query, (tokens or 0, conversation_id))
            
            conn.commit()
            logger.debug(f"Added message {message_id} to conversation {conversation_id}")
            return message_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to add message: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_conversation(
        self,
        user_id: str,
        chat_id: str,
        limit: Optional[int] = None,
        max_tokens: Optional[int] = None,
        accessed_by_user_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get conversation history for a user/chat.
        
        Args:
            user_id: User identifier (owner)
            chat_id: Chat identifier
            limit: Maximum number of messages to return (None for all)
            max_tokens: Maximum tokens (None for all, oldest messages pruned first)
            accessed_by_user_id: User ID requesting access (for access control)
            
        Returns:
            Conversation dictionary with messages, or None if not found or no access
        """
        # Check access if accessed_by_user_id is provided and different from owner
        if accessed_by_user_id and accessed_by_user_id != user_id:
            access = self.check_conversation_access(user_id, chat_id, accessed_by_user_id)
            if not access['has_access']:
                return None
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Get conversation
            query = self._normalize_sql("""
                SELECT id, user_id, chat_id, created_at, updated_at, 
                       last_message_at, message_count, total_tokens, metadata
                FROM conversations
                WHERE user_id = ? AND chat_id = ?
            """)
            cursor.execute(query, (user_id, chat_id))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            conversation = {
                'id': row[0],
                'user_id': row[1],
                'chat_id': row[2],
                'created_at': row[3],
                'updated_at': row[4],
                'last_message_at': row[5],
                'message_count': row[6],
                'total_tokens': row[7],
                'metadata': json.loads(row[8]) if row[8] else {}
            }
            
            # Get messages
            query = self._normalize_sql("""
                SELECT id, role, content, tokens, created_at
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
            """)
            
            if max_tokens:
                # Get messages in reverse order and limit by tokens
                query = self._normalize_sql("""
                    SELECT id, role, content, tokens, created_at
                    FROM conversation_messages
                    WHERE conversation_id = ?
                    ORDER BY created_at DESC
                """)
                cursor.execute(query, (conversation['id'],))
                messages = []
                total_tokens = 0
                
                for msg_row in cursor.fetchall():
                    msg_tokens = msg_row[3] or 0
                    if total_tokens + msg_tokens > max_tokens:
                        break
                    messages.append({
                        'id': msg_row[0],
                        'role': msg_row[1],
                        'content': msg_row[2],
                        'tokens': msg_row[3],
                        'created_at': msg_row[4]
                    })
                    total_tokens += msg_tokens
                
                # Reverse to get chronological order
                messages.reverse()
                
                if limit:
                    messages = messages[-limit:]
            else:
                cursor.execute(query, (conversation['id'],))
                messages = []
                for msg_row in cursor.fetchall():
                    messages.append({
                        'id': msg_row[0],
                        'role': msg_row[1],
                        'content': msg_row[2],
                        'tokens': msg_row[3],
                        'created_at': msg_row[4]
                    })
                
                if limit:
                    messages = messages[-limit:]
            
            conversation['messages'] = messages
            
            # Check if summarization should be triggered
            # Only trigger if max_tokens is provided (indicating we care about token limits)
            if max_tokens and self.llm_enabled:
                # Get all messages to check if summarization is needed
                all_messages = self._get_all_messages(conversation['id'])
                all_tokens = sum(msg.get('tokens', 0) for msg in all_messages)
                
                # If total tokens exceed threshold (e.g., 80% of max), consider summarization
                threshold = max_tokens * 0.8
                if all_tokens > threshold and len(all_messages) > 6:  # Need enough messages to summarize
                    logger.info(f"Context window is long ({all_tokens} tokens), considering summarization")
                    # Try to summarize old messages
                    try:
                        self.summarize_old_messages(user_id, chat_id, max_tokens, keep_recent=5)
                        # Re-fetch conversation after summarization
                        return self.get_conversation(user_id, chat_id, limit=limit, max_tokens=max_tokens)
                    except Exception as e:
                        logger.warning(f"Failed to summarize conversation: {e}", exc_info=True)
                        # Continue with original conversation if summarization fails
            
            return conversation
        finally:
            self.adapter.close(conn)
    
    def _get_all_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        """Get all messages for a conversation (for internal use)."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, role, content, tokens, created_at
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
            """)
            cursor.execute(query, (conversation_id,))
            messages = []
            for msg_row in cursor.fetchall():
                messages.append({
                    'id': msg_row[0],
                    'role': msg_row[1],
                    'content': msg_row[2],
                    'tokens': msg_row[3],
                    'created_at': msg_row[4]
                })
            return messages
        finally:
            self.adapter.close(conn)
    
    def _summarize_messages(
        self,
        messages: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None
    ) -> str:
        """
        Summarize a list of conversation messages using LLM.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            user_id: Optional user ID for custom template lookup
            chat_id: Optional chat ID for custom template lookup
            
        Returns:
            Summary text
        """
        if not self.llm_enabled:
            # Fallback: simple concatenation if LLM not available
            logger.warning("LLM not configured, using simple text concatenation for summary")
            summary_parts = []
            for msg in messages:
                role = msg.get('role', 'unknown')
                content = msg.get('content', '')
                summary_parts.append(f"{role}: {content[:100]}...")  # Truncate long messages
            return "Previous conversation: " + " | ".join(summary_parts)
        
        try:
            # Format messages for LLM API (OpenAI-compatible format)
            formatted_messages = [
                {"role": msg.get('role', 'user'), "content": msg.get('content', '')}
                for msg in messages
            ]
            
            # Get custom prompt template if user_id and chat_id are provided
            template_content = None
            if user_id and chat_id:
                template = self.get_prompt_template_for_conversation(user_id, chat_id, "summarization")
                if template:
                    template_content = template['template_content']
                    logger.debug(f"Using custom prompt template {template['id']} for summarization")
            
            # Use custom template or default system message
            if template_content:
                # Format template with context if needed (for future expansion)
                try:
                    if '{context}' in template_content:
                        system_content = template_content.format(context="conversation history")
                    else:
                        system_content = template_content
                except (KeyError, ValueError):
                    # If formatting fails, use template as-is
                    logger.warning("Failed to format template variables, using template as-is")
                    system_content = template_content
            else:
                system_content = "You are a helpful assistant that summarizes conversation history. Create a concise summary that preserves key information, important facts, user preferences, and context. Focus on what matters most for continuing the conversation."
            
            # Add system message for summarization task
            system_message = {
                "role": "system",
                "content": system_content
            }
            
            api_messages = [system_message] + formatted_messages
            
            # Call LLM API (OpenAI-compatible)
            headers = {
                "Authorization": f"Bearer {self.llm_api_key}",
                "Content-Type": "application/json"
            }
            
            payload = {
                "model": self.llm_model,
                "messages": api_messages,
                "max_tokens": 500,  # Limit summary length
                "temperature": 0.3  # Lower temperature for more consistent summaries
            }
            
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.llm_api_url.rstrip('/')}/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                response.raise_for_status()
                result = response.json()
                
                # Extract summary from response
                if "choices" in result and len(result["choices"]) > 0:
                    summary = result["choices"][0]["message"]["content"]
                    logger.info(f"Generated summary with {len(summary)} characters")
                    
                    # Track cost for summarization
                    if user_id and chat_id:
                        try:
                            from cost_tracking import CostTracker, ServiceType
                            cost_tracker = CostTracker()
                            conv_id = self.get_or_create_conversation(user_id, chat_id)
                            
                            # Extract token usage from response
                            usage = result.get("usage", {})
                            input_tokens = usage.get("prompt_tokens", 0)
                            output_tokens = usage.get("completion_tokens", 0)
                            total_tokens = usage.get("total_tokens", input_tokens + output_tokens)
                            
                            # Calculate cost
                            cost = cost_tracker.calculate_llm_cost(
                                model=self.llm_model,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens
                            )
                            
                            # Record cost
                            cost_tracker.record_cost(
                                service_type=ServiceType.LLM,
                                user_id=user_id,
                                conversation_id=conv_id,
                                cost=cost,
                                tokens=total_tokens,
                                metadata={
                                    "model": self.llm_model,
                                    "input_tokens": input_tokens,
                                    "output_tokens": output_tokens,
                                    "operation": "summarization"
                                }
                            )
                        except Exception as e:
                            # Don't fail the request if cost tracking fails
                            logger.warning(f"Failed to track LLM cost for summarization: {e}", exc_info=True)
                    
                    return summary
                else:
                    raise ValueError("Invalid LLM API response format")
                    
        except httpx.HTTPError as e:
            logger.error(f"HTTP error calling LLM API: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"Error summarizing messages: {e}", exc_info=True)
            raise
    
    async def stream_llm_response(
        self,
        messages: List[Dict[str, Any]],
        user_id: Optional[str] = None,
        chat_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.7,
        system_prompt: Optional[str] = None,
        ab_test_id: Optional[int] = None
    ):
        """
        Stream LLM response character-by-character.
        
        Uses Server-Sent Events (SSE) to stream responses from OpenAI-compatible APIs.
        Yields text chunks as they arrive from the LLM.
        
        Args:
            messages: List of message dictionaries with 'role' and 'content'
            user_id: Optional user ID for custom template lookup
            chat_id: Optional chat ID for custom template lookup
            max_tokens: Maximum tokens for the response
            temperature: Temperature for response generation (0.0-2.0)
            system_prompt: Optional system prompt to prepend
            ab_test_id: Optional A/B test ID to use for variant assignment
            
        Yields:
            Text chunks (strings) as they arrive from the LLM
            
        Raises:
            ValueError: If LLM is not enabled or invalid configuration
            httpx.HTTPError: If API request fails
        """
        if not self.llm_enabled:
            raise ValueError("LLM not configured. Set LLM_API_URL and LLM_API_KEY environment variables.")
        
        # A/B testing setup
        ab_variant = None
        conversation_id = None
        test_config = None
        ab_test_start_time = None
        model_to_use = self.llm_model  # Default to configured model
        
        # Handle A/B testing if test_id is provided
        if ab_test_id and user_id and chat_id:
            conversation_id = self.get_or_create_conversation(user_id, chat_id)
            ab_variant = self.assign_ab_variant(conversation_id, ab_test_id)
            test_config = self.get_ab_test(ab_test_id)
            ab_test_start_time = datetime.now()
            
            if test_config and ab_variant:
                variant_config_str = test_config['variant_config'] if ab_variant == 'variant' else test_config['control_config']
                variant_config = json.loads(variant_config_str)
                
                # Override model, temperature, system_prompt from variant config
                if 'model' in variant_config:
                    model_to_use = variant_config['model']
                
                if 'temperature' in variant_config:
                    temperature = variant_config['temperature']
                
                if 'system_prompt' in variant_config:
                    system_prompt = variant_config['system_prompt']
        
        # Format messages for LLM API (OpenAI-compatible format)
        formatted_messages = [
            {"role": msg.get('role', 'user'), "content": msg.get('content', '')}
            for msg in messages
        ]
        
        # Get custom prompt template if user_id and chat_id are provided
        template_content = None
        if user_id and chat_id:
            template = self.get_prompt_template_for_conversation(user_id, chat_id, "chat")
            if template:
                template_content = template['template_content']
        
        # Use custom template or provided system prompt or default
        if template_content:
            system_content = template_content
        elif system_prompt:
            system_content = system_prompt
        else:
            system_content = "You are a helpful assistant."
        
        # Add system message if provided
        if system_content:
            system_message = {"role": "system", "content": system_content}
            api_messages = [system_message] + formatted_messages
        else:
            api_messages = formatted_messages
        
        # Prepare streaming request
        headers = {
            "Authorization": f"Bearer {self.llm_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": model_to_use,
            "messages": api_messages,
            "stream": True,  # Enable streaming
            "temperature": temperature
        }
        
        if max_tokens:
            payload["max_tokens"] = max_tokens
        
        # Make streaming request using httpx with async client
        response_content = ""
        tokens_used = None
        input_tokens = None
        output_tokens = None
        error_occurred = False
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                async with client.stream(
                    "POST",
                    f"{self.llm_api_url.rstrip('/')}/v1/chat/completions",
                    headers=headers,
                    json=payload
                ) as response:
                    response.raise_for_status()
                    
                    # Parse Server-Sent Events
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        
                        # SSE format: "data: {json}"
                        if line.startswith("data: "):
                            data_str = line[6:]  # Remove "data: " prefix
                            
                            # Check for [DONE] marker
                            if data_str.strip() == "[DONE]":
                                break
                            
                            try:
                                data = json.loads(data_str)
                                
                                # Extract content delta from OpenAI-compatible format
                                if "choices" in data and len(data["choices"]) > 0:
                                    choice = data["choices"][0]
                                    delta = choice.get("delta", {})
                                    content = delta.get("content", "")
                                    
                                    if content:
                                        response_content += content
                                        yield content
                                
                                # Track token usage if available
                                if "usage" in data:
                                    tokens_used = data["usage"].get("total_tokens")
                                    # Also capture input/output tokens for cost calculation
                                    input_tokens = data["usage"].get("prompt_tokens", 0)
                                    output_tokens = data["usage"].get("completion_tokens", 0)
                                    
                            except json.JSONDecodeError:
                                logger.warning(f"Failed to parse SSE data: {data_str}")
                                continue
                            except Exception as e:
                                logger.warning(f"Error processing SSE chunk: {e}")
                                continue
                    
                logger.debug("Finished streaming LLM response")
        
        except httpx.HTTPError as e:
            error_occurred = True
            logger.error(f"HTTP error calling LLM API for streaming: {e}", exc_info=True)
            raise
        except Exception as e:
            error_occurred = True
            logger.error(f"Error streaming LLM response: {e}", exc_info=True)
            raise
        finally:
            # Track cost for LLM usage
            if user_id and conversation_id:
                # Estimate tokens if not available
                if tokens_used is None and response_content:
                    tokens_used = len(response_content) // 4  # Rough estimate
                
                if tokens_used:
                    try:
                        from cost_tracking import CostTracker, ServiceType
                        cost_tracker = CostTracker()
                        
                        # Estimate input/output tokens if not available
                        if input_tokens is None or output_tokens is None:
                            # Rough estimate: 60% input, 40% output for typical conversations
                            input_tokens = int(tokens_used * 0.6)
                            output_tokens = tokens_used - input_tokens
                        
                        # Calculate cost
                        cost = cost_tracker.calculate_llm_cost(
                            model=model_to_use,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens
                        )
                        
                        # Record cost
                        cost_tracker.record_cost(
                            service_type=ServiceType.LLM,
                            user_id=user_id,
                            conversation_id=conversation_id,
                            cost=cost,
                            tokens=tokens_used,
                            metadata={
                                "model": model_to_use,
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "temperature": temperature,
                                "max_tokens": max_tokens,
                                "ab_test_id": ab_test_id,
                                "ab_variant": ab_variant
                            }
                        )
                    except Exception as e:
                        # Don't fail the request if cost tracking fails
                        logger.warning(f"Failed to track LLM cost: {e}", exc_info=True)
            
            # Record A/B test metrics if applicable
            if ab_test_id and conversation_id and ab_variant:
                try:
                    response_time_ms = None
                    if ab_test_start_time:
                        response_time_ms = int((datetime.now() - ab_test_start_time).total_seconds() * 1000)
                    
                    # Estimate tokens if not provided (rough estimate: 1 token ? 4 characters)
                    if tokens_used is None and response_content:
                        tokens_used = len(response_content) // 4
                    
                    self.record_ab_metric(
                        test_id=ab_test_id,
                        conversation_id=conversation_id,
                        variant=ab_variant,
                        response_time_ms=response_time_ms,
                        tokens_used=tokens_used,
                        error_occurred=error_occurred
                    )
                except Exception as e:
                    # Don't fail the request if metrics recording fails
                    logger.warning(f"Failed to record A/B test metrics: {e}", exc_info=True)

    def summarize_old_messages(
        self,
        user_id: str,
        chat_id: str,
        max_tokens: int,
        keep_recent: int = 5
    ) -> bool:
        """
        Summarize old messages when context window gets long.
        Replaces old messages with a summary message while preserving key information.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            max_tokens: Maximum tokens for the conversation
            keep_recent: Minimum number of recent messages to always keep
            
        Returns:
            True if summarization was performed, False otherwise
        """
        conversation = self.get_conversation(user_id, chat_id)
        if not conversation:
            return False
        
        messages = conversation.get('messages', [])
        if len(messages) <= keep_recent + 1:  # Not enough messages to summarize
            return False
        
        # Calculate tokens
        total_tokens = sum(msg.get('tokens', 0) for msg in messages)
        
        # Only summarize if we're approaching the limit
        threshold = max_tokens * 0.75
        if total_tokens < threshold:
            return False
        
        # Get messages to summarize (old messages, keeping recent ones)
        recent_messages = messages[-keep_recent:] if len(messages) > keep_recent else []
        old_messages = messages[:-keep_recent] if len(messages) > keep_recent else []
        
        if not old_messages:
            return False
        
        # Check if there's already a summary message
        # (to avoid re-summarizing already summarized content)
        has_summary = any(
            msg.get('role') == 'system' and 'summary' in msg.get('content', '').lower()
            for msg in old_messages[-1:]
        )
        if has_summary and len(old_messages) <= 1:
            # Already summarized, no need to re-summarize
            return False
        
        try:
            # Summarize old messages
            logger.info(f"Summarizing {len(old_messages)} old messages")
            summary_text = self._summarize_messages(old_messages, user_id=user_id, chat_id=chat_id)
            
            # Estimate tokens for summary (rough estimate: 1 token per 4 characters)
            summary_tokens = len(summary_text) // 4
            
            # Calculate tokens in messages we're keeping
            kept_tokens = sum(msg.get('tokens', 0) for msg in recent_messages)
            old_tokens = sum(msg.get('tokens', 0) for msg in old_messages)
            
            # Replace old messages with summary
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                
                # Delete old messages
                old_message_ids = [msg['id'] for msg in old_messages]
                if old_message_ids:
                    placeholders = ','.join(['?' for _ in old_message_ids])
                    query = self._normalize_sql(f"""
                        DELETE FROM conversation_messages
                        WHERE conversation_id = ? AND id IN ({placeholders})
                    """)
                    cursor.execute(query, (conversation['id'],) + tuple(old_message_ids))
                
                # Add summary as a system message
                summary_content = f"[Summary of previous conversation ({len(old_messages)} messages)]: {summary_text}"
                query = self._normalize_sql("""
                    INSERT INTO conversation_messages (conversation_id, role, content, tokens)
                    VALUES (?, ?, ?, ?)
                """)
                cursor.execute(query, (conversation['id'], 'system', summary_content, summary_tokens))
                
                # Update conversation stats
                new_total_tokens = kept_tokens + summary_tokens
                new_message_count = len(recent_messages) + 1  # +1 for summary
                query = self._normalize_sql("""
                    UPDATE conversations
                    SET message_count = ?,
                        total_tokens = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """)
                cursor.execute(query, (new_message_count, new_total_tokens, conversation['id']))
                
                conn.commit()
                logger.info(f"Summarized {len(old_messages)} messages into summary, reduced tokens from {old_tokens} to {summary_tokens}")
                return True
                
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to replace messages with summary: {e}", exc_info=True)
                raise
            finally:
                self.adapter.close(conn)
                
        except Exception as e:
            logger.error(f"Failed to summarize old messages: {e}", exc_info=True)
            return False
    
    def prune_old_contexts(
        self,
        user_id: str,
        chat_id: str,
        max_tokens: int,
        keep_recent: int = 5
    ) -> int:
        """
        Prune old messages from conversation to stay within token limit.
        Keeps the most recent messages.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            max_tokens: Maximum tokens to keep
            keep_recent: Minimum number of recent messages to always keep
            
        Returns:
            Number of messages pruned
        """
        conversation = self.get_conversation(user_id, chat_id)
        if not conversation:
            return 0
        
        messages = conversation['messages']
        if not messages:
            return 0
        
        # Calculate tokens from oldest to newest
        total_tokens = 0
        keep_messages = []
        
        # Always keep the most recent messages
        recent_messages = messages[-keep_recent:] if len(messages) > keep_recent else messages
        recent_tokens = sum(msg.get('tokens', 0) for msg in recent_messages)
        
        if recent_tokens > max_tokens:
            # Even recent messages exceed limit, keep only what fits
            for msg in reversed(recent_messages):
                msg_tokens = msg.get('tokens', 0)
                if total_tokens + msg_tokens <= max_tokens:
                    keep_messages.insert(0, msg)
                    total_tokens += msg_tokens
                else:
                    break
        else:
            # Keep recent messages, add older ones up to limit
            keep_messages = recent_messages.copy()
            total_tokens = recent_tokens
            
            # Add older messages from back to front
            older_messages = messages[:-keep_recent] if len(messages) > keep_recent else []
            for msg in reversed(older_messages):
                msg_tokens = msg.get('tokens', 0)
                if total_tokens + msg_tokens <= max_tokens:
                    keep_messages.insert(0, msg)
                    total_tokens += msg_tokens
                else:
                    break
        
        # Delete messages not in keep list
        keep_ids = {msg['id'] for msg in keep_messages}
        prune_count = len(messages) - len(keep_messages)
        
        if prune_count > 0:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                placeholders = ','.join(['?' for _ in keep_ids])
                query = self._normalize_sql(f"""
                    DELETE FROM conversation_messages
                    WHERE conversation_id = ? AND id NOT IN ({placeholders})
                """)
                cursor.execute(query, (conversation['id'],) + tuple(keep_ids))
                
                # Update conversation stats
                cursor.execute(self._normalize_sql("""
                    UPDATE conversations
                    SET message_count = ?,
                        total_tokens = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """), (len(keep_messages), total_tokens, conversation['id']))
                
                conn.commit()
                logger.info(f"Pruned {prune_count} messages from conversation {conversation['id']}")
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to prune messages: {e}", exc_info=True)
                raise
            finally:
                self.adapter.close(conn)
        
        return prune_count
    
    def reset_conversation(self, user_id: str, chat_id: str) -> bool:
        """
        Reset a conversation by clearing all messages but keeping the conversation record.
        This is useful for starting a new conversation context while preserving metadata.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            
        Returns:
            True if reset, False if conversation not found
        """
        conversation = self.get_conversation(user_id, chat_id)
        if not conversation:
            return False
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Delete all messages
            query = self._normalize_sql("""
                DELETE FROM conversation_messages
                WHERE conversation_id = ?
            """)
            cursor.execute(query, (conversation['id'],))
            
            # Reset conversation stats
            query = self._normalize_sql("""
                UPDATE conversations
                SET message_count = 0,
                    total_tokens = 0,
                    last_message_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """)
            cursor.execute(query, (conversation['id'],))
            
            conn.commit()
            logger.info(f"Reset conversation {conversation['id']} for user {user_id}, chat {chat_id}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to reset conversation: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def clear_conversation(self, user_id: str, chat_id: str) -> bool:
        """
        Clear all messages from a conversation but keep the conversation record.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            
        Returns:
            True if cleared, False if conversation not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            # Get conversation ID
            query = self._normalize_sql("""
                SELECT id FROM conversations
                WHERE user_id = ? AND chat_id = ?
            """)
            cursor.execute(query, (user_id, chat_id))
            row = cursor.fetchone()
            
            if not row:
                return False
            
            conversation_id = row[0]
            
            # Delete all messages
            query = self._normalize_sql("""
                DELETE FROM conversation_messages
                WHERE conversation_id = ?
            """)
            cursor.execute(query, (conversation_id,))
            
            # Reset conversation stats
            query = self._normalize_sql("""
                UPDATE conversations
                SET message_count = 0,
                    total_tokens = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """)
            cursor.execute(query, (conversation_id,))
            
            conn.commit()
            logger.info(f"Cleared conversation for user {user_id}, chat {chat_id}")
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to clear conversation: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def delete_conversation(self, user_id: str, chat_id: str) -> bool:
        """
        Delete a conversation and all its messages.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            
        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                DELETE FROM conversations
                WHERE user_id = ? AND chat_id = ?
            """)
            cursor.execute(query, (user_id, chat_id))
            deleted = cursor.rowcount > 0
            conn.commit()
            if deleted:
                logger.info(f"Deleted conversation for user {user_id}, chat {chat_id}")
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete conversation: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def export_conversation(
        self,
        user_id: str,
        chat_id: str,
        format: str = "json",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Union[Dict[str, Any], str, bytes]:
        """
        Export conversation to JSON, TXT, or PDF format.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            format: Export format ('json', 'txt', or 'pdf')
            start_date: Optional start date for filtering messages (inclusive)
            end_date: Optional end date for filtering messages (inclusive)
            
        Returns:
            Dictionary for JSON format, string for TXT format, bytes for PDF format
        """
        conversation = self.get_conversation(user_id, chat_id)
        if not conversation:
            raise ValueError(f"Conversation not found for user {user_id}, chat {chat_id}")
        
        # Filter messages by date range if provided
        messages = conversation.get('messages', [])
        if start_date or end_date:
            filtered_messages = []
            for msg in messages:
                msg_date = msg.get('created_at')
                if msg_date:
                    if isinstance(msg_date, str):
                        try:
                            msg_date = datetime.fromisoformat(msg_date.replace('Z', '+00:00'))
                        except:
                            # If parsing fails, include the message
                            filtered_messages.append(msg)
                            continue
                    
                    # Check date range
                    if start_date and msg_date < start_date:
                        continue
                    if end_date and msg_date > end_date:
                        continue
                    filtered_messages.append(msg)
                else:
                    # If no date, include the message (for backwards compatibility)
                    filtered_messages.append(msg)
            messages = filtered_messages
        
        # Format conversation data
        conv_data = {
            'user_id': conversation['user_id'],
            'chat_id': conversation['chat_id'],
            'created_at': conversation['created_at'].isoformat() if isinstance(conversation['created_at'], datetime) else str(conversation['created_at']),
            'updated_at': conversation['updated_at'].isoformat() if isinstance(conversation['updated_at'], datetime) else str(conversation['updated_at']),
            'last_message_at': conversation['last_message_at'].isoformat() if conversation['last_message_at'] and isinstance(conversation['last_message_at'], datetime) else (str(conversation['last_message_at']) if conversation['last_message_at'] else None),
            'message_count': len(messages),
            'total_tokens': sum(msg.get('tokens', 0) for msg in messages),
            'metadata': conversation.get('metadata', {}),
            'messages': [
                {
                    'role': msg['role'],
                    'content': msg['content'],
                    'tokens': msg.get('tokens'),
                    'created_at': msg['created_at'].isoformat() if isinstance(msg['created_at'], datetime) else str(msg['created_at'])
                }
                for msg in messages
            ]
        }
        
        if format == "json":
            return conv_data
        elif format == "txt":
            return self._export_to_txt(conv_data)
        elif format == "pdf":
            return self._export_to_pdf(conv_data)
        else:
            raise ValueError(f"Unsupported export format: {format}. Supported formats: json, txt, pdf")
    
    def _export_to_txt(self, conv_data: Dict[str, Any]) -> str:
        """
        Export conversation data to plain text format.
        
        Args:
            conv_data: Conversation data dictionary
            
        Returns:
            Plain text string
        """
        lines = []
        lines.append("=" * 80)
        lines.append(f"Conversation Export")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"User ID: {conv_data['user_id']}")
        lines.append(f"Chat ID: {conv_data['chat_id']}")
        lines.append(f"Created At: {conv_data['created_at']}")
        lines.append(f"Updated At: {conv_data['updated_at']}")
        if conv_data.get('last_message_at'):
            lines.append(f"Last Message At: {conv_data['last_message_at']}")
        lines.append(f"Message Count: {conv_data['message_count']}")
        lines.append(f"Total Tokens: {conv_data['total_tokens']}")
        if conv_data.get('metadata'):
            lines.append(f"Metadata: {json.dumps(conv_data['metadata'], indent=2)}")
        lines.append("")
        lines.append("-" * 80)
        lines.append("Messages")
        lines.append("-" * 80)
        lines.append("")
        
        for msg in conv_data['messages']:
            role = msg['role'].upper()
            content = msg['content']
            timestamp = msg.get('created_at', '')
            tokens = msg.get('tokens', '')
            
            lines.append(f"[{role}] {timestamp}")
            if tokens:
                lines.append(f"Tokens: {tokens}")
            lines.append("")
            lines.append(content)
            lines.append("")
            lines.append("-" * 80)
            lines.append("")
        
        return "\n".join(lines)
    
    def _export_to_pdf(self, conv_data: Dict[str, Any]) -> bytes:
        """
        Export conversation data to PDF format.
        
        Args:
            conv_data: Conversation data dictionary
            
        Returns:
            PDF file as bytes
        """
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
            from reportlab.lib.enums import TA_LEFT
            from io import BytesIO
            
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter)
            story = []
            
            # Define styles
            styles = getSampleStyleSheet()
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=16,
                textColor='#000000',
                spaceAfter=12,
                alignment=TA_LEFT
            )
            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Heading2'],
                fontSize=12,
                textColor='#333333',
                spaceAfter=6,
                alignment=TA_LEFT
            )
            normal_style = styles['Normal']
            meta_style = ParagraphStyle(
                'Meta',
                parent=styles['Normal'],
                fontSize=9,
                textColor='#666666',
                spaceAfter=12
            )
            
            # Title
            story.append(Paragraph("Conversation Export", title_style))
            story.append(Spacer(1, 0.2 * inch))
            
            # Metadata
            story.append(Paragraph("<b>Conversation Information</b>", heading_style))
            story.append(Paragraph(f"User ID: {conv_data['user_id']}", meta_style))
            story.append(Paragraph(f"Chat ID: {conv_data['chat_id']}", meta_style))
            story.append(Paragraph(f"Created At: {conv_data['created_at']}", meta_style))
            story.append(Paragraph(f"Updated At: {conv_data['updated_at']}", meta_style))
            if conv_data.get('last_message_at'):
                story.append(Paragraph(f"Last Message At: {conv_data['last_message_at']}", meta_style))
            story.append(Paragraph(f"Message Count: {conv_data['message_count']}", meta_style))
            story.append(Paragraph(f"Total Tokens: {conv_data['total_tokens']}", meta_style))
            if conv_data.get('metadata'):
                story.append(Paragraph(f"Metadata: {json.dumps(conv_data['metadata'])}", meta_style))
            
            story.append(Spacer(1, 0.3 * inch))
            story.append(Paragraph("<b>Messages</b>", heading_style))
            story.append(Spacer(1, 0.2 * inch))
            
            # Messages
            for msg in conv_data['messages']:
                role = msg['role'].upper()
                content = msg['content']
                timestamp = msg.get('created_at', '')
                tokens = msg.get('tokens', '')
                
                # Role header
                role_text = f"<b>[{role}]</b>"
                if timestamp:
                    role_text += f" <i>{timestamp}</i>"
                if tokens:
                    role_text += f" (Tokens: {tokens})"
                
                story.append(Paragraph(role_text, heading_style))
                
                # Content (escape HTML special characters)
                content_escaped = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                # Replace newlines with <br/>
                content_escaped = content_escaped.replace('\n', '<br/>')
                story.append(Paragraph(content_escaped, normal_style))
                story.append(Spacer(1, 0.2 * inch))
            
            # Build PDF
            doc.build(story)
            buffer.seek(0)
            return buffer.getvalue()
            
        except ImportError:
            logger.error("reportlab is not installed. Install it with: pip install reportlab")
            raise ValueError("PDF export requires reportlab library. Install with: pip install reportlab")
        except Exception as e:
            logger.error(f"Error generating PDF: {e}", exc_info=True)
            raise
    
    def import_conversation(self, data: Dict[str, Any]) -> int:
        """
        Import conversation from JSON format.
        
        Args:
            data: Dictionary with conversation data (from export_conversation)
            
        Returns:
            Conversation ID
        """
        user_id = data['user_id']
        chat_id = data['chat_id']
        
        # Create or get conversation
        conversation_id = self.get_or_create_conversation(user_id, chat_id)
        
        # Import messages
        for msg_data in data.get('messages', []):
            self.add_message(
                conversation_id=conversation_id,
                role=msg_data['role'],
                content=msg_data['content'],
                tokens=msg_data.get('tokens')
            )
        
        # Update metadata if provided
        if 'metadata' in data and data['metadata']:
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = self._normalize_sql("""
                    UPDATE conversations
                    SET metadata = ?
                    WHERE id = ?
                """)
                cursor.execute(query, (json.dumps(data['metadata']), conversation_id))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.error(f"Failed to update metadata: {e}", exc_info=True)
                raise
            finally:
                self.adapter.close(conn)
        
        logger.info(f"Imported conversation {conversation_id} with {len(data.get('messages', []))} messages")
        return conversation_id
    
    def list_conversations(
        self,
        user_id: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        List conversations, optionally filtered by user.
        
        Args:
            user_id: Optional user ID to filter by
            limit: Maximum number of conversations to return
            
        Returns:
            List of conversation dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            if user_id:
                query = self._normalize_sql("""
                    SELECT id, user_id, chat_id, created_at, updated_at,
                           last_message_at, message_count, total_tokens
                    FROM conversations
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                """)
                cursor.execute(query, (user_id, limit))
            else:
                query = self._normalize_sql("""
                    SELECT id, user_id, chat_id, created_at, updated_at,
                           last_message_at, message_count, total_tokens
                    FROM conversations
                    ORDER BY updated_at DESC
                    LIMIT ?
                """)
                cursor.execute(query, (limit,))
            
            conversations = []
            for row in cursor.fetchall():
                conversations.append({
                    'id': row[0],
                    'user_id': row[1],
                    'chat_id': row[2],
                    'created_at': row[3],
                    'updated_at': row[4],
                    'last_message_at': row[5],
                    'message_count': row[6],
                    'total_tokens': row[7]
                })
            
            return conversations
        finally:
            self.adapter.close(conn)
    
    # Template Management Methods
    
    def create_template(
        self,
        user_id: str,
        name: str,
        description: str = "",
        initial_messages: List[Dict[str, str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Create a conversation template.
        
        Args:
            user_id: User identifier who owns the template
            name: Template name
            description: Template description
            initial_messages: List of initial messages to include (dicts with 'role' and 'content')
            metadata: Optional metadata dictionary
            
        Returns:
            Template ID
        """
        if initial_messages is None:
            initial_messages = []
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            query = self._normalize_sql("""
                INSERT INTO conversation_templates (user_id, name, description, initial_messages, metadata)
                VALUES (?, ?, ?, ?, ?)
            """)
            cursor.execute(query, (
                user_id,
                name,
                description,
                json.dumps(initial_messages),
                json.dumps(metadata) if metadata else None
            ))
            template_id = self.adapter.get_last_insert_id(cursor)
            conn.commit()
            logger.info(f"Created template {template_id} for user {user_id}")
            return template_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to create template: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a template by ID, including its quick replies.
        
        Args:
            template_id: Template ID
            
        Returns:
            Template dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Get template
            query = self._normalize_sql("""
                SELECT id, user_id, name, description, initial_messages, metadata,
                       created_at, updated_at
                FROM conversation_templates
                WHERE id = ?
            """)
            cursor.execute(query, (template_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            template = {
                'id': row[0],
                'user_id': row[1],
                'name': row[2],
                'description': row[3],
                'initial_messages': json.loads(row[4]) if row[4] else [],
                'metadata': json.loads(row[5]) if row[5] else {},
                'created_at': row[6],
                'updated_at': row[7]
            }
            
            # Get quick replies
            query = self._normalize_sql("""
                SELECT id, label, action, order_index, created_at
                FROM quick_replies
                WHERE template_id = ?
                ORDER BY order_index ASC, id ASC
            """)
            cursor.execute(query, (template_id,))
            quick_replies = []
            for reply_row in cursor.fetchall():
                quick_replies.append({
                    'id': reply_row[0],
                    'label': reply_row[1],
                    'action': reply_row[2],
                    'order_index': reply_row[3],
                    'created_at': reply_row[4]
                })
            
            template['quick_replies'] = quick_replies
            return template
        finally:
            self.adapter.close(conn)
    
    def list_templates(self, user_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List conversation templates, optionally filtered by user.
        
        Args:
            user_id: Optional user ID to filter by
            limit: Maximum number of templates to return
            
        Returns:
            List of template dictionaries (without quick replies)
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            if user_id:
                query = self._normalize_sql("""
                    SELECT id, user_id, name, description, initial_messages, metadata,
                           created_at, updated_at
                    FROM conversation_templates
                    WHERE user_id = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                """)
                cursor.execute(query, (user_id, limit))
            else:
                query = self._normalize_sql("""
                    SELECT id, user_id, name, description, initial_messages, metadata,
                           created_at, updated_at
                    FROM conversation_templates
                    ORDER BY updated_at DESC
                    LIMIT ?
                """)
                cursor.execute(query, (limit,))
            
            templates = []
            for row in cursor.fetchall():
                templates.append({
                    'id': row[0],
                    'user_id': row[1],
                    'name': row[2],
                    'description': row[3],
                    'initial_messages': json.loads(row[4]) if row[4] else [],
                    'metadata': json.loads(row[5]) if row[5] else {},
                    'created_at': row[6],
                    'updated_at': row[7]
                })
            
            return templates
        finally:
            self.adapter.close(conn)
    
    def update_template(
        self,
        template_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        initial_messages: Optional[List[Dict[str, str]]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update a conversation template.
        
        Args:
            template_id: Template ID
            name: New template name (optional)
            description: New description (optional)
            initial_messages: New initial messages (optional)
            metadata: New metadata (optional)
            
        Returns:
            True if updated, False if template not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Build update query dynamically
            updates = []
            params = []
            
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            if initial_messages is not None:
                updates.append("initial_messages = ?")
                params.append(json.dumps(initial_messages))
            if metadata is not None:
                updates.append("metadata = ?")
                params.append(json.dumps(metadata))
            
            if not updates:
                return False  # Nothing to update
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(template_id)
            
            query = self._normalize_sql(f"""
                UPDATE conversation_templates
                SET {', '.join(updates)}
                WHERE id = ?
            """)
            cursor.execute(query, tuple(params))
            
            updated = cursor.rowcount > 0
            conn.commit()
            
            if updated:
                logger.info(f"Updated template {template_id}")
            return updated
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update template: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def delete_template(self, template_id: int) -> bool:
        """
        Delete a conversation template (and its quick replies via CASCADE).
        
        Args:
            template_id: Template ID
            
        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                DELETE FROM conversation_templates
                WHERE id = ?
            """)
            cursor.execute(query, (template_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            if deleted:
                logger.info(f"Deleted template {template_id}")
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete template: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def add_quick_reply(
        self,
        template_id: int,
        label: str,
        action: str,
        order_index: int = 0
    ) -> int:
        """
        Add a quick reply button to a template.
        
        Args:
            template_id: Template ID
            label: Button label text
            action: Action identifier/command for the button
            order_index: Display order (lower numbers appear first)
            
        Returns:
            Quick reply ID
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                INSERT INTO quick_replies (template_id, label, action, order_index)
                VALUES (?, ?, ?, ?)
            """)
            cursor.execute(query, (template_id, label, action, order_index))
            reply_id = self.adapter.get_last_insert_id(cursor)
            conn.commit()
            logger.debug(f"Added quick reply {reply_id} to template {template_id}")
            return reply_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to add quick reply: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def update_quick_reply(
        self,
        reply_id: int,
        label: Optional[str] = None,
        action: Optional[str] = None,
        order_index: Optional[int] = None
    ) -> bool:
        """
        Update a quick reply.
        
        Args:
            reply_id: Quick reply ID
            label: New label (optional)
            action: New action (optional)
            order_index: New order index (optional)
            
        Returns:
            True if updated, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if label is not None:
                updates.append("label = ?")
                params.append(label)
            if action is not None:
                updates.append("action = ?")
                params.append(action)
            if order_index is not None:
                updates.append("order_index = ?")
                params.append(order_index)
            
            if not updates:
                return False
            
            params.append(reply_id)
            
            query = self._normalize_sql(f"""
                UPDATE quick_replies
                SET {', '.join(updates)}
                WHERE id = ?
            """)
            cursor.execute(query, tuple(params))
            updated = cursor.rowcount > 0
            conn.commit()
            return updated
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update quick reply: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def delete_quick_reply(self, reply_id: int) -> bool:
        """
        Delete a quick reply.
        
        Args:
            reply_id: Quick reply ID
            
        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                DELETE FROM quick_replies
                WHERE id = ?
            """)
            cursor.execute(query, (reply_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete quick reply: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def apply_template(
        self,
        user_id: str,
        chat_id: str,
        template_id: int
    ) -> int:
        """
        Apply a template to start a conversation.
        Creates or resets the conversation and adds initial messages from template.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            template_id: Template ID to apply
            
        Returns:
            Conversation ID
        """
        template = self.get_template(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")
        
        # Get or create conversation (reset if exists to apply template fresh)
        existing = self.get_conversation(user_id, chat_id)
        if existing:
            self.reset_conversation(user_id, chat_id)
        
        conversation_id = self.get_or_create_conversation(user_id, chat_id)
        
        # Add initial messages from template
        for msg in template['initial_messages']:
            role = msg.get('role', 'assistant')
            content = msg.get('content', '')
            tokens = msg.get('tokens')
            self.add_message(conversation_id, role, content, tokens=tokens)
        
        logger.info(f"Applied template {template_id} to conversation {conversation_id}")
        return conversation_id
    
    def get_conversation_analytics(
        self,
        user_id: str,
        chat_id: str
    ) -> Dict[str, Any]:
        """
        Get analytics metrics for a specific conversation.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            
        Returns:
            Dictionary with analytics metrics including:
            - message_count: Total number of messages
            - total_tokens: Total tokens used
            - average_response_time_seconds: Average time between user message and assistant response
            - user_engagement_score: Score based on message frequency and patterns
            - conversation_duration_seconds: Total time span of conversation
        """
        conversation = self.get_conversation(user_id, chat_id)
        if not conversation:
            return {}
        
        messages = conversation.get('messages', [])
        if not messages:
            return {
                'message_count': 0,
                'total_tokens': 0,
                'average_response_time_seconds': 0,
                'user_engagement_score': 0,
                'conversation_duration_seconds': 0
            }
        
        # Calculate response times (time between user message and next assistant message)
        response_times = []
        user_messages = []
        
        for i, msg in enumerate(messages):
            if msg['role'] == 'user':
                user_messages.append((i, msg.get('created_at')))
            elif msg['role'] == 'assistant' and user_messages:
                # Find the most recent user message
                user_idx, user_time = user_messages[-1]
                if user_idx < i:
                    assistant_time = msg.get('created_at')
                    if user_time and assistant_time:
                        try:
                            if isinstance(user_time, str):
                                user_time = parse_date(user_time)
                            if isinstance(assistant_time, str):
                                assistant_time = parse_date(assistant_time)
                            
                            if isinstance(user_time, datetime):
                                if isinstance(assistant_time, datetime):
                                    delta = (assistant_time - user_time).total_seconds()
                                    if delta > 0:
                                        response_times.append(delta)
                        except Exception as e:
                            logger.debug(f"Could not calculate response time: {e}")
        
        avg_response_time = sum(response_times) / len(response_times) if response_times else 0
        
        # Calculate engagement score (higher = more engaged)
        # Factors: message count, message frequency, response time consistency
        user_msg_count = sum(1 for msg in messages if msg['role'] == 'user')
        engagement_score = min(100, user_msg_count * 10 + (1.0 / (avg_response_time + 1)) * 10) if avg_response_time > 0 else user_msg_count * 10
        
        # Calculate conversation duration
        first_msg_time = messages[0].get('created_at') if messages else None
        last_msg_time = messages[-1].get('created_at') if messages else None
        duration = 0
        if first_msg_time and last_msg_time:
            try:
                if isinstance(first_msg_time, str):
                    first_msg_time = parse_date(first_msg_time)
                if isinstance(last_msg_time, str):
                    last_msg_time = parse_date(last_msg_time)
                
                if isinstance(first_msg_time, datetime) and isinstance(last_msg_time, datetime):
                    duration = (last_msg_time - first_msg_time).total_seconds()
            except Exception as e:
                logger.debug(f"Could not calculate duration: {e}")
        
        return {
            'message_count': conversation.get('message_count', len(messages)),
            'total_tokens': conversation.get('total_tokens', 0),
            'average_response_time_seconds': round(avg_response_time, 2),
            'user_engagement_score': round(engagement_score, 2),
            'conversation_duration_seconds': round(duration, 2),
            'response_times': [round(rt, 2) for rt in response_times],
            'user_message_count': user_msg_count,
            'assistant_message_count': sum(1 for msg in messages if msg['role'] == 'assistant')
        }
    
    def get_dashboard_analytics(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get dashboard analytics aggregating data across conversations.
        
        Args:
            start_date: Optional start date for filtering
            end_date: Optional end date for filtering
            user_id: Optional user ID to filter by
            
        Returns:
            Dictionary with dashboard metrics including:
            - total_conversations: Total number of conversations
            - active_users: Number of unique users
            - total_messages: Total messages across all conversations
            - average_response_time: Average response time across conversations
            - engagement_metrics: User engagement statistics
            - date_range: Applied date range if any
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Build WHERE clause for date and user filtering
            where_clauses = []
            params = []
            
            if user_id:
                where_clauses.append("c.user_id = ?")
                params.append(user_id)
            
            if start_date:
                where_clauses.append("c.created_at >= ?")
                params.append(start_date)
            if end_date:
                where_clauses.append("c.created_at <= ?")
                params.append(end_date)
            
            where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
            
            # Get total conversations
            query = self._normalize_sql(f"""
                SELECT COUNT(*) FROM conversations c
                {where_sql}
            """)
            cursor.execute(query, tuple(params))
            total_conversations = cursor.fetchone()[0] or 0
            
            # Get active users
            query = self._normalize_sql(f"""
                SELECT COUNT(DISTINCT user_id) FROM conversations c
                {where_sql}
            """)
            cursor.execute(query, tuple(params))
            active_users = cursor.fetchone()[0] or 0
            
            # Get total messages
            query = self._normalize_sql(f"""
                SELECT COALESCE(SUM(c.message_count), 0) FROM conversations c
                {where_sql}
            """)
            cursor.execute(query, tuple(params))
            total_messages = cursor.fetchone()[0] or 0
            
            # Calculate average response times across conversations
            # This is a simplified calculation - in production you might want more sophisticated aggregation
            conversations = self.list_conversations(user_id=user_id, limit=1000)
            response_times = []
            engagement_scores = []
            
            for conv in conversations:
                if start_date and conv.get('created_at'):
                    try:
                        conv_date = conv['created_at']
                        if isinstance(conv_date, str):
                            conv_date = parse_date(conv_date)
                        if isinstance(conv_date, datetime) and conv_date < start_date:
                            continue
                    except:
                        pass
                if end_date and conv.get('created_at'):
                    try:
                        conv_date = conv['created_at']
                        if isinstance(conv_date, str):
                            conv_date = parse_date(conv_date)
                        if isinstance(conv_date, datetime) and conv_date > end_date:
                            continue
                    except:
                        pass
                
                analytics = self.get_conversation_analytics(conv['user_id'], conv['chat_id'])
                if analytics.get('average_response_time_seconds', 0) > 0:
                    response_times.append(analytics['average_response_time_seconds'])
                if analytics.get('user_engagement_score', 0) > 0:
                    engagement_scores.append(analytics['user_engagement_score'])
            
            avg_response_time = sum(response_times) / len(response_times) if response_times else 0
            avg_engagement = sum(engagement_scores) / len(engagement_scores) if engagement_scores else 0
            
            return {
                'total_conversations': total_conversations,
                'active_users': active_users,
                'total_messages': total_messages,
                'average_response_time': round(avg_response_time, 2),
                'engagement_metrics': {
                    'average_engagement_score': round(avg_engagement, 2),
                    'high_engagement_conversations': sum(1 for s in engagement_scores if s > 70),
                    'medium_engagement_conversations': sum(1 for s in engagement_scores if 40 <= s <= 70),
                    'low_engagement_conversations': sum(1 for s in engagement_scores if s < 40)
                },
                'date_range': {
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None
                } if start_date or end_date else None
            }
        finally:
            self.adapter.close(conn)
    
    def generate_analytics_report(
        self,
        format: str = "json",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        user_id: Optional[str] = None
    ) -> Union[Dict[str, Any], str]:
        """
        Generate analytics report in specified format.
        
        Args:
            format: Report format ('json', 'csv')
            start_date: Optional start date for filtering
            end_date: Optional end date for filtering
            user_id: Optional user ID to filter by
            
        Returns:
            Report data in specified format (dict for JSON, string for CSV)
        """
        dashboard = self.get_dashboard_analytics(start_date, end_date, user_id)
        conversations = self.list_conversations(user_id=user_id, limit=1000)
        
        # Filter conversations by date if needed
        filtered_conversations = []
        for conv in conversations:
            include = True
            if start_date and conv.get('created_at'):
                try:
                    conv_date = conv['created_at']
                    if isinstance(conv_date, str):
                        conv_date = parse_date(conv_date)
                    if isinstance(conv_date, datetime) and conv_date < start_date:
                        include = False
                except:
                    pass
            if end_date and conv.get('created_at'):
                try:
                    conv_date = conv['created_at']
                    if isinstance(conv_date, str):
                        conv_date = parse_date(conv_date)
                    if isinstance(conv_date, datetime) and conv_date > end_date:
                        include = False
                except:
                    pass
            if include:
                filtered_conversations.append(conv)
        
        # Get detailed analytics for each conversation
        conversation_details = []
        for conv in filtered_conversations:
            analytics = self.get_conversation_analytics(conv['user_id'], conv['chat_id'])
            conversation_details.append({
                'user_id': conv['user_id'],
                'chat_id': conv['chat_id'],
                'created_at': conv['created_at'].isoformat() if isinstance(conv.get('created_at'), datetime) else str(conv.get('created_at', '')),
                'message_count': analytics.get('message_count', 0),
                'total_tokens': analytics.get('total_tokens', 0),
                'average_response_time_seconds': analytics.get('average_response_time_seconds', 0),
                'user_engagement_score': analytics.get('user_engagement_score', 0)
            })
        
        if format == "json":
            return {
                'report_generated_at': datetime.now().isoformat(),
                'dashboard_summary': dashboard,
                'conversations': conversation_details,
                'filters': {
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None,
                    'user_id': user_id
                }
            }
        elif format == "csv":
            import csv
            import io
            output = io.StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'User ID', 'Chat ID', 'Created At', 'Message Count',
                'Total Tokens', 'Avg Response Time (s)', 'Engagement Score'
            ])
            
            # Write data
            for conv in conversation_details:
                writer.writerow([
                    conv['user_id'],
                    conv['chat_id'],
                    conv['created_at'],
                    conv['message_count'],
                    conv['total_tokens'],
                    conv['average_response_time_seconds'],
                    conv['user_engagement_score']
                ])
            
            return output.getvalue()
        else:
            raise ValueError(f"Unsupported report format: {format}. Supported: json, csv")
    
    # Prompt Template Methods
    
    def validate_prompt_template(self, template_content: str) -> Tuple[bool, Optional[str]]:
        """
        Validate prompt template syntax.
        
        Args:
            template_content: Template content to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        try:
            # Check for balanced braces (for template variables like {variable})
            brace_count = 0
            in_brace = False
            i = 0
            
            while i < len(template_content):
                if template_content[i] == '{':
                    if in_brace:
                        return False, "Nested braces are not allowed"
                    in_brace = True
                    brace_count += 1
                elif template_content[i] == '}':
                    if not in_brace:
                        return False, "Unmatched closing brace"
                    in_brace = False
                    # Validate variable name (simple validation - alphanumeric and underscore)
                    if i > 0 and template_content[i-1] == '{':
                        return False, "Empty variable name not allowed"
                i += 1
            
            if in_brace:
                return False, "Unclosed brace in template"
            
            return True, None
        except Exception as e:
            return False, f"Template validation error: {str(e)}"
    
    def create_prompt_template(
        self,
        user_id: str,
        template_name: str,
        template_content: str,
        template_type: str = "summarization",
        conversation_id: Optional[int] = None
    ) -> int:
        """
        Create a new prompt template.
        
        Args:
            user_id: User identifier
            template_name: Name of the template
            template_content: Template content (can include {variable} syntax)
            template_type: Type of template (default: 'summarization')
            conversation_id: Optional conversation ID for per-conversation templates
            
        Returns:
            Template ID
        """
        # Validate template syntax
        is_valid, error = self.validate_prompt_template(template_content)
        if not is_valid:
            raise ValueError(f"Invalid template syntax: {error}")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # If conversation_id is provided, verify it exists and belongs to user
            if conversation_id:
                query = self._normalize_sql("""
                    SELECT id FROM conversations 
                    WHERE id = ? AND user_id = ?
                """)
                cursor.execute(query, (conversation_id, user_id))
                if not cursor.fetchone():
                    raise ValueError(f"Conversation {conversation_id} not found for user {user_id}")
            
            # Insert template
            query = self._normalize_sql("""
                INSERT INTO prompt_templates 
                (user_id, conversation_id, template_name, template_content, template_type)
                VALUES (?, ?, ?, ?, ?)
            """)
            cursor.execute(query, (user_id, conversation_id, template_name, template_content, template_type))
            template_id = self.adapter.get_last_insert_id(cursor)
            conn.commit()
            
            logger.info(f"Created prompt template {template_id} for user {user_id}")
            return template_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to create prompt template: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_prompt_template(self, template_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a prompt template by ID.
        
        Args:
            template_id: Template ID
            
        Returns:
            Template dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, user_id, conversation_id, template_name, template_content, 
                       template_type, created_at, updated_at
                FROM prompt_templates 
                WHERE id = ?
            """)
            cursor.execute(query, (template_id,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'id': row[0],
                    'user_id': row[1],
                    'conversation_id': row[2],
                    'template_name': row[3],
                    'template_content': row[4],
                    'template_type': row[5],
                    'created_at': row[6],
                    'updated_at': row[7]
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get prompt template: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_prompt_template_for_user(
        self,
        user_id: str,
        template_type: str = "summarization"
    ) -> Optional[Dict[str, Any]]:
        """
        Get prompt template for a user (per-user templates, not conversation-specific).
        
        Args:
            user_id: User identifier
            template_type: Type of template (default: 'summarization')
            
        Returns:
            Template dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, user_id, conversation_id, template_name, template_content, 
                       template_type, created_at, updated_at
                FROM prompt_templates 
                WHERE user_id = ? AND template_type = ? AND conversation_id IS NULL
                ORDER BY updated_at DESC
                LIMIT 1
            """)
            cursor.execute(query, (user_id, template_type))
            row = cursor.fetchone()
            
            if row:
                return {
                    'id': row[0],
                    'user_id': row[1],
                    'conversation_id': row[2],
                    'template_name': row[3],
                    'template_content': row[4],
                    'template_type': row[5],
                    'created_at': row[6],
                    'updated_at': row[7]
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get prompt template for user: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_prompt_template_for_conversation(
        self,
        user_id: str,
        chat_id: str,
        template_type: str = "summarization"
    ) -> Optional[Dict[str, Any]]:
        """
        Get prompt template for a conversation.
        Prefers conversation-specific templates, falls back to user templates.
        
        Args:
            user_id: User identifier
            chat_id: Chat identifier
            template_type: Type of template (default: 'summarization')
            
        Returns:
            Template dictionary or None if not found
        """
        # First try to get conversation-specific template
        conversation = self.get_conversation(user_id, chat_id)
        if conversation:
            conv_id = conversation['id']
            conn = self._get_connection()
            try:
                cursor = conn.cursor()
                query = self._normalize_sql("""
                    SELECT id, user_id, conversation_id, template_name, template_content, 
                           template_type, created_at, updated_at
                    FROM prompt_templates 
                    WHERE conversation_id = ? AND template_type = ?
                    ORDER BY updated_at DESC
                    LIMIT 1
                """)
                cursor.execute(query, (conv_id, template_type))
                row = cursor.fetchone()
                
                if row:
                    return {
                        'id': row[0],
                        'user_id': row[1],
                        'conversation_id': row[2],
                        'template_name': row[3],
                        'template_content': row[4],
                        'template_type': row[5],
                        'created_at': row[6],
                        'updated_at': row[7]
                    }
            except Exception as e:
                logger.error(f"Failed to get conversation prompt template: {e}", exc_info=True)
            finally:
                self.adapter.close(conn)
        
        # Fall back to user template
        return self.get_prompt_template_for_user(user_id, template_type)
    
    def list_prompt_templates(
        self,
        user_id: Optional[str] = None,
        template_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List prompt templates.
        
        Args:
            user_id: Optional filter by user ID
            template_type: Optional filter by template type
            
        Returns:
            List of template dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            conditions = []
            params = []
            
            if user_id:
                conditions.append("user_id = ?")
                params.append(user_id)
            
            if template_type:
                conditions.append("template_type = ?")
                params.append(template_type)
            
            where_clause = " AND ".join(conditions) if conditions else "1=1"
            
            query = self._normalize_sql(f"""
                SELECT id, user_id, conversation_id, template_name, template_content, 
                       template_type, created_at, updated_at
                FROM prompt_templates 
                WHERE {where_clause}
                ORDER BY updated_at DESC
            """)
            cursor.execute(query, params)
            
            templates = []
            for row in cursor.fetchall():
                templates.append({
                    'id': row[0],
                    'user_id': row[1],
                    'conversation_id': row[2],
                    'template_name': row[3],
                    'template_content': row[4],
                    'template_type': row[5],
                    'created_at': row[6],
                    'updated_at': row[7]
                })
            
            return templates
        except Exception as e:
            logger.error(f"Failed to list prompt templates: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def update_prompt_template(
        self,
        template_id: int,
        template_name: Optional[str] = None,
        template_content: Optional[str] = None
    ) -> bool:
        """
        Update a prompt template.
        
        Args:
            template_id: Template ID
            template_name: Optional new template name
            template_content: Optional new template content
            
        Returns:
            True if updated, False if not found
        """
        # Validate template content if provided
        if template_content:
            is_valid, error = self.validate_prompt_template(template_content)
            if not is_valid:
                raise ValueError(f"Invalid template syntax: {error}")
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if template_name:
                updates.append("template_name = ?")
                params.append(template_name)
            
            if template_content:
                updates.append("template_content = ?")
                params.append(template_content)
            
            if not updates:
                return False
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(template_id)
            
            query = self._normalize_sql(f"""
                UPDATE prompt_templates 
                SET {', '.join(updates)}
                WHERE id = ?
            """)
            cursor.execute(query, params)
            conn.commit()
            
            updated = cursor.rowcount > 0
            if updated:
                logger.info(f"Updated prompt template {template_id}")
            return updated
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update prompt template: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def delete_prompt_template(self, template_id: int) -> bool:
        """
        Delete a prompt template.
        
        Args:
            template_id: Template ID
            
        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                DELETE FROM prompt_templates 
                WHERE id = ?
            """)
            cursor.execute(query, (template_id,))
            conn.commit()
            
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted prompt template {template_id}")
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete prompt template: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    # ==================== A/B Testing Methods ====================
    
    def create_ab_test(
        self,
        name: str,
        control: Dict[str, Any],
        variant: Dict[str, Any],
        description: Optional[str] = None,
        traffic_split: float = 0.5,
        active: bool = True
    ) -> int:
        """
        Create an A/B test configuration.
        
        Args:
            name: Test name
            control: Control configuration dict (model, temperature, system_prompt, etc.)
            variant: Variant configuration dict
            description: Optional test description
            traffic_split: Fraction of traffic to send to variant (0.0-1.0)
            active: Whether test is active
            
        Returns:
            Test ID
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                INSERT INTO ab_tests (name, description, control_config, variant_config, traffic_split, active)
                VALUES (?, ?, ?, ?, ?, ?)
            """)
            cursor.execute(query, (
                name,
                description,
                json.dumps(control),
                json.dumps(variant),
                traffic_split,
                1 if active else 0
            ))
            test_id = self.adapter.get_last_insert_id(cursor)
            conn.commit()
            logger.info(f"Created A/B test {test_id}: {name}")
            return test_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to create A/B test: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_ab_test(self, test_id: int) -> Optional[Dict[str, Any]]:
        """
        Get an A/B test configuration.
        
        Args:
            test_id: Test ID
            
        Returns:
            Test configuration dict or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, name, description, control_config, variant_config, 
                       traffic_split, active, created_at, updated_at
                FROM ab_tests
                WHERE id = ?
            """)
            cursor.execute(query, (test_id,))
            row = cursor.fetchone()
            
            if row:
                return {
                    'id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'control_config': row[3],
                    'variant_config': row[4],
                    'traffic_split': row[5],
                    'active': bool(row[6]),
                    'created_at': row[7],
                    'updated_at': row[8]
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get A/B test: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def list_ab_tests(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """
        List A/B tests.
        
        Args:
            active_only: If True, only return active tests
            
        Returns:
            List of test configuration dicts
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            where_clause = "WHERE active = 1" if active_only else "1=1"
            query = self._normalize_sql(f"""
                SELECT id, name, description, control_config, variant_config, 
                       traffic_split, active, created_at, updated_at
                FROM ab_tests
                {where_clause}
                ORDER BY created_at DESC
            """)
            cursor.execute(query)
            
            tests = []
            for row in cursor.fetchall():
                tests.append({
                    'id': row[0],
                    'name': row[1],
                    'description': row[2],
                    'control_config': row[3],
                    'variant_config': row[4],
                    'traffic_split': row[5],
                    'active': bool(row[6]),
                    'created_at': row[7],
                    'updated_at': row[8]
                })
            return tests
        except Exception as e:
            logger.error(f"Failed to list A/B tests: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def update_ab_test(
        self,
        test_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        control: Optional[Dict[str, Any]] = None,
        variant: Optional[Dict[str, Any]] = None,
        traffic_split: Optional[float] = None,
        active: Optional[bool] = None
    ) -> bool:
        """
        Update an A/B test configuration.
        
        Args:
            test_id: Test ID
            name: Optional new name
            description: Optional new description
            control: Optional new control config
            variant: Optional new variant config
            traffic_split: Optional new traffic split
            active: Optional new active status
            
        Returns:
            True if updated, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            updates = []
            params = []
            
            if name is not None:
                updates.append("name = ?")
                params.append(name)
            if description is not None:
                updates.append("description = ?")
                params.append(description)
            if control is not None:
                updates.append("control_config = ?")
                params.append(json.dumps(control))
            if variant is not None:
                updates.append("variant_config = ?")
                params.append(json.dumps(variant))
            if traffic_split is not None:
                updates.append("traffic_split = ?")
                params.append(traffic_split)
            if active is not None:
                updates.append("active = ?")
                params.append(1 if active else 0)
            
            if not updates:
                return False
            
            updates.append("updated_at = CURRENT_TIMESTAMP")
            params.append(test_id)
            
            query = self._normalize_sql(f"""
                UPDATE ab_tests
                SET {', '.join(updates)}
                WHERE id = ?
            """)
            cursor.execute(query, params)
            conn.commit()
            
            updated = cursor.rowcount > 0
            if updated:
                logger.info(f"Updated A/B test {test_id}")
            return updated
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update A/B test: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def deactivate_ab_test(self, test_id: int) -> bool:
        """
        Deactivate an A/B test.
        
        Args:
            test_id: Test ID
            
        Returns:
            True if deactivated, False if not found
        """
        return self.update_ab_test(test_id, active=False)
    
    def assign_ab_variant(self, conversation_id: int, test_id: int) -> str:
        """
        Assign a variant (control or variant) to a conversation for an A/B test.
        Returns the same variant if already assigned, or assigns based on traffic split.
        
        Args:
            conversation_id: Conversation ID
            test_id: Test ID
            
        Returns:
            'control' or 'variant'
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Check if already assigned
            query = self._normalize_sql("""
                SELECT variant FROM ab_test_assignments
                WHERE test_id = ? AND conversation_id = ?
            """)
            cursor.execute(query, (test_id, conversation_id))
            row = cursor.fetchone()
            
            if row:
                return row[0]
            
            # Get test configuration
            test = self.get_ab_test(test_id)
            if not test:
                raise ValueError(f"A/B test {test_id} not found")
            if not test['active']:
                # If test is inactive, default to control
                variant = 'control'
            else:
                # Assign based on traffic split using hash of conversation_id
                # This ensures consistent assignment
                import hashlib
                hash_val = int(hashlib.md5(f"{test_id}_{conversation_id}".encode()).hexdigest(), 16)
                threshold = test['traffic_split'] * (2**128)
                variant = 'variant' if hash_val < threshold else 'control'
            
            # Store assignment
            query = self._normalize_sql("""
                INSERT INTO ab_test_assignments (test_id, conversation_id, variant)
                VALUES (?, ?, ?)
            """)
            cursor.execute(query, (test_id, conversation_id, variant))
            conn.commit()
            
            logger.debug(f"Assigned variant {variant} to conversation {conversation_id} for test {test_id}")
            return variant
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to assign A/B variant: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def record_ab_metric(
        self,
        test_id: int,
        conversation_id: int,
        variant: str,
        response_time_ms: Optional[int] = None,
        tokens_used: Optional[int] = None,
        user_satisfaction_score: Optional[float] = None,
        error_occurred: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        Record metrics for an A/B test response.
        
        Args:
            test_id: Test ID
            conversation_id: Conversation ID
            variant: 'control' or 'variant'
            response_time_ms: Response time in milliseconds
            tokens_used: Number of tokens used
            user_satisfaction_score: User satisfaction score (0.0-5.0)
            error_occurred: Whether an error occurred
            metadata: Optional additional metadata
            
        Returns:
            Metric ID
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                INSERT INTO ab_test_metrics 
                (test_id, conversation_id, variant, response_time_ms, tokens_used, 
                 user_satisfaction_score, error_occurred, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """)
            cursor.execute(query, (
                test_id,
                conversation_id,
                variant,
                response_time_ms,
                tokens_used,
                user_satisfaction_score,
                1 if error_occurred else 0,
                json.dumps(metadata) if metadata else None
            ))
            metric_id = self.adapter.get_last_insert_id(cursor)
            conn.commit()
            logger.debug(f"Recorded A/B metric {metric_id} for test {test_id}, variant {variant}")
            return metric_id
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to record A/B metric: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_ab_metrics(self, test_id: int, variant: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get metrics for an A/B test.
        
        Args:
            test_id: Test ID
            variant: Optional filter by variant ('control' or 'variant')
            
        Returns:
            List of metric dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            where_clause = "WHERE test_id = ?"
            params = [test_id]
            
            if variant:
                where_clause += " AND variant = ?"
                params.append(variant)
            
            query = self._normalize_sql(f"""
                SELECT id, test_id, conversation_id, variant, response_time_ms, tokens_used,
                       user_satisfaction_score, error_occurred, metadata, recorded_at
                FROM ab_test_metrics
                {where_clause}
                ORDER BY recorded_at DESC
            """)
            cursor.execute(query, params)
            
            metrics = []
            for row in cursor.fetchall():
                metrics.append({
                    'id': row[0],
                    'test_id': row[1],
                    'conversation_id': row[2],
                    'variant': row[3],
                    'response_time_ms': row[4],
                    'tokens_used': row[5],
                    'user_satisfaction_score': row[6],
                    'error_occurred': bool(row[7]),
                    'metadata': json.loads(row[8]) if row[8] else None,
                    'recorded_at': row[9]
                })
            return metrics
        except Exception as e:
            logger.error(f"Failed to get A/B metrics: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_ab_statistics(self, test_id: int) -> Dict[str, Any]:
        """
        Get statistical analysis of A/B test results.
        
        Args:
            test_id: Test ID
            
        Returns:
            Dictionary with statistics for control and variant groups
        """
        import statistics
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Get metrics for both variants
            control_metrics = self.get_ab_metrics(test_id, variant='control')
            variant_metrics = self.get_ab_metrics(test_id, variant='variant')
            
            def calculate_stats(metrics: List[Dict[str, Any]]) -> Dict[str, Any]:
                if not metrics:
                    return {
                        'count': 0,
                        'avg_response_time_ms': None,
                        'avg_tokens_used': None,
                        'avg_satisfaction_score': None,
                        'error_rate': None
                    }
                
                response_times = [m['response_time_ms'] for m in metrics if m['response_time_ms'] is not None]
                tokens = [m['tokens_used'] for m in metrics if m['tokens_used'] is not None]
                satisfaction_scores = [m['user_satisfaction_score'] for m in metrics if m['user_satisfaction_score'] is not None]
                errors = sum(1 for m in metrics if m['error_occurred'])
                
                return {
                    'count': len(metrics),
                    'avg_response_time_ms': statistics.mean(response_times) if response_times else None,
                    'median_response_time_ms': statistics.median(response_times) if response_times else None,
                    'avg_tokens_used': statistics.mean(tokens) if tokens else None,
                    'avg_satisfaction_score': statistics.mean(satisfaction_scores) if satisfaction_scores else None,
                    'error_rate': errors / len(metrics) if metrics else None
                }
            
            control_stats = calculate_stats(control_metrics)
            variant_stats = calculate_stats(variant_metrics)
            
            return {
                'test_id': test_id,
                'total_samples': len(control_metrics) + len(variant_metrics),
                'control': control_stats,
                'variant': variant_stats
            }
        except Exception as e:
            logger.error(f"Failed to get A/B statistics: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def create_share(
        self,
        user_id: str,
        chat_id: str,
        shared_with_user_id: Optional[str] = None,
        permission: str = "read_only",
        share_token: Optional[str] = None
    ) -> int:
        """
        Create a share for a conversation.
        
        Args:
            user_id: Owner's user ID
            chat_id: Chat/conversation identifier
            shared_with_user_id: User ID to share with (optional, for direct sharing)
            permission: 'read_only' or 'editable'
            share_token: Optional custom share token (auto-generated if not provided)
            
        Returns:
            Share ID
            
        Raises:
            ValueError: If conversation not found, invalid permission, or duplicate token
        """
        if permission not in ('read_only', 'editable'):
            raise ValueError("Permission must be 'read_only' or 'editable'")
        
        # Get conversation ID
        conversation_id = self.get_or_create_conversation(user_id, chat_id)
        if not conversation_id:
            raise ValueError(f"Conversation not found for user {user_id}, chat {chat_id}")
        
        # Generate token if not provided
        if not share_token:
            share_token = secrets.token_urlsafe(32)
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            
            # Check if token already exists
            query = self._normalize_sql(
                "SELECT id FROM conversation_shares WHERE share_token = ?"
            )
            cursor.execute(query, (share_token,))
            if cursor.fetchone():
                raise ValueError("Share token already exists")
            
            # Insert share
            query = self._normalize_sql("""
                INSERT INTO conversation_shares (
                    conversation_id, owner_user_id, shared_with_user_id,
                    share_token, permission
                )
                VALUES (?, ?, ?, ?, ?)
            """)
            cursor.execute(query, (
                conversation_id,
                user_id,
                shared_with_user_id,
                share_token,
                permission
            ))
            share_id = self.adapter.get_last_insert_id(cursor)
            conn.commit()
            logger.info(f"Created share {share_id} for conversation {conversation_id}")
            return share_id
        except ValueError:
            raise
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to create share: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_share(self, share_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a share by ID.
        
        Args:
            share_id: Share ID
            
        Returns:
            Share dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, conversation_id, owner_user_id, shared_with_user_id,
                       share_token, permission, created_at
                FROM conversation_shares
                WHERE id = ?
            """)
            cursor.execute(query, (share_id,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return {
                'id': row[0],
                'conversation_id': row[1],
                'owner_user_id': row[2],
                'shared_with_user_id': row[3],
                'share_token': row[4],
                'permission': row[5],
                'created_at': row[6]
            }
        except Exception as e:
            logger.error(f"Failed to get share: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_share_by_token(self, share_token: str) -> Optional[Dict[str, Any]]:
        """
        Get a share by its token.
        
        Args:
            share_token: Share token
            
        Returns:
            Share dictionary or None if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, conversation_id, owner_user_id, shared_with_user_id,
                       share_token, permission, created_at
                FROM conversation_shares
                WHERE share_token = ?
            """)
            cursor.execute(query, (share_token,))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return {
                'id': row[0],
                'conversation_id': row[1],
                'owner_user_id': row[2],
                'shared_with_user_id': row[3],
                'share_token': row[4],
                'permission': row[5],
                'created_at': row[6]
            }
        except Exception as e:
            logger.error(f"Failed to get share by token: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def list_shares_for_conversation(
        self,
        user_id: str,
        chat_id: str
    ) -> List[Dict[str, Any]]:
        """
        List all shares for a conversation.
        
        Args:
            user_id: Owner's user ID
            chat_id: Chat/conversation identifier
            
        Returns:
            List of share dictionaries
        """
        conversation_id = self.get_or_create_conversation(user_id, chat_id)
        if not conversation_id:
            return []
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, conversation_id, owner_user_id, shared_with_user_id,
                       share_token, permission, created_at
                FROM conversation_shares
                WHERE conversation_id = ?
                ORDER BY created_at DESC
            """)
            cursor.execute(query, (conversation_id,))
            
            shares = []
            for row in cursor.fetchall():
                shares.append({
                    'id': row[0],
                    'conversation_id': row[1],
                    'owner_user_id': row[2],
                    'shared_with_user_id': row[3],
                    'share_token': row[4],
                    'permission': row[5],
                    'created_at': row[6]
                })
            return shares
        except Exception as e:
            logger.error(f"Failed to list shares: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def list_shares_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        """
        List all shares where a user is the recipient.
        
        Args:
            user_id: User ID
            
        Returns:
            List of share dictionaries
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, conversation_id, owner_user_id, shared_with_user_id,
                       share_token, permission, created_at
                FROM conversation_shares
                WHERE shared_with_user_id = ?
                ORDER BY created_at DESC
            """)
            cursor.execute(query, (user_id,))
            
            shares = []
            for row in cursor.fetchall():
                shares.append({
                    'id': row[0],
                    'conversation_id': row[1],
                    'owner_user_id': row[2],
                    'shared_with_user_id': row[3],
                    'share_token': row[4],
                    'permission': row[5],
                    'created_at': row[6]
                })
            return shares
        except Exception as e:
            logger.error(f"Failed to list shares for user: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def delete_share(self, share_id: int) -> bool:
        """
        Delete a share.
        
        Args:
            share_id: Share ID
            
        Returns:
            True if deleted, False if not found
        """
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql(
                "DELETE FROM conversation_shares WHERE id = ?"
            )
            cursor.execute(query, (share_id,))
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted share {share_id}")
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete share: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def check_conversation_access(
        self,
        user_id: str,
        chat_id: str,
        accessed_by_user_id: str
    ) -> Dict[str, Any]:
        """
        Check if a user has access to a conversation and what permissions.
        
        Args:
            user_id: Owner's user ID
            chat_id: Chat/conversation identifier
            accessed_by_user_id: User ID requesting access
            
        Returns:
            Dictionary with access information:
            - has_access: bool
            - can_read: bool
            - can_write: bool
            - permission: 'owner', 'read_only', 'editable', or None
        """
        # Owner has full access
        if accessed_by_user_id == user_id:
            return {
                'has_access': True,
                'can_read': True,
                'can_write': True,
                'permission': 'owner'
            }
        
        # Check for shares
        conversation_id = self.get_or_create_conversation(user_id, chat_id)
        if not conversation_id:
            return {
                'has_access': False,
                'can_read': False,
                'can_write': False,
                'permission': None
            }
        
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT permission
                FROM conversation_shares
                WHERE conversation_id = ? AND shared_with_user_id = ?
            """)
            cursor.execute(query, (conversation_id, accessed_by_user_id))
            row = cursor.fetchone()
            
            if not row:
                return {
                    'has_access': False,
                    'can_read': False,
                    'can_write': False,
                    'permission': None
                }
            
            permission = row[0]
            return {
                'has_access': True,
                'can_read': True,
                'can_write': permission == 'editable',
                'permission': permission
            }
        except Exception as e:
            logger.error(f"Failed to check access: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
    
    def get_conversation_by_share_token(
        self,
        share_token: str,
        limit: Optional[int] = None,
        max_tokens: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get a conversation using a share token.
        
        Args:
            share_token: Share token
            limit: Maximum number of messages to return
            max_tokens: Maximum tokens (oldest messages pruned first)
            
        Returns:
            Conversation dictionary or None if token invalid
        """
        share = self.get_share_by_token(share_token)
        if not share:
            return None
        
        # Get conversation via conversation_id
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            query = self._normalize_sql("""
                SELECT id, user_id, chat_id, created_at, updated_at,
                       last_message_at, message_count, total_tokens, metadata
                FROM conversations
                WHERE id = ?
            """)
            cursor.execute(query, (share['conversation_id'],))
            row = cursor.fetchone()
            
            if not row:
                return None
            
            conversation = {
                'id': row[0],
                'user_id': row[1],
                'chat_id': row[2],
                'created_at': row[3],
                'updated_at': row[4],
                'last_message_at': row[5],
                'message_count': row[6],
                'total_tokens': row[7],
                'metadata': json.loads(row[8]) if row[8] else {}
            }
            
            # Get messages
            query = self._normalize_sql("""
                SELECT id, role, content, tokens, created_at
                FROM conversation_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
            """)
            
            if max_tokens:
                # For token-limited queries, we need to get all and prune
                cursor.execute(query, (share['conversation_id'],))
                all_messages = []
                total_tokens = 0
                
                for msg_row in cursor.fetchall():
                    all_messages.append({
                        'id': msg_row[0],
                        'role': msg_row[1],
                        'content': msg_row[2],
                        'tokens': msg_row[3],
                        'created_at': msg_row[4]
                    })
                    total_tokens += msg_row[3] or 0
                
                # Prune oldest messages if over token limit
                while total_tokens > max_tokens and len(all_messages) > 5:
                    removed = all_messages.pop(0)
                    total_tokens -= removed['tokens'] or 0
                
                conversation['messages'] = all_messages
            elif limit:
                # Limit by message count
                query += f" LIMIT {limit}"
                cursor.execute(query, (share['conversation_id'],))
                conversation['messages'] = [
                    {
                        'id': row[0],
                        'role': row[1],
                        'content': row[2],
                        'tokens': row[3],
                        'created_at': row[4]
                    }
                    for row in cursor.fetchall()
                ]
            else:
                cursor.execute(query, (share['conversation_id'],))
                conversation['messages'] = [
                    {
                        'id': row[0],
                        'role': row[1],
                        'content': row[2],
                        'tokens': row[3],
                        'created_at': row[4]
                    }
                    for row in cursor.fetchall()
                ]
            
            return conversation
        except Exception as e:
            logger.error(f"Failed to get conversation by share token: {e}", exc_info=True)
            raise
        finally:
            self.adapter.close(conn)
