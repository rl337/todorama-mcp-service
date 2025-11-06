#!/usr/bin/env python3
"""
Verification script to check that all MCP_FUNCTIONS have corresponding handlers in main.py.
"""
import re
import ast

def extract_mcp_functions():
    """Extract function names from MCP_FUNCTIONS."""
    with open('src/mcp_api.py', 'r') as f:
        content = f.read()
    
    # Find MCP_FUNCTIONS = [
    start_idx = content.find('MCP_FUNCTIONS = [')
    if start_idx == -1:
        raise ValueError("MCP_FUNCTIONS not found")
    
    # Extract function names
    function_names = []
    pattern = r'"name":\s*"([^"]+)"'
    matches = re.findall(pattern, content[start_idx:])
    
    return matches

def extract_handlers():
    """Extract tool_name handlers from main.py."""
    with open('src/main.py', 'r') as f:
        lines = f.readlines()
    
    # Find tools/call section
    start_idx = None
    end_idx = None
    
    for i, line in enumerate(lines):
        if 'elif body.get("method") == "tools/call":' in line or '# Handle tools/call request' in line:
            start_idx = i
        elif start_idx is not None and 'else:' in line and 'tool_name' not in line:
            # Found the else clause after all handlers
            end_idx = i
            break
    
    if start_idx is None:
        raise ValueError("tools/call section not found")
    
    if end_idx is None:
        # Look for the else clause that handles unknown tools
        for i in range(start_idx, len(lines)):
            if 'else:' in lines[i] and 'Tool not found' in lines[i+1] if i+1 < len(lines) else False:
                end_idx = i
                break
    
    if end_idx is None:
        end_idx = len(lines)
    
    # Extract handlers from this section
    section_content = ''.join(lines[start_idx:end_idx])
    
    # Pattern for: if tool_name == "function_name" or elif tool_name == "function_name"
    pattern = r'(?:if|elif)\s+tool_name\s*==\s*"([^"]+)"'
    matches = re.findall(pattern, section_content)
    
    return matches

def main():
    print("Verifying MCP function routing...")
    print("=" * 60)
    
    # Get functions from MCP_FUNCTIONS
    mcp_functions = extract_mcp_functions()
    print(f"\nFound {len(mcp_functions)} functions in MCP_FUNCTIONS:")
    for func in sorted(mcp_functions):
        print(f"  - {func}")
    
    # Get handlers from main.py
    handlers = extract_handlers()
    print(f"\nFound {len(handlers)} handlers in main.py:")
    for handler in sorted(handlers):
        print(f"  - {handler}")
    
    # Compare
    print("\n" + "=" * 60)
    mcp_set = set(mcp_functions)
    handlers_set = set(handlers)
    
    missing_handlers = mcp_set - handlers_set
    extra_handlers = handlers_set - mcp_set
    
    if missing_handlers:
        print(f"\n? MISSING HANDLERS ({len(missing_handlers)}):")
        for func in sorted(missing_handlers):
            print(f"  - {func} (defined in MCP_FUNCTIONS but no handler in main.py)")
    else:
        print("\n? All MCP_FUNCTIONS have handlers")
    
    if extra_handlers:
        print(f"\n??  EXTRA HANDLERS ({len(extra_handlers)}):")
        for handler in sorted(extra_handlers):
            print(f"  - {handler} (handler exists but not in MCP_FUNCTIONS)")
    else:
        print("\n? No extra handlers found")
    
    if not missing_handlers and not extra_handlers:
        print("\n? VERIFICATION PASSED: All functions are properly routed!")
        return 0
    else:
        print("\n? VERIFICATION FAILED: Routing issues found")
        return 1

if __name__ == "__main__":
    exit(main())
