# Cursor Agent Log Parser

A simple parser to extract human-readable content from Cursor Agent JSON output.

## Usage

```bash
# Pipe cursor agent output through the parser
cursor-agent command | tee cursor-agent.log | python3 parse_cursor_agent.py

# Or just parse an existing log file
cat cursor-agent.log | python3 parse_cursor_agent.py

# Parse and save to a readable log
cursor-agent command | tee cursor-agent.log | python3 parse_cursor_agent.py > readable.log
```

## What it extracts

- **Task operations**: Task reservations (🔒), completions (✅), and creation (➕)
- **Tool calls**: Shows what tools the agent is calling (file reads, terminal commands, etc.)
- **Task summaries**: Extracts summaries from task execution results
- **Messages**: Shows user and assistant messages
- **Errors**: Highlights error messages
- **Duration**: Shows execution time for long-running operations

## Output format

- `→` Tool calls
- `📝` Content/messages
- `❌` Errors
- `⚠️` Warnings/status
- `🔧` Functions
- `📋` Plain text log lines

## Examples

```bash
# Watch agent work in real-time
cursor-agent fix-tests | tee cursor-agent.log | python3 parse_cursor_agent.py

# Parse existing log file
cat cursor-agent.log | python3 parse_cursor_agent.py

# Or use stdin redirection
python3 parse_cursor_agent.py < cursor-agent.log

# Save both raw and readable logs
cursor-agent command | tee cursor-agent.log | python3 parse_cursor_agent.py | tee cursor-agent-readable.log
```

## Testing

To test the parser with a sample log:

```bash
# The parser will work with any cursor-agent.log file
cat cursor-agent.log | python3 parse_cursor_agent.py
```

