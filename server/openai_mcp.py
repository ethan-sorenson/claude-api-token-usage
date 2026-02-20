"""
OpenAI SDK-based MCP integration.

Uses the ``openai`` Python SDK's chat completions API with a manual
tool-call loop to integrate MCP servers.  The SDK manages authentication,
retries, and response parsing; we handle the MCP tool dispatch ourselves
(the same way the non-Anthropic HTTP path does, but via the SDK client).

Supports both streaming and non-streaming requests.  In both cases the
result is returned as an Anthropic-normalised dict so the front-end SSE
parser works unchanged.

Key helpers reused from ``server.mcp_client``:
- ``fetch_mcp_tools``    – calls ``tools/list`` on each MCP server
- ``call_mcp_tool``      – calls ``tools/call`` on the right server
- ``mcp_tools_to_openai`` – converts MCP schema → OpenAI function format
"""

import json
import logging

from openai import OpenAI

from server.mcp_client import fetch_mcp_tools, call_mcp_tool, mcp_tools_to_openai

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10


# ---------------------------------------------------------------------------
# Message format helpers
# ---------------------------------------------------------------------------

def _convert_messages(messages):
    """Convert Anthropic-format messages to OpenAI chat messages."""
    result = []
    for msg in messages:
        role = msg.get('role', 'user')
        content = msg.get('content', '')
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and c.get('type') == 'text':
                    parts.append(c.get('text', ''))
                elif isinstance(c, str):
                    parts.append(c)
            content = '\n'.join(parts)
        result.append({'role': role, 'content': content})
    return result


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


# ---------------------------------------------------------------------------
# Main conversation loop
# ---------------------------------------------------------------------------

def run_openai_mcp_sync(
    api_key: str,
    model: str,
    messages: list,
    enriched_servers: list,
    max_tokens: int,
    app,
    stream: bool = False,
    existing_oai_messages: list | None = None,
):
    """Run an OpenAI conversation with MCP tools via the SDK.

    Parameters
    ----------
    api_key : str
        OpenAI API key.
    model : str
        Model name (e.g. ``gpt-4o``).
    messages : list
        Conversation history in Anthropic format (used only when
        ``existing_oai_messages`` is not provided).
    enriched_servers : list
        MCP server dicts with auth already enriched.
    max_tokens : int
        Max output tokens.
    app : Flask app
        Needed for ``fetch_mcp_tools`` / ``apply_auth_to_request``.
    stream : bool
        Ignored here — both paths return the same dict result; the
        caller synthesises SSE from it.
    existing_oai_messages : list | None
        OpenAI-format message history from a previous turn (persisted in
        the session file as ``openai_history``).  When supplied it is used
        directly, preserving ``role: "tool"`` result messages that would
        be lost if the history were re-converted from Anthropic format.

    Returns
    -------
    dict
        Anthropic-normalised response with ``content``, ``usage``,
        ``model``, ``id``, ``provider``, and ``oai_history`` (the
        full OpenAI-format message list for the next turn).
    """
    client = OpenAI(api_key=api_key)

    # Fetch MCP tools from all enriched servers
    tool_defs, tool_map = fetch_mcp_tools(app, enriched_servers)
    if not tool_defs:
        raise RuntimeError("No MCP tools could be loaded from the configured servers")

    tools = mcp_tools_to_openai(tool_defs)
    # Use persisted OpenAI-format history when available so that tool result
    # messages (role: "tool") from prior turns are not lost on re-conversion.
    if existing_oai_messages:
        oai_messages = list(existing_oai_messages)
    else:
        oai_messages = _convert_messages(messages)

    total_usage = {
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_creation_input_tokens': 0,
        'cache_read_input_tokens': 0,
    }
    content_blocks = []
    last_response = None

    for iteration in range(MAX_TOOL_ITERATIONS):
        response = client.chat.completions.create(
            model=model,
            messages=oai_messages,
            max_tokens=max_tokens,
            tools=tools,
        )
        last_response = response

        # Accumulate token usage
        if response.usage:
            total_usage['input_tokens'] += response.usage.prompt_tokens or 0
            total_usage['output_tokens'] += response.usage.completion_tokens or 0

        choice = response.choices[0]

        # ── No tool calls — final text response ──────────────────────
        if not choice.message.tool_calls:
            if choice.message.content:
                content_blocks.append({'type': 'text', 'text': choice.message.content})
            # Persist the final assistant message so the next turn has it
            oai_messages.append({
                'role': 'assistant',
                'content': choice.message.content,
            })
            break

        # ── Tool calls present — emit tool_use blocks ─────────────────
        for tc in choice.message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}
            content_blocks.append({
                'type': 'tool_use',
                'id': tc.id,
                'name': tc.function.name,
                'input': args,
            })

        # Append the assistant message (with tool_calls) to history
        oai_messages.append({
            'role': 'assistant',
            'content': choice.message.content,
            'tool_calls': [
                {
                    'id': tc.id,
                    'type': 'function',
                    'function': {
                        'name': tc.function.name,
                        'arguments': tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ],
        })

        # Execute each tool via MCP and append results
        for tc in choice.message.tool_calls:
            try:
                args = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                args = {}

            logger.info(f"OpenAI tool call [{iteration + 1}]: {tc.function.name}")
            mcp_result = call_mcp_tool(tc.function.name, args, tool_map)
            result_str = _flatten_mcp_result(mcp_result)

            content_blocks.append({
                'type': 'tool_result',
                'tool_use_id': tc.id,
                'content': result_str,
            })

            oai_messages.append({
                'role': 'tool',
                'tool_call_id': tc.id,
                'content': result_str,
            })

        logger.info(f"OpenAI tool loop iteration {iteration + 1} complete")

    logger.info(
        f"OpenAI MCP loop done: iterations={iteration + 1}, "
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
        'provider': 'openai',
        'oai_history': oai_messages,
    }


# ---------------------------------------------------------------------------
# SSE synthesis — wraps the dict result in Anthropic-style SSE events
# (mirrors synthesize_mistral_mcp_sse in mistral_mcp.py)
# ---------------------------------------------------------------------------

def synthesize_openai_mcp_sse(result, session_id, metrics, messages,
                               input_price, output_price):
    """Wrap an OpenAI MCP dict result in Anthropic-style SSE events."""
    import json as _json
    from flask import Response, stream_with_context

    oai_history = result.get('oai_history')

    def _save(history):
        from server.routes.chat import _save_session
        extra = {'openai_history': oai_history} if oai_history else None
        _save_session(session_id, history, metrics, extra=extra)

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
        history = messages + [{'role': 'assistant', 'content': content}]
        _save(history)
        yield f"data: {_json.dumps({'type': 'stream_end', 'content': content, 'session_metrics': metrics, 'conversation_history': history, 'usage': usage, 'stop_reason': 'end_turn'})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
