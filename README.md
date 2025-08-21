# Openwebui_With_CCR
### Use OpenWebUI's API in Claude Code Router in order to use it in Claude Code.

First, you need to install Claude Code Router and Claude Code.

[Claude Code Router](https://github.com/musistudio/claude-code-router)   
[Claude Code](https://github.com/anthropics/claude-code)

Then, configure it according to Claude Code Router's README.md.

Use `python main.py` or `python3 main.py` to start the proxy.

```py
LISTEN_HOST = '127.0.0.1'
LISTEN_PORT = 4567 # Your Claude Code BASE_URL and Port
```
You can set it with `export ANTHROPIC_BASE_URL="http://127.0.0.1:4567"`
```py
UPSTREAM_HOST = '127.0.0.1'
UPSTREAM_PORT = 3456 # Your Claude Code Router Port
```
We process the `UPSTREAM` traffic and forward it to `LISTEN`.


### Principle

Communication between a Claude Code client and a proxy server (or directly with a Claude model) typically uses the [Server-Sent Events (SSE)](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events) protocol. SSE is a one-way communication mechanism based on HTTP that allows the server to continuously send a stream of events to the client. Each event begins with `event: <event_name>`, followed by `data: <payload>`, and ends with two newline characters `\n\n`.

The problem lies in OpenWebUI being forwarded through the Claude Code Router. Before the actual conversation begins, a metadata message block is sent. This is commonly used in web chat.

This metadata message block is roughly structured like this:

```
event: message_start
data: {"type":"message_start", "message": {...}}

event: content_block_start
data: {"type":"content_block_start", "index":0, "content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" ```"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"json\n{\n \"isNew"}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Topic\": true,\n \""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"title\": \"Initial Greeting\"\n}\n```"}}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn",...}}

event: message_stop
data: {"type":"message_stop"}\n\n
```

The problem is the JSON string spliced out in `content_block_delta`: 

```json
{ 
"isNewTopic": true, 
"title": "Initial Greeting"
}
```

The Claude Code client expects to receive plain text content for rendering a conversation. When it receives a JSON object wrapped in a Markdown code block, it might interpret it as:

1. Internal Directives or Metadata: The client might have an internal mechanism for handling special fields like `isNewTopic` to manage conversation state or session information. When it detects this structure, it interprets it as a directive, not text to be displayed to the user.
2. Unexpected Content Type: The client's rendering logic might only handle normal text `text_delta` events, and might not know how to render or simply ignore a full JSON code block (even though it's still text).
3. State Machine Interruption: The client's internal processing of the SSE stream might be a state machine. After processing this "metadata" block and digesting it internally (or ignoring it), it might believe the "message" is complete and not properly enter the state to receive the next conversation message. The `Executing hooks for Stop` message in the debug log may be part of this "message end" processing, but because no specific subsequent actions are matched, it becomes "stuck."

In short, the proxy server sent a message that the model should understand but the client should not display. Without explicit instructions, the client improperly processed it (digesting or ignoring it instead of displaying it) and did not continue processing subsequent normal conversation messages.

### How the Python Proxy Fix Works

The Python proxy script provided in this repository is an application-layer gateway. Its principles are:

1. Man-in-the-middle interception:
* The proxy program listens on a port (e.g., `4567`) to which clients connect.
* When a Claude Code client connects to port `4567`, the proxy program immediately establishes a connection to the real Claude Code Router (listening on port `3456`).
* Now, all client requests to `3456` will first pass through the proxy on `4567`.

2. **Transparently forwarding client requests** (`forward_client_to_server` function):
* Any data sent by the client (e.g., `Hello` request) is forwarded **unchanged** by the proxy to the upstream real Claude Code proxy server. This is lossless, ensuring the request reaches the backend correctly.

3. Intelligently filtering server responses (`forward_server_to_client_with_fix` function):
* This is where the core logic resides. The proxy receives data from the real Claude Code proxy server.
* Buffer mechanism (`buffer`): Because SSE events may be split across multiple TCP packets (e.g., `event: message_start` in one packet and `data: {` in another), the proxy uses an internal buffer to accumulate received data.
* Event block parsing: The proxy looks for the start marker (`BLOCK_START_MARKER`) and end marker (`BLOCK_END_MARKER`) of the SSE message. This allows it to identify and extract a complete SSE message block.
* Key filtering logic: Once the proxy successfully extracts a complete message block from the buffer, it checks whether the complete content of the message block contains the defined `BAD_BLOCK_SIGNATURE` (i.e., `b'"isNewTopic": true'`).
* **If it does, this indicates that the currently extracted message block is the problematic metadata block. The proxy **directly discards** the message block and does not forward it to the client.
* **If it does not, this indicates that the message block is normal and should be displayed to the client (e.g., Claude's greeting). The proxy immediately forwards it to the client.
* Continuous processing: The proxy loops, processing the accumulated data in the buffer, until no complete message blocks are left to extract or no new data arrives.
