"""
Local MCP Client for non-Anthropic providers.

Anthropic handles MCP natively via ``mcp_servers`` in the API payload.
For OpenAI, Google, and Mistral we need to act as the MCP client
ourselves:

1. Call ``tools/list``   on each MCP server -> get tool schemas
2. Convert schemas to the provider's native function-calling format
3. When the LLM responds with a tool call, call ``tools/call`` on
   the MCP server with the tool name + arguments
4. Feed the result back to the LLM as a tool-result message

All HTTP communication uses SSE-aware JSON-RPC exactly like the
existing ``test-mcp`` route does.
"""

import json
import logging
import requests as http_requests

from server.helpers import parse_sse_response, apply_auth_to_request

logger = logging.getLogger(__name__)


# -- JSON-RPC helpers ----------------------------------------------------

def _jsonrpc_call(url, method, params=None, headers=None, timeout=30):
    """Send a JSON-RPC request and return the ``result`` dict."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }
    hdrs = {
        'Content-Type': 'application/json',
        'Accept': 'application/json,text/event-stream',
    }
    if headers:
        hdrs.update(headers)

    resp = http_requests.post(url, json=payload, headers=hdrs, timeout=timeout)
    resp.raise_for_status()

    result = parse_sse_response(resp.text)
    if 'error' in result:
        raise RuntimeError(f"MCP JSON-RPC error: {result['error']}")
    return result.get('result', {})


def _init_mcp_session(url, headers, timeout=10):
    """Initialize a Streamable HTTP MCP session and return the session ID.

    Servers like Business Central use the MCP Streamable HTTP transport
    (protocol 2025-06-18) which requires an ``initialize`` handshake before
    ``tools/call`` will work.  The session ID is returned in the
    ``Mcp-Session-Id`` response header and must be included in all
    subsequent requests.

    Returns the session ID string, or ``None`` if the server doesn't issue
    one (i.e. it uses a simpler transport that doesn't need sessions).
    """
    init_payload = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "claude-api-usage", "version": "1.0"},
        },
    }
    resp = http_requests.post(url, json=init_payload, headers=headers, timeout=timeout)
    resp.raise_for_status()
    session_id = resp.headers.get('Mcp-Session-Id')

    if session_id:
        # Send the required ``initialized`` notification so the server knows
        # the client has finished its setup phase.
        notif_hdrs = dict(headers)
        notif_hdrs['Mcp-Session-Id'] = session_id
        notif_payload = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        try:
            http_requests.post(url, json=notif_payload, headers=notif_hdrs, timeout=timeout)
        except Exception:
            pass  # Best-effort; don't fail the whole session over the notification

    return session_id


# -- Tool schema fetching ------------------------------------------------

def fetch_mcp_tools(app, enriched_servers):
    """Call ``tools/list`` on each enriched server and return a combined
    list of tool definitions plus a lookup map.

    Returns ``(tool_defs, tool_map)`` where:
    - ``tool_defs``  -- list of MCP tool dicts (name, description,
                        inputSchema) with ``_server_id`` injected.
    - ``tool_map``   -- dict mapping ``qualified_name -> (server_url, headers, server_data)``
                        so we know where to dispatch ``tools/call``.
    """
    tool_defs = []
    tool_map = {}

    for srv in enriched_servers:
        sid = srv.get('id')
        mcp_url = srv.get('url', '')
        if not mcp_url:
            continue

        # Build authenticated headers
        hdrs = {
            'Content-Type': 'application/json',
            'Accept': 'application/json,text/event-stream',
        }
        mcp_url, hdrs, err = apply_auth_to_request(app, sid, srv, mcp_url, hdrs)
        if err:
            logger.warning(f"Auth error for MCP server {sid}, skipping: {err}")
            continue

        # Apply any custom headers (e.g. Business Central Company/ConfigurationName)
        custom_headers = srv.get('headers', {})
        if custom_headers:
            hdrs.update(custom_headers)

        # Initialize a Streamable HTTP session when the server supports it.
        # BC and similar servers require a session (Mcp-Session-Id) for
        # tools/call to work; tools/list is more lenient but we init first
        # so both use the same session context.
        session_hdrs = dict(hdrs)
        try:
            session_id = _init_mcp_session(mcp_url, hdrs)
            if session_id:
                session_hdrs['Mcp-Session-Id'] = session_id
                logger.info(f"Initialized MCP session {session_id} for server {sid}")
        except Exception as se:
            logger.debug(f"Session init not required or failed for {sid}: {se}")

        try:
            result = _jsonrpc_call(mcp_url, 'tools/list', headers=session_hdrs)
            tools = result.get('tools', [])
            for t in tools:
                name = t.get('name', '')
                # Prefix tool name with server id to avoid collisions
                qualified_name = f"{sid}__{name}" if name else None
                if not qualified_name:
                    continue
                t['_qualified_name'] = qualified_name
                t['_server_id'] = sid
                tool_defs.append(t)
                tool_map[qualified_name] = (mcp_url, session_hdrs, srv)
            logger.info(f"Fetched {len(tools)} tools from MCP server {sid}")
        except Exception as e:
            logger.warning(f"Failed to fetch tools from MCP server {sid}: {e}")

    return tool_defs, tool_map


def call_mcp_tool(tool_name, arguments, tool_map):
    """Execute a tool call against the correct MCP server.

    *tool_name* is the qualified name (``server_id__tool_name``).
    Returns the ``result`` from the MCP server's ``tools/call`` response.
    """
    if tool_name not in tool_map:
        return {"error": f"Unknown tool: {tool_name}"}

    mcp_url, hdrs, _srv = tool_map[tool_name]

    # Strip the server_id prefix to get the original tool name
    parts = tool_name.split('__', 1)
    original_name = parts[1] if len(parts) == 2 else tool_name

    try:
        result = _jsonrpc_call(mcp_url, 'tools/call', {
            'name': original_name,
            'arguments': arguments,
        }, headers=hdrs)
        return result
    except Exception as e:
        logger.error(f"MCP tool call failed for {tool_name}: {e}")
        return {"error": str(e)}


# -- Conversion to provider-native tool format ---------------------------

def mcp_tools_to_openai(tool_defs):
    """Convert MCP tool definitions to OpenAI function-calling format.

    Works for OpenAI and Mistral (both share the same schema).
    """
    functions = []
    for t in tool_defs:
        schema = t.get('inputSchema', {'type': 'object', 'properties': {}})
        functions.append({
            'type': 'function',
            'function': {
                'name': t['_qualified_name'],
                'description': t.get('description', ''),
                'parameters': schema,
            },
        })
    return functions


def mcp_tools_to_google(tool_defs):
    """Convert MCP tool definitions to Gemini ``tools`` format."""
    declarations = []
    for t in tool_defs:
        schema = t.get('inputSchema', {'type': 'object', 'properties': {}})
        # Gemini doesn't accept $schema or additionalProperties at top level
        schema = {k: v for k, v in schema.items()
                  if k not in ('$schema', 'additionalProperties')}
        declarations.append({
            'name': t['_qualified_name'],
            'description': t.get('description', ''),
            'parameters': schema,
        })
    return [{'functionDeclarations': declarations}] if declarations else []
