#!/usr/bin/env python3
"""
Parser for Cursor Agent JSON output.
Extracts human-readable content from agent logs.
"""
import json
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional


def format_timestamp(ts: Optional[str]) -> str:
    """Format timestamp for display."""
    if not ts:
        return ""
    try:
        # Try to parse and format timestamp
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        return dt.strftime("%H:%M:%S")
    except:
        return ts


def extract_tool_call(tool_call: Dict[str, Any]) -> str:
    """Extract human-readable tool call information."""
    tool_name = tool_call.get("name", "unknown")
    args = tool_call.get("arguments", {})
    
    # Format tool call based on type
    if tool_name == "run_terminal_cmd":
        cmd = args.get("command", "")
        # Truncate long commands
        if len(cmd) > 80:
            cmd = cmd[:77] + "..."
        return f"  → Running: {cmd}"
    elif tool_name == "read_file":
        file_path = args.get("target_file", "")
        return f"  → Reading: {file_path}"
    elif tool_name == "write":
        file_path = args.get("file_path", "")
        return f"  → Writing: {file_path}"
    elif tool_name == "search_replace":
        file_path = args.get("file_path", "")
        return f"  → Editing: {file_path}"
    elif tool_name == "grep":
        pattern = args.get("pattern", "")
        path = args.get("path", "")
        return f"  → Searching: {pattern[:50]} in {path}"
    else:
        return f"  → {tool_name}({', '.join(f'{k}={v}' for k, v in list(args.items())[:2])})"


def extract_tool_result(tool_result: Dict[str, Any]) -> str:
    """Extract human-readable tool result information."""
    content = tool_result.get("content", "")
    
    # For terminal commands, show exit code and truncated output
    if isinstance(content, str):
        lines = content.split('\n')
        if len(lines) > 10:
            content = '\n'.join(lines[:10]) + f"\n    ... ({len(lines) - 10} more lines)"
        if content.strip():
            # Indent output
            indented = '\n'.join(f"    {line}" for line in content.split('\n'))
            return f"    {indented}"
    
    return ""


def extract_message(message: Dict[str, Any]) -> Optional[str]:
    """Extract human-readable message content."""
    role = message.get("role", "")
    content = message.get("content", "")
    
    if role == "user":
        if isinstance(content, str) and content.strip():
            return f"👤 User: {content[:200]}{'...' if len(content) > 200 else ''}"
    elif role == "assistant":
        if isinstance(content, str) and content.strip():
            # Extract text content (may be markdown)
            return f"🤖 Agent: {content[:300]}{'...' if len(content) > 300 else ''}"
    
    return None


def parse_agent_output(line: str) -> Optional[str]:
    """Parse a single line of agent JSON output."""
    if not line.strip():
        return None
    
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        # Not JSON, might be plain text - return as is
        if line.strip() and not line.startswith('{'):
            return line
        return None
    
    # Extract different types of messages
    output_parts = []
    
    # Handle Cursor's format: type-based entries
    entry_type = data.get("type", "")
    subtype = data.get("subtype", "")
    
    # Tool call entries (Cursor format)
    if entry_type == "tool_call":
        if subtype == "started":
            tool_call = data.get("tool_call", {})
            if not tool_call:
                tool_call = data
            
            # Cursor uses nested structures like readToolCall, mcpToolCall, etc.
            tool_name = None
            args = {}
            
            # Check for nested tool call structures
            if "readToolCall" in tool_call:
                tool_name = "read"
                args = tool_call["readToolCall"].get("args", {})
            elif "writeToolCall" in tool_call:
                tool_name = "write"
                args = tool_call["writeToolCall"].get("args", {})
            elif "searchReplaceToolCall" in tool_call:
                tool_name = "search_replace"
                args = tool_call["searchReplaceToolCall"].get("args", {})
            elif "runTerminalCommandToolCall" in tool_call:
                tool_name = "run_terminal"
                args = tool_call["runTerminalCommandToolCall"].get("args", {})
            elif "grepToolCall" in tool_call:
                tool_name = "grep"
                args = tool_call["grepToolCall"].get("args", {})
            elif "mcpToolCall" in tool_call:
                # MCP tool calls
                mcp_args = tool_call["mcpToolCall"].get("args", {})
                tool_name = mcp_args.get("toolName", mcp_args.get("name", "mcp"))
                args = mcp_args.get("args", {})
                
                # Format MCP tool calls
                if "complete_task" in tool_name.lower():
                    task_id = args.get("task_id", "?")
                    output_parts.append(f"✅ Completing task {task_id}")
                elif "reserve_task" in tool_name.lower():
                    task_id = args.get("task_id", "?")
                    output_parts.append(f"🔒 Reserving task {task_id}")
                elif "create_task" in tool_name.lower():
                    title = args.get("title", "")
                    output_parts.append(f"➕ Creating task: {title[:50] if title else 'new task'}")
                elif "list_available_tasks" in tool_name.lower():
                    agent_type = args.get("agent_type", "?")
                    output_parts.append(f"📋 Listing available tasks ({agent_type})")
                elif "query_tasks" in tool_name.lower():
                    status = args.get("task_status", "?")
                    output_parts.append(f"🔍 Querying tasks (status: {status})")
                else:
                    output_parts.append(f"🔧 MCP: {tool_name}")
                # Skip further processing for MCP calls
                if output_parts:
                    return "\n".join(output_parts)
            else:
                # Fallback: check for direct name/arguments
                tool_name = tool_call.get("name", "unknown")
                args = tool_call.get("arguments", tool_call.get("args", {}))
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except:
                        args = {}
            
            # Format standard tool calls
            if tool_name == "read":
                path = args.get("path", args.get("target_file", "?"))
                output_parts.append(f"  → Reading: {path}")
            elif tool_name == "write":
                path = args.get("path", args.get("file_path", "?"))
                output_parts.append(f"  → Writing: {path}")
            elif tool_name == "search_replace":
                path = args.get("path", args.get("file_path", "?"))
                output_parts.append(f"  → Editing: {path}")
            elif tool_name == "run_terminal":
                cmd = args.get("command", "?")
                if len(cmd) > 80:
                    cmd = cmd[:77] + "..."
                output_parts.append(f"  → Running: {cmd}")
            elif tool_name == "grep":
                pattern = args.get("pattern", "?")
                path = args.get("path", "?")
                output_parts.append(f"  → Searching: {pattern[:50]} in {path}")
            elif tool_name and tool_name != "unknown":
                # Generic tool call
                output_parts.append(f"  → {tool_name}")
        elif subtype == "completed":
            # Tool call completed - usually followed by result
            pass
    
    # Result entries (Cursor format) - this is the important one!
    if entry_type == "result":
        result_content = data.get("result", "")
        is_error = data.get("is_error", False)
        duration_ms = data.get("duration_ms", 0)
        
        if isinstance(result_content, str) and result_content.strip():
            # This contains the actual execution summary!
            if is_error:
                output_parts.append(f"❌ Error: {result_content[:500]}{'...' if len(result_content) > 500 else ''}")
            else:
                # Extract key information from result
                import re
                
                # Extract task IDs mentioned
                task_ids = re.findall(r'task\s+(\d+)', result_content, re.IGNORECASE)
                task_ids.extend(re.findall(r'Task\s+(\d+)', result_content))
                
                # Check for task completion
                if "complete" in result_content.lower() or "verified" in result_content.lower():
                    if task_ids:
                        unique_ids = list(set(task_ids))[:10]
                        output_parts.append(f"✅ Completed tasks: {', '.join(unique_ids)}")
                    else:
                        output_parts.append(f"✅ Task operation completed")
                
                # Check for task reservation
                if "reserv" in result_content.lower() or "lock" in result_content.lower():
                    if task_ids:
                        output_parts.append(f"🔒 Reserved task: {task_ids[0]}")
                    else:
                        output_parts.append(f"🔒 Task reserved")
                
                # Extract summary (look for "Summary" section or first paragraph)
                summary_match = re.search(r'##\s+Summary\s*\n(.*?)(?=\n\n|\Z)', result_content, re.DOTALL | re.IGNORECASE)
                if summary_match:
                    summary = summary_match.group(1).strip()
                    # Clean up markdown
                    summary = re.sub(r'\*\*([^*]+)\*\*', r'\1', summary)  # Remove bold
                    summary = re.sub(r'#+\s*', '', summary)  # Remove headers
                    if len(summary) > 300:
                        summary = summary[:300] + "..."
                    output_parts.append(f"📋 Summary: {summary}")
                else:
                    # Show first meaningful paragraph
                    lines = [l.strip() for l in result_content.split('\n') if l.strip() and not l.strip().startswith('#')]
                    if lines:
                        first_line = lines[0]
                        if len(first_line) > 200:
                            first_line = first_line[:200] + "..."
                        output_parts.append(f"📋 {first_line}")
                
                # Show duration if significant
                if duration_ms > 5000:
                    output_parts.append(f"⏱️  Duration: {duration_ms/1000:.1f}s")
    
    # Assistant message entries (Cursor format)
    if entry_type == "assistant":
        message = data.get("message", {})
        if message:
            msg = extract_message(message)
            if msg:
                output_parts.append(msg)
    
    # User message entries
    if entry_type == "user":
        message = data.get("message", {})
        if message:
            msg = extract_message(message)
            if msg:
                output_parts.append(msg)
    
    # Thinking entries (can be skipped or shown briefly)
    if entry_type == "thinking" and subtype == "completed":
        # Just mark that thinking completed
        pass
    
    # Legacy format: Check for tool calls (old format)
    if "tool_calls" in data:
        for tool_call in data.get("tool_calls", []):
            output_parts.append(extract_tool_call(tool_call))
    
    # Legacy format: Check for tool results
    if "tool_results" in data:
        for tool_result in data.get("tool_results", []):
            result = extract_tool_result(tool_result)
            if result:
                output_parts.append(result)
    
    # Legacy format: Check for messages
    if "messages" in data:
        for message in data.get("messages", []):
            msg = extract_message(message)
            if msg:
                output_parts.append(msg)
    
    # Check for direct content (various formats)
    if "content" in data:
        content = data["content"]
        if isinstance(content, str) and content.strip():
            # Truncate very long content
            display_content = content[:500] + ('...' if len(content) > 500 else '')
            output_parts.append(f"📝 {display_content}")
        elif isinstance(content, list):
            # Handle list of content blocks
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    text = item["text"]
                    if text.strip():
                        output_parts.append(f"📝 {text[:200]}{'...' if len(text) > 200 else ''}")
    
    # Check for text field
    if "text" in data and isinstance(data["text"], str):
        text = data["text"].strip()
        if text:
            output_parts.append(f"📝 {text[:200]}{'...' if len(text) > 200 else ''}")
    
    # Check for error messages
    if "error" in data:
        error_msg = str(data["error"])
        output_parts.append(f"❌ Error: {error_msg}")
    
    # Check for status/progress
    if "status" in data:
        status = data["status"]
        if status != "ok":
            output_parts.append(f"⚠️  Status: {status}")
    
    # Check for function/tool name
    if "function" in data:
        func_name = data["function"]
        output_parts.append(f"🔧 Function: {func_name}")
    
    # Check for task-related MCP operations
    if "method" in data:
        method = data.get("method", "")
        params = data.get("params", {})
        result = data.get("result", {})
        
        # Task operations
        if "task" in method.lower():
            if "complete" in method.lower():
                task_id = params.get("task_id") or result.get("task_id", "?")
                output_parts.append(f"✅ Task {task_id} completed")
            elif "reserve" in method.lower() or "lock" in method.lower():
                task_id = params.get("task_id") or result.get("task_id", "?")
                output_parts.append(f"🔒 Task {task_id} reserved/locked")
            elif "unlock" in method.lower():
                task_id = params.get("task_id") or result.get("task_id", "?")
                output_parts.append(f"🔓 Task {task_id} unlocked")
            elif "create" in method.lower():
                task_id = result.get("task_id") or result.get("id", "?")
                title = params.get("title", result.get("title", ""))
                if title:
                    output_parts.append(f"➕ Created task {task_id}: {title[:50]}")
                else:
                    output_parts.append(f"➕ Created task {task_id}")
            elif "update" in method.lower():
                task_id = params.get("task_id") or result.get("task_id", "?")
                output_parts.append(f"📝 Updated task {task_id}")
            else:
                # Generic task method
                output_parts.append(f"📋 Task operation: {method}")
    
    # Check for MCP response with task info
    if "result" in data and isinstance(data["result"], dict):
        result = data["result"]
        if "task_id" in result or "task" in str(result).lower():
            if "success" in result:
                if result.get("success"):
                    output_parts.append(f"✅ Task operation succeeded")
                else:
                    output_parts.append(f"❌ Task operation failed: {result.get('error', 'Unknown error')}")
    
    # Check for task updates/progress
    if "update_type" in data:
        update_type = data["update_type"]
        content = data.get("content", data.get("text", ""))
        if content:
            output_parts.append(f"📊 {update_type}: {content[:100]}{'...' if len(content) > 100 else ''}")
    
    # Check for notes/comments
    if "notes" in data and data["notes"]:
        notes = str(data["notes"])
        output_parts.append(f"📝 Notes: {notes[:100]}{'...' if len(notes) > 100 else ''}")
    
    # If we found anything, return it
    if output_parts:
        return "\n".join(output_parts)
    
    return None


def main():
    """Main parser function."""
    # Don't print header if output is being piped (non-interactive)
    if sys.stdout.isatty():
        print("=" * 80)
        print("Cursor Agent Log Parser")
        print("=" * 80)
        print()
    
    line_count = 0
    parsed_count = 0
    last_output = None
    
    try:
        for line in sys.stdin:
            line_count += 1
            original_line = line
            line = line.strip()
            
            if not line:
                continue
            
            # Try to parse as JSON
            parsed = parse_agent_output(line)
            
            if parsed:
                # Avoid duplicate consecutive outputs
                if parsed != last_output:
                    parsed_count += 1
                    print(parsed)
                    print()  # Blank line between entries
                    last_output = parsed
    
    except KeyboardInterrupt:
        if sys.stdout.isatty():
            print("\n\nParser interrupted by user")
        sys.exit(0)
    except BrokenPipeError:
        # Handle case where output is piped and reader closes early
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Parser error: {e}", file=sys.stderr)
        # Print the problematic line for debugging
        if 'line' in locals():
            print(f"Problematic line: {line[:200]}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

