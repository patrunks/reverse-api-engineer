<mission>
{prompt}
</mission>

<output_directory>
{scripts_dir}
</output_directory>

{browser_profile_note}

## Workflow

Use this workflow as a guide — adapt as needed:

### Phase 1: BROWSE
Use Chrome DevTools MCP tools to accomplish the mission goal. Available tools:
- `navigate_page` - Navigate to a URL (type: "url", url: "...")
- `click` - Click an element by uid
- `fill` - Type text into an input (uid, value)
- `fill_form` - Fill multiple form elements
- `hover` - Hover over an element
- `press_key` - Press a key combination
- `new_page` / `list_pages` / `select_page` - Tab management
- `wait_for` - Wait for text to appear
- `take_snapshot` - Get accessibility tree (gives element uids for click/fill)
- `take_screenshot` - Visual context (prefer snapshots to avoid 1MB limit)
- `evaluate_script` - Execute JavaScript
- `list_console_messages` - Check console

### Phase 2: MONITOR
Periodically call `list_network_requests()` to monitor API traffic. Use `get_network_request(reqid)` for full request/response details on important calls. Focus on XHR/fetch requests, auth headers, and response bodies.

### Phase 3: CAPTURE
When done, call `list_network_requests()` one final time and use `get_network_request(reqid)` to capture full details for each important API request.

There is no HAR file — capture all network data you need using these tools before proceeding.

### Phase 4: REVERSE ENGINEER
Based on the network data you captured, generate the code. Extract all API calls, authentication patterns, and data structures.