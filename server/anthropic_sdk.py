"""
Anthropic Python SDK integration.

Replaces direct ``requests`` HTTP calls to the Anthropic API with the
official ``anthropic`` Python SDK.  Handles both standard chat and two
MCP integration paths:

1. **Native MCP** (``mcp_servers`` in the payload via beta header) —
   used when Anthropic's servers can reach every MCP server directly,
   i.e. no custom headers are required OR a public HTTPS proxy is running.

2. **Client-side MCP** (``run_anthropic_mcp_client_sync``) —
   used when a server has custom headers but no public proxy is available
   (e.g. Business Central without ngrok).  Our server calls ``tools/list``
   and ``tools/call`` directly (same as the OpenAI path) and passes tool
   results back to Anthropic via its native tool-calling API.

Public surface
--------------
run_anthropic_non_streaming(...)
    Standard non-streaming call via ``client.messages.create()``.

stream_anthropic_response(...)
    Streaming call via ``client.messages.stream()``.

run_anthropic_mcp_client_sync(...)
    Client-side MCP tool loop — fetches tools from MCP servers locally
    and drives the Anthropic tool-calling loop via SDK.

synthesize_anthropic_mcp_sse(...)
    Wraps a client-side MCP result dict in Anthropic-style SSE events.

check_anthropic_credit(api_key)
    Validates an API key using the SDK's models list endpoint.
"""

import json
import logging

import anthropic

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10

_MCP_BETA = 'mcp-client-2025-11-20'


# ---------------------------------------------------------------------------
# Non-streaming
# ---------------------------------------------------------------------------

def run_anthropic_non_streaming(
    api_key: str,
    model: str,
    messages: list,
    max_tokens: int,
    mcp_servers: list | None = None,
    tools: list | None = None,
    system: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    stop_sequences: list | None = None,
):
    """Send a non-streaming Anthropic messages request via the SDK.

    Returns
    -------
    dict
        Anthropic response in its native JSON format (already the
        normalised format used everywhere else in the app).
    """
    client = anthropic.Anthropic(api_key=api_key)

    kwargs = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': messages,
    }
    if system:
        kwargs['system'] = system
    if tools:
        kwargs['tools'] = tools
    if temperature is not None:
        kwargs['temperature'] = min(float(temperature), 1.0)
    if top_p is not None:
        kwargs['top_p'] = float(top_p)
    if stop_sequences:
        kwargs['stop_sequences'] = list(stop_sequences)

    try:
        if mcp_servers:
            kwargs['mcp_servers'] = mcp_servers
            response = client.beta.messages.create(
                betas=[_MCP_BETA],
                **kwargs,
            )
        else:
            response = client.messages.create(**kwargs)
    except anthropic.AuthenticationError as e:
        raise RuntimeError(f"Anthropic authentication failed: {e}") from e
    except anthropic.BadRequestError as e:
        raise RuntimeError(f"Anthropic bad request: {e}") from e
    except anthropic.RateLimitError as e:
        raise RuntimeError(f"Anthropic rate limit exceeded: {e}") from e
    except anthropic.APIStatusError as e:
        raise RuntimeError(f"Anthropic API error {e.status_code}: {e}") from e

    # Convert Pydantic model → plain dict preserving Anthropic's format
    return json.loads(response.model_dump_json())


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------

def stream_anthropic_response(
    api_key: str,
    model: str,
    messages: list,
    max_tokens: int,
    mcp_servers: list | None = None,
    tools: list | None = None,
    system: str | None = None,
    session_id: str | None = None,
    metrics: dict | None = None,
    input_price: float = 0.0,
    output_price: float = 0.0,
    existing_messages: list | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    stop_sequences: list | None = None,
):
    """Stream an Anthropic messages request via the SDK.

    Yields normalised SSE JSON strings (same format as
    ``AnthropicProvider.parse_stream_events``) and emits a final
    ``stream_end`` event that saves the session and includes metrics.

    Returns a Flask ``Response``.
    """
    from flask import Response, stream_with_context, current_app

    if metrics is None:
        metrics = {'total_input_tokens': 0, 'total_output_tokens': 0, 'total_cost': 0.0}
    if existing_messages is None:
        existing_messages = messages

    client = anthropic.Anthropic(api_key=api_key)

    kwargs = {
        'model': model,
        'max_tokens': max_tokens,
        'messages': messages,
    }
    if system:
        kwargs['system'] = system
    if tools:
        kwargs['tools'] = tools
    if temperature is not None:
        kwargs['temperature'] = min(float(temperature), 1.0)
    if top_p is not None:
        kwargs['top_p'] = float(top_p)
    if stop_sequences:
        kwargs['stop_sequences'] = list(stop_sequences)

    def generate():
        accumulated = []
        usage_data = {}
        stop_reason = None

        try:
            if mcp_servers:
                kwargs['mcp_servers'] = mcp_servers
                stream_ctx = client.beta.messages.stream(
                    betas=[_MCP_BETA],
                    **kwargs,
                )
            else:
                stream_ctx = client.messages.stream(**kwargs)

            with stream_ctx as stream:
                for event in stream:
                    try:
                        event_dict = event.model_dump()
                    except Exception:
                        continue

                    etype = event_dict.get('type')

                    # Track accumulated content and usage (mirrors _stream_response)
                    if etype == 'content_block_start':
                        idx = event_dict.get('index', 0)
                        while len(accumulated) <= idx:
                            accumulated.append({})
                        accumulated[idx] = event_dict.get('content_block', {})

                    elif etype == 'content_block_delta':
                        idx = event_dict.get('index', 0)
                        delta = event_dict.get('delta', {})
                        while len(accumulated) <= idx:
                            accumulated.append({})
                        if delta.get('type') == 'text_delta':
                            accumulated[idx].setdefault('text', '')
                            accumulated[idx]['text'] += delta.get('text', '')
                        elif delta.get('type') == 'thinking_delta':
                            accumulated[idx].setdefault('thinking', '')
                            accumulated[idx]['thinking'] += delta.get('thinking', '')

                    elif etype == 'message_delta':
                        d = event_dict.get('delta', {})
                        if 'stop_reason' in d:
                            stop_reason = d['stop_reason']
                        usage_data.update(event_dict.get('usage', {}))

                    elif etype == 'message_start':
                        usage_data.update(
                            event_dict.get('message', {}).get('usage', {})
                        )

                    # Skip internal SDK-only event types (not valid SSE for frontend)
                    if etype in ('message_stop',):
                        continue

                    yield f"data: {json.dumps(event_dict)}\n\n"

        except Exception as e:
            logger.error(f"Anthropic SDK streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
            return

        # Emit final stream_end event (mirrors _stream_response)
        if usage_data:
            cur_in = usage_data.get('input_tokens', 0)
            cur_out = usage_data.get('output_tokens', 0)
            metrics['total_input_tokens'] += cur_in
            metrics['total_output_tokens'] += cur_out
            metrics['total_cost'] += (cur_in * input_price) + (cur_out * output_price)

        history = existing_messages + [{'role': 'assistant', 'content': accumulated}]

        if session_id:
            try:
                db = current_app.config['db']
                db.update_session_state(session_id, metrics)
            except Exception as e:
                logger.warning(f"Could not save session {session_id}: {e}")

        yield f"data: {json.dumps({'type': 'stream_end', 'content': accumulated, 'session_metrics': metrics, 'conversation_history': history, 'usage': usage_data, 'stop_reason': stop_reason, 'tool_chain': []})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


# ---------------------------------------------------------------------------
# Client-side MCP tool loop (fallback when native MCP can't reach a server)
# ---------------------------------------------------------------------------

def _mcp_tools_to_anthropic(tool_defs):
    """Convert MCP tool definitions to Anthropic's tool-calling format.

    Anthropic uses ``input_schema`` (not ``parameters``) for the JSON schema.
    """
    tools = []
    for t in tool_defs:
        schema = t.get('inputSchema', {'type': 'object', 'properties': {}})
        tools.append({
            'name': t['_qualified_name'],
            'description': t.get('description', ''),
            'input_schema': schema,
        })
    return tools


def _flatten_mcp_result(mcp_result):
    """Convert an MCP tools/call result to a plain text string."""
    if isinstance(mcp_result, str):
        return mcp_result
    if isinstance(mcp_result, dict):
        content_list = mcp_result.get('content', [])
        if isinstance(content_list, list):
            texts = [
                c['text'] for c in content_list
                if isinstance(c, dict) and c.get('text')
            ]
            if texts:
                return '\n'.join(texts)
        return json.dumps(mcp_result)
    return str(mcp_result)


def _sdk_block_to_dict(block):
    """Convert an SDK content block object to a plain dict for re-sending."""
    if block.type == 'text':
        return {'type': 'text', 'text': block.text}
    if block.type == 'tool_use':
        return {'type': 'tool_use', 'id': block.id, 'name': block.name, 'input': block.input}
    # Fallback: filter out None values from model_dump
    try:
        return {k: v for k, v in block.model_dump().items() if v is not None}
    except Exception:
        return {'type': str(block.type)}


def run_anthropic_mcp_client_sync(
    api_key: str,
    model: str,
    messages: list,
    enriched_servers: list,
    max_tokens: int,
    app,
    stream: bool = False,
):
    """Run an Anthropic conversation with MCP tools via client-side tool dispatch.

    Used when native Anthropic MCP can't reach the server (e.g. Business
    Central requires custom auth headers and no public proxy is running).
    Our server calls ``tools/list`` / ``tools/call`` directly, then passes
    tool results back to Anthropic using its native tool-calling API.

    Returns the same Anthropic-normalised dict as other MCP implementations.
    """
    from server.mcp_client import fetch_mcp_tools, call_mcp_tool

    client = anthropic.Anthropic(api_key=api_key)

    tool_defs, tool_map = fetch_mcp_tools(app, enriched_servers)
    if not tool_defs:
        raise RuntimeError("No MCP tools could be loaded from the configured servers")

    tools = _mcp_tools_to_anthropic(tool_defs)

    # Extract system message and build message list
    system = None
    filtered = []
    for msg in messages:
        if msg.get('role') == 'system':
            content = msg.get('content', '')
            if isinstance(content, list):
                system = '\n'.join(
                    c.get('text', '') for c in content
                    if isinstance(c, dict) and c.get('type') == 'text'
                )
            else:
                system = str(content)
        else:
            filtered.append(msg)

    anth_messages = list(filtered or messages)

    total_usage = {
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_creation_input_tokens': 0,
        'cache_read_input_tokens': 0,
    }
    content_blocks = []
    last_response = None

    for iteration in range(MAX_TOOL_ITERATIONS):
        kwargs = {
            'model': model,
            'max_tokens': max_tokens,
            'messages': anth_messages,
            'tools': tools,
        }
        if system:
            kwargs['system'] = system

        try:
            response = client.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            raise RuntimeError(f"Anthropic API error {e.status_code}: {e}") from e

        last_response = response

        if response.usage:
            total_usage['input_tokens'] += response.usage.input_tokens or 0
            total_usage['output_tokens'] += response.usage.output_tokens or 0

        tool_use_blocks = [b for b in response.content if b.type == 'tool_use']

        # ── No tool calls — final text response ──────────────────────
        if not tool_use_blocks:
            final_content = []
            for block in response.content:
                if block.type == 'text' and block.text:
                    content_blocks.append({'type': 'text', 'text': block.text})
                    final_content.append({'type': 'text', 'text': block.text})
            # Append the final assistant message to anth_messages so the full
            # history (with proper role alternation) can be saved for next turn.
            anth_messages.append({'role': 'assistant', 'content': final_content})
            break

        # ── Emit tool_use content blocks ──────────────────────────────
        for block in response.content:
            if block.type == 'tool_use':
                content_blocks.append({
                    'type': 'tool_use',
                    'id': block.id,
                    'name': block.name,
                    'input': block.input,
                })
            elif block.type == 'text' and block.text:
                content_blocks.append({'type': 'text', 'text': block.text})

        # Append assistant message (all content blocks) to history
        anth_messages.append({
            'role': 'assistant',
            'content': [_sdk_block_to_dict(b) for b in response.content],
        })

        # Execute each tool via MCP and collect results
        tool_results = []
        for block in tool_use_blocks:
            logger.info(f"Anthropic client-side tool call [{iteration + 1}]: {block.name}")
            mcp_result = call_mcp_tool(block.name, block.input, tool_map)
            result_str = _flatten_mcp_result(mcp_result)

            content_blocks.append({
                'type': 'tool_result',
                'tool_use_id': block.id,
                'content': result_str,
            })
            tool_results.append({
                'type': 'tool_result',
                'tool_use_id': block.id,
                'content': result_str,
            })

        # Append tool results as a user message
        anth_messages.append({'role': 'user', 'content': tool_results})
        logger.info(f"Anthropic client-side tool loop iteration {iteration + 1} complete")

    logger.info(
        f"Anthropic client-side MCP loop done: iterations={iteration + 1}, "
        f"content_blocks={len(content_blocks)}, usage={total_usage}"
    )

    if not content_blocks:
        content_blocks.append({'type': 'text', 'text': '(No response)'})

    return {
        'id': last_response.id if last_response else '',
        'model': last_response.model if last_response else model,
        'content': content_blocks,
        'stop_reason': 'end_turn',
        'usage': total_usage,
        'provider': 'anthropic',
        # Full message history with correct role alternation (tool_result in
        # user messages, not assistant).  Used by callers to save the session
        # so that the next turn doesn't trigger an Anthropic 400.
        'history': anth_messages,
    }


def synthesize_anthropic_mcp_sse(result, session_id, metrics, messages,
                                  input_price, output_price):
    """Wrap an Anthropic client-side MCP dict result in Anthropic-style SSE events."""
    import json as _json
    from flask import Response, stream_with_context

    def _save(history):
        from server.routes.chat import _save_session
        _save_session(session_id, history, metrics)

    content = result.get('content', [])
    usage = result.get('usage', {})

    cur_in = usage.get('input_tokens', 0)
    cur_out = usage.get('output_tokens', 0)
    metrics['total_input_tokens'] += cur_in
    metrics['total_output_tokens'] += cur_out
    metrics['total_cost'] += (cur_in * input_price) + (cur_out * output_price)

    def generate():
        yield f"data: {_json.dumps({'type': 'message_start', 'message': {'id': result.get('id', ''), 'model': result.get('model', ''), 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"
        for i, block in enumerate(content):
            btype = block.get('type', 'text')
            if btype == 'text':
                yield f"data: {_json.dumps({'type': 'content_block_start', 'index': i, 'content_block': {'type': 'text', 'text': ''}})}\n\n"
                yield f"data: {_json.dumps({'type': 'content_block_delta', 'index': i, 'delta': {'type': 'text_delta', 'text': block.get('text', '')}})}\n\n"
                yield f"data: {_json.dumps({'type': 'content_block_stop', 'index': i})}\n\n"
            elif btype in ('tool_use', 'tool_result'):
                yield f"data: {_json.dumps({'type': 'content_block_start', 'index': i, 'content_block': block})}\n\n"
                yield f"data: {_json.dumps({'type': 'content_block_stop', 'index': i})}\n\n"
        yield f"data: {_json.dumps({'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': usage})}\n\n"
        # Use the full internal history (with tool_result in user messages)
        # so the next turn doesn't get Anthropic 400 "tool_result in assistant message".
        history = result.get('history') or (messages + [{'role': 'assistant', 'content': content}])
        _save(history)
        yield f"data: {_json.dumps({'type': 'stream_end', 'content': content, 'session_metrics': metrics, 'conversation_history': history, 'usage': usage, 'stop_reason': 'end_turn'})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


# ---------------------------------------------------------------------------
# Credit / key validation
# ---------------------------------------------------------------------------

def check_anthropic_credit(api_key: str) -> dict:
    """Validate an Anthropic API key using the SDK.

    Returns the same shape as ``AnthropicProvider.check_credit``.
    """
    client = anthropic.Anthropic(api_key=api_key)
    try:
        page = client.models.list(limit=1)
        # Success — key is valid
        return {
            'valid': True,
            'credit_status': 'active',
            'status': 200,
        }
    except anthropic.AuthenticationError:
        return {'error': 'Invalid API key', 'valid': False, 'status': 401}
    except anthropic.PermissionDeniedError:
        return {'error': 'API key does not have permission', 'valid': False, 'status': 403}
    except anthropic.APIStatusError as e:
        if e.status_code == 402:
            return {
                'valid': True,
                'credit_status': 'exhausted',
                'message': 'Your API credit has been exhausted. '
                           'Please add more credit at console.anthropic.com.',
                'status': 200,
            }
        return {'error': str(e), 'status': e.status_code}
    except Exception as e:
        return {'error': str(e), 'status': 500}
