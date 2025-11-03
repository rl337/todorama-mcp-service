#!/usr/bin/env python3
"""
Analyze cursor-agent.log to understand agent behavior.

This script parses the JSON log file and provides insights into:
- Tasks worked on
- Tool calls made
- Success/failure rates
- Looping behavior
- Timeline of actions
"""

import json
import sys
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class TaskActivity:
    """Track activity for a specific task."""
    task_id: int
    updates: List[Dict] = field(default_factory=list)
    completions: List[Dict] = field(default_factory=list)
    unlocks: List[Dict] = field(default_factory=list)
    reservations: List[Dict] = field(default_factory=list)
    other_calls: List[Dict] = field(default_factory=list)
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


@dataclass
class ToolCall:
    """Represents a tool call from the log."""
    timestamp: int
    timestamp_str: str
    tool_name: str
    tool_type: str  # 'mcpToolCall', 'shellToolCall', etc.
    args: Dict[str, Any]
    result: Optional[Dict] = None
    status: str = "unknown"  # 'started', 'completed', 'failed'
    error: Optional[str] = None


def parse_timestamp(ts_ms: int) -> str:
    """Convert milliseconds timestamp to readable string."""
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return f"ts:{ts_ms}"


def extract_task_id(tool_call: Dict) -> Optional[int]:
    """Extract task_id from a tool call."""
    if 'mcpToolCall' in tool_call:
        args = tool_call['mcpToolCall'].get('args', {})
        tool_args = args.get('args', {})
        return tool_args.get('task_id')
    return None


def parse_log_file(log_path: str) -> tuple[List[ToolCall], Dict[int, TaskActivity]]:
    """Parse the log file and extract tool calls and task activities.
    
    The log file is JSONL format - each line is a separate JSON object.
    Some lines may be plain text from the shell script wrapper.
    """
    tool_calls: List[ToolCall] = []
    task_activities: Dict[int, TaskActivity] = {}
    parsed_lines = 0
    skipped_lines = 0
    
    with open(log_path, 'r') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            
            # Skip plain text log lines (from shell script)
            if not line.startswith('{'):
                continue
            
            try:
                data = json.loads(line)
                parsed_lines += 1
            except json.JSONDecodeError:
                skipped_lines += 1
                continue
            
            # Extract tool calls
            if 'tool_call' in data:
                tool_call_data = data['tool_call']
                timestamp_ms = data.get('timestamp_ms', 0)
                timestamp_str = parse_timestamp(timestamp_ms)
                subtype = data.get('subtype', 'unknown')
                
                # Handle MCP tool calls
                if 'mcpToolCall' in tool_call_data:
                    mcp_call = tool_call_data['mcpToolCall']
                    tool_name = mcp_call.get('args', {}).get('name', 'unknown')
                    tool_args = mcp_call.get('args', {}).get('args', {})
                    
                    tool_call = ToolCall(
                        timestamp=timestamp_ms,
                        timestamp_str=timestamp_str,
                        tool_name=tool_name,
                        tool_type='mcpToolCall',
                        args=tool_args,
                        result=tool_call_data.get('result'),
                        status=subtype
                    )
                    tool_calls.append(tool_call)
                    
                    # Track task-specific activity
                    task_id = tool_args.get('task_id')
                    if task_id:
                        # Ensure task_id is an int for consistency
                        try:
                            task_id = int(task_id)
                        except (ValueError, TypeError):
                            pass
                        
                        if task_id not in task_activities:
                            task_activities[task_id] = TaskActivity(task_id=task_id)
                        
                        activity = task_activities[task_id]
                        activity.last_seen = timestamp_str
                        if activity.first_seen is None:
                            activity.first_seen = timestamp_str
                        
                        if tool_name == 'todo-add_task_update':
                            activity.updates.append({
                                'timestamp': timestamp_str,
                                'timestamp_ms': timestamp_ms,
                                'content': tool_args.get('content', '')[:100],
                                'update_type': tool_args.get('update_type', 'unknown'),
                                'status': subtype
                            })
                        elif tool_name == 'todo-complete_task':
                            activity.completions.append({
                                'timestamp': timestamp_str,
                                'timestamp_ms': timestamp_ms,
                                'status': subtype,
                                'result': tool_call_data.get('result'),
                                'notes': tool_args.get('notes', '')[:100]
                            })
                        elif tool_name == 'todo-unlock_task':
                            activity.unlocks.append({
                                'timestamp': timestamp_str,
                                'timestamp_ms': timestamp_ms,
                                'status': subtype
                            })
                        elif tool_name == 'todo-reserve_task':
                            activity.reservations.append({
                                'timestamp': timestamp_str,
                                'timestamp_ms': timestamp_ms,
                                'status': subtype,
                                'agent_id': tool_args.get('agent_id')
                            })
                        else:
                            activity.other_calls.append({
                                'timestamp': timestamp_str,
                                'tool_name': tool_name,
                                'status': subtype
                            })
                
                # Handle shell tool calls
                elif 'shellToolCall' in tool_call_data:
                    shell_call = tool_call_data['shellToolCall']
                    command = shell_call.get('args', {}).get('command', 'unknown')
                    
                    tool_call = ToolCall(
                        timestamp=timestamp_ms,
                        timestamp_str=timestamp_str,
                        tool_name='shell_command',
                        tool_type='shellToolCall',
                        args={'command': command},
                        result=tool_call_data.get('result'),
                        status=subtype
                    )
                    tool_calls.append(tool_call)
    
    return tool_calls, task_activities


def print_summary(tool_calls: List[ToolCall], task_activities: Dict[int, TaskActivity]):
    """Print a summary of agent activity."""
    print("=" * 80)
    print("CURSOR AGENT LOG ANALYSIS")
    print("=" * 80)
    print()
    
    # Overall stats
    print(f"Total tool calls: {len(tool_calls)}")
    print(f"Tasks worked on: {len(task_activities)}")
    print()
    
    # Tool call breakdown
    tool_counts = defaultdict(int)
    for call in tool_calls:
        tool_counts[call.tool_name] += 1
    
    print("Tool Call Breakdown:")
    print("-" * 80)
    for tool, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
        print(f"  {tool:30s}: {count:4d}")
    print()
    
    # Task-specific activity
    print("=" * 80)
    print("TASK-SPECIFIC ACTIVITY")
    print("=" * 80)
    print()
    
    for task_id in sorted(task_activities.keys(), key=lambda x: (isinstance(x, str), x if isinstance(x, int) else 0)):
        activity = task_activities[task_id]
        print(f"Task #{task_id}:")
        print(f"  First seen:  {activity.first_seen}")
        print(f"  Last seen:   {activity.last_seen}")
        print(f"  Updates:     {len(activity.updates)}")
        print(f"  Completions: {len(activity.completions)}")
        print(f"  Unlocks:     {len(activity.unlocks)}")
        print(f"  Reservations: {len(activity.reservations)}")
        print(f"  Other calls: {len(activity.other_calls)}")
        
        # Show completion status
        if activity.completions:
            for comp in activity.completions:
                status = comp['status']
                result = comp.get('result')
                if result and isinstance(result, dict):
                    success_obj = result.get('success')
                    if success_obj:
                        if isinstance(success_obj, dict) and 'content' in success_obj:
                            content_list = success_obj['content']
                            if content_list and len(content_list) > 0:
                                text_obj = content_list[0].get('text', {})
                                text = text_obj.get('text', '') if isinstance(text_obj, dict) else str(text_obj)
                                success = "✓" if '"success": true' in text or '"success":true' in text else "✗"
                            else:
                                success = "✓"
                        else:
                            success = "✓"
                    else:
                        success = "✗"
                else:
                    success = "?"
                print(f"    {comp['timestamp']} - COMPLETION ({status}) {success}")
                if comp.get('notes'):
                    print(f"      Notes: {comp['notes']}")
        
        # Show update timeline
        if activity.updates:
            print(f"  Update Timeline:")
            for update in activity.updates[-10:]:  # Last 10 updates
                status_marker = "✓" if update['status'] == 'completed' else "→"
                print(f"    {update['timestamp']} {status_marker} [{update['update_type']}] {update['content']}")
        
        print()


def print_detailed_task_analysis(task_id: int, task_activities: Dict[int, TaskActivity], tool_calls: List[ToolCall]):
    """Print detailed analysis for a specific task."""
    if task_id not in task_activities:
        print(f"Task #{task_id} not found in log")
        return
    
    activity = task_activities[task_id]
    
    print("=" * 80)
    print(f"DETAILED ANALYSIS: TASK #{task_id}")
    print("=" * 80)
    print()
    
    # Timeline - deduplicate events that are too close together
    all_events = []
    seen_events = set()  # Track (timestamp_ms, event_type, content_hash) to deduplicate
    
    for update in activity.updates:
        content_hash = hash(update['content'][:50])  # Use first 50 chars as hash
        event_key = (update['timestamp_ms'] // 1000, 'update', content_hash)  # Round to seconds
        if event_key not in seen_events:
            seen_events.add(event_key)
            all_events.append((update['timestamp_ms'], 'update', update))
    
    for comp in activity.completions:
        event_key = (comp['timestamp_ms'], 'completion')
        if event_key not in seen_events:
            seen_events.add(event_key)
            all_events.append((comp['timestamp_ms'], 'completion', comp))
    
    for unlock in activity.unlocks:
        event_key = (unlock['timestamp_ms'], 'unlock')
        if event_key not in seen_events:
            seen_events.add(event_key)
            all_events.append((unlock['timestamp_ms'], 'unlock', unlock))
    
    for reserve in activity.reservations:
        event_key = (reserve['timestamp_ms'], 'reservation')
        if event_key not in seen_events:
            seen_events.add(event_key)
            all_events.append((reserve['timestamp_ms'], 'reservation', reserve))
    
    all_events.sort(key=lambda x: x[0])
    
    print("Timeline of Events (deduplicated):")
    print("-" * 80)
    for timestamp_ms, event_type, event_data in all_events:
        timestamp_str = parse_timestamp(timestamp_ms)
        if event_type == 'update':
            print(f"{timestamp_str} [UPDATE] {event_data['update_type']}: {event_data['content']}")
        elif event_type == 'completion':
            result = event_data.get('result')
            if result:
                if isinstance(result, dict):
                    success = result.get('success')
                    if success:
                        if isinstance(success, dict) and 'content' in success:
                            content = success['content']
                            if isinstance(content, list) and len(content) > 0:
                                text = content[0].get('text', {}).get('text', '')
                                success_indicator = "✓ SUCCESS" if '"success": true' in text or '"success":true' in text else "✗ FAILED"
                            else:
                                success_indicator = "✓ SUCCESS"
                        else:
                            success_indicator = "✓ SUCCESS"
                    else:
                        success_indicator = "✗ FAILED"
                else:
                    success_indicator = "? UNKNOWN"
            else:
                success_indicator = "? NO RESULT"
            print(f"{timestamp_str} [COMPLETION] {success_indicator}")
            if event_data.get('notes'):
                print(f"  Notes: {event_data['notes']}")
        elif event_type == 'unlock':
            print(f"{timestamp_str} [UNLOCK]")
        elif event_type == 'reservation':
            print(f"{timestamp_str} [RESERVATION] by {event_data.get('agent_id', 'unknown')}")
    
    print()
    
    # Detect looping patterns
    print("Loop Detection:")
    print("-" * 80)
    if len(activity.updates) > 10:
        print(f"⚠️  WARNING: {len(activity.updates)} updates detected - possible looping behavior")
        # Check for rapid repeated updates
        if len(activity.updates) > 5:
            update_times = [u['timestamp_ms'] for u in activity.updates]
            intervals = [update_times[i+1] - update_times[i] for i in range(len(update_times)-1)]
            rapid_updates = [i for i in intervals if i < 60000]  # Less than 1 minute apart
            if rapid_updates:
                print(f"  ⚠️  Found {len(rapid_updates)} rapid updates (within 1 minute of each other)")
    else:
        print(f"✓ Update count looks normal ({len(activity.updates)} updates)")
    print()


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze cursor-agent log file')
    parser.add_argument('log_file', nargs='?', default='cursor-agent.log',
                       help='Path to cursor-agent.log file')
    parser.add_argument('--task', type=int, help='Show detailed analysis for specific task ID')
    parser.add_argument('--list-tasks', action='store_true', help='List all tasks found in log')
    
    args = parser.parse_args()
    
    print(f"Parsing log file: {args.log_file}")
    print()
    
    try:
        tool_calls, task_activities = parse_log_file(args.log_file)
    except FileNotFoundError:
        print(f"Error: Log file not found: {args.log_file}")
        sys.exit(1)
    except Exception as e:
        print(f"Error parsing log file: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    if args.list_tasks:
        print("Tasks found in log:")
        for task_id in sorted(task_activities.keys()):
            activity = task_activities[task_id]
            print(f"  Task #{task_id}: {len(activity.updates)} updates, "
                  f"{len(activity.completions)} completions, "
                  f"{activity.first_seen} to {activity.last_seen}")
        return
    
    if args.task:
        print_detailed_task_analysis(args.task, task_activities, tool_calls)
    else:
        print_summary(tool_calls, task_activities)


if __name__ == '__main__':
    main()

