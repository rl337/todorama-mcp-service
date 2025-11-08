#!/bin/bash
# Quick test script for the parser

echo "Testing cursor agent parser..."
echo ""

# Test with sample JSON
cat << 'TESTDATA' | python3 parse_cursor_agent.py
{"tool_calls": [{"name": "read_file", "arguments": {"target_file": "src/api/command_router.py"}}]}
{"tool_results": [{"content": "File contents here..."}]}
{"messages": [{"role": "assistant", "content": "I'll fix the syntax error in command_router.py"}]}
{"tool_calls": [{"name": "run_terminal_cmd", "arguments": {"command": "pytest tests/test_api.py -v", "is_background": false}}]}
{"tool_results": [{"content": "test_api.py::test_create_task PASSED\n1 passed in 0.5s"}]}
{"error": "Some error occurred"}
