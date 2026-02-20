"""
Chat and streaming routes.

Supports multiple AI providers (Anthropic, OpenAI, Google Gemini, Mistral).
The provider is determined from the ``token_id`` stored in the database or
from an explicit ``provider`` field in the request body.  All streaming
responses are normalised to Anthropic's SSE event format so the front-end
parser works unchanged.
"""

import json
import traceback
import requests
import logging
from flask import Blueprint, request, jsonify, Response, stream_with_context, current_app
from server.mcp import MCPManager
from server.helpers import load_mcp_credentials
from server.providers import get_provider, get_pricing
from server.mcp_client import fetch_mcp_tools, call_mcp_tool, mcp_tools_to_google
from server.mistral_mcp import run_mistral_mcp_sync, synthesize_mistral_mcp_sse, stream_mistral_mcp_live
from server.openai_mcp import run_openai_mcp_sync, synthesize_openai_mcp_sse
from server.anthropic_sdk import (
    run_anthropic_non_streaming,
    stream_anthropic_response,
    run_anthropic_mcp_client_sync,
    synthesize_anthropic_mcp_sse,
    check_anthropic_credit,
)

logger = logging.getLogger(__name__)
chat_bp = Blueprint('chat', __name__)


def _resolve_api_key_and_provider(data):
    """Return ``(api_key, provider_name, error_response | None)``.

    Resolution order for provider:
    1. Explicit ``provider`` field in the request body.
    2. Provider stored against the ``token_id`` in the database.
    3. Falls back to ``'anthropic'``.
    """
    api_key = data.get('api_key')
    token_id = data.get('token_id')
    provider_name = data.get('provider')  # may be None

    if token_id:
        db = current_app.config['db']
        token = db.get_token(token_id)
        if not token:
            return None, None, (jsonify({"error": "Token not found"}), 404)
        if not api_key:
            api_key = token['key']
        if not provider_name:
            provider_name = token.get('provider')

    provider_name = (provider_name or 'anthropic').lower()

    if not api_key:
        return None, None, (jsonify({"error": "API key or token_id is required"}), 400)

    return api_key, provider_name, None


MAX_TOOL_ITERATIONS = 10


def _run_tool_loop(provider, api_key, url, headers, payload, tool_map,
                   model, use_streaming, session_id, metrics, messages,
                   input_price, output_price):
    """Execute a synchronous tool-call loop for non-Anthropic providers.

    1. POST to the LLM (non-streaming).
    2. Check if the response contains tool calls.
    3. If so: execute each tool via MCP, append results, repeat.
    4. When the LLM produces text (no tool calls), return the result.

    If *use_streaming* was ``True``, the final text response is emitted
    as synthesised SSE events so the front-end parser works unchanged.
    """
    # Force non-streaming during the tool loop iterations
    payload.pop('stream', None)
    payload.pop('stream_options', None)

    # Rebuild URL for non-streaming (important for Google where streaming
    # is determined by the URL path, not the payload).
    url = provider.build_url(model=model, stream=False, api_key=api_key)

    cumulative_usage = {'input_tokens': 0, 'output_tokens': 0,
                        'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}
    tool_chain = []

    for iteration in range(MAX_TOOL_ITERATIONS):
        resp = requests.post(url, headers=headers, json=payload, timeout=300)

        if resp.status_code != 200:
            err = provider.parse_error(resp)
            logger.error(f"{provider.name} tool-loop error {resp.status_code}: {err.get('error')}")
            if use_streaming:
                return _emit_sse_error(err)
            return jsonify(err), resp.status_code

        raw = resp.json()

        # Accumulate token usage across iterations
        iter_usage = provider.normalize_usage(raw.get('usage') or raw.get('usageMetadata') or {})
        for k in cumulative_usage:
            cumulative_usage[k] += iter_usage.get(k, 0)

        # Check for tool calls
        tool_calls = []
        if hasattr(provider, 'extract_tool_calls'):
            tool_calls = provider.extract_tool_calls(raw)

        if not tool_calls:
            # Final text response – no more tool calls
            result = provider.parse_response(raw)
            # Merge cumulative usage
            result['usage'] = cumulative_usage
            result['tool_chain'] = tool_chain

            cur_in = cumulative_usage.get('input_tokens', 0)
            cur_out = cumulative_usage.get('output_tokens', 0)
            metrics['total_input_tokens'] += cur_in
            metrics['total_output_tokens'] += cur_out
            metrics['total_cost'] += (cur_in * input_price) + (cur_out * output_price)

            if use_streaming:
                return _synthesize_sse(
                    result, session_id, metrics, messages,
                    input_price, output_price, tool_chain=tool_chain
                )

            result['session_metrics'] = metrics
            history = messages + [{'role': 'assistant', 'content': result.get('content', [])}]
            result['conversation_history'] = history
            _save_session(session_id, history, metrics)
            return jsonify(result)

        # Execute each tool call via MCP and collect results
        tool_results = []
        for tc in tool_calls:
            logger.info(f"Tool call [{iteration+1}]: {tc['name']}")
            mcp_result = call_mcp_tool(tc['name'], tc['arguments'], tool_map)
            # Flatten MCP content array to a string
            content_str = _flatten_mcp_result(mcp_result)
            tool_results.append({
                'id': tc['id'],
                'name': tc['name'],
                'result': content_str,
            })
            # Track tool chain for frontend visualisation
            result_preview = content_str[:500] if len(content_str) > 500 else content_str
            tool_chain.append({
                'iteration': iteration + 1,
                'tool_name': tc['name'],
                'tool_input': tc['arguments'],
                'tool_result': result_preview,
            })

        # Append assistant tool message + tool results to payload
        provider.append_tool_results(payload, raw, tool_results)
        logger.info(f"Tool loop iteration {iteration+1} done, {len(tool_results)} results appended")

    # Exhausted iterations – return what we have
    logger.warning("Tool loop hit max iterations")
    if use_streaming:
        return _emit_sse_error({'error': 'Tool call loop reached maximum iterations'})
    return jsonify({'error': 'Tool call loop reached maximum iterations'}), 500


def _flatten_mcp_result(mcp_result):
    """Convert an MCP tools/call result to a plain text string."""
    if isinstance(mcp_result, str):
        return mcp_result
    if isinstance(mcp_result, dict):
        # MCP tools/call returns {content: [{type, text}], ...}
        content_list = mcp_result.get('content', [])
        if isinstance(content_list, list):
            texts = []
            for c in content_list:
                if isinstance(c, dict) and c.get('text'):
                    texts.append(c['text'])
                elif isinstance(c, str):
                    texts.append(c)
            if texts:
                return '\n'.join(texts)
        # Fallback: serialise the whole dict
        return json.dumps(mcp_result)
    return str(mcp_result)


def _synthesize_sse(result, session_id, metrics, messages,
                    input_price, output_price, tool_chain=None):
    """Wrap a non-streaming result in Anthropic-style SSE events."""
    def generate():
        # message_start
        yield f"data: {json.dumps({'type': 'message_start', 'message': {'id': result.get('id', ''), 'model': result.get('model', ''), 'usage': {'input_tokens': 0, 'output_tokens': 0}}})}\n\n"

        content = result.get('content', [])
        for i, block in enumerate(content):
            yield f"data: {json.dumps({'type': 'content_block_start', 'index': i, 'content_block': {'type': block.get('type', 'text'), 'text': ''}})}\n\n"
            if block.get('type') == 'text':
                yield f"data: {json.dumps({'type': 'content_block_delta', 'index': i, 'delta': {'type': 'text_delta', 'text': block.get('text', '')}})}\n\n"
            yield f"data: {json.dumps({'type': 'content_block_stop', 'index': i})}\n\n"

        usage = result.get('usage', {})
        yield f"data: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': result.get('stop_reason', 'end_turn')}, 'usage': usage})}\n\n"

        history = messages + [{'role': 'assistant', 'content': content}]
        _save_session(session_id, history, metrics)

        yield f"data: {json.dumps({'type': 'stream_end', 'content': content, 'session_metrics': metrics, 'conversation_history': history, 'usage': usage, 'stop_reason': result.get('stop_reason'), 'tool_chain': tool_chain or []})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


def _emit_sse_error(err):
    """Return an SSE response containing a single error event."""
    def generate():
        yield f"data: {json.dumps({'type': 'error', 'error': err.get('error', 'Unknown error')})}\n\n"
    return Response(stream_with_context(generate()), mimetype='text/event-stream')


def _save_session(session_id, history, metrics, extra=None):
    """Persist session metrics and provider state to SQL (best-effort).

    ``extra`` is an optional dict of provider-specific fields to persist
    (e.g. ``mistral_conversation_id``, ``openai_history``).
    """
    if not session_id:
        return
    try:
        db = current_app.config['db']
        db.update_session_state(session_id, metrics, extra=extra)
    except Exception as e:
        logger.warning(f"Could not auto-save session {session_id}: {e}")


def _stream_response(provider, api_key, url, headers, payload,
                     session_id, metrics, messages, input_price, output_price):
    """Stream SSE from any supported AI provider to the client.

    All provider-specific events are normalised to Anthropic's SSE format
    by the provider's ``parse_stream_events`` method.
    """

    def generate():
        try:
            with requests.post(url, headers=headers, json=payload,
                               stream=True, timeout=300) as resp:
                if resp.status_code != 200:
                    err = provider.parse_error(resp)
                    logger.error(f"{provider.name} API error {resp.status_code}: {err.get('error')}")
                    yield f"data: {json.dumps(err)}\n\n"
                    return

                accumulated = []
                usage_data = {}
                stop_reason = None

                for event_str in provider.parse_stream_events(resp):
                    try:
                        event = json.loads(event_str)
                    except json.JSONDecodeError:
                        yield f"data: {event_str}\n\n"
                        continue

                    etype = event.get('type')

                    if etype == 'content_block_start':
                        idx = event.get('index', 0)
                        while len(accumulated) <= idx:
                            accumulated.append({})
                        accumulated[idx] = event.get('content_block', {})

                    elif etype == 'content_block_delta':
                        idx = event.get('index', 0)
                        delta = event.get('delta', {})
                        while len(accumulated) <= idx:
                            accumulated.append({})
                        if delta.get('type') == 'text_delta':
                            accumulated[idx].setdefault('text', '')
                            accumulated[idx]['text'] += delta.get('text', '')
                        elif delta.get('type') == 'thinking_delta':
                            accumulated[idx].setdefault('thinking', '')
                            accumulated[idx]['thinking'] += delta.get('thinking', '')

                    elif etype == 'message_delta':
                        d = event.get('delta', {})
                        if 'stop_reason' in d:
                            stop_reason = d['stop_reason']
                        usage_data.update(event.get('usage', {}))

                    elif etype == 'message_start':
                        usage_data.update(event.get('message', {}).get('usage', {}))

                    yield f"data: {event_str}\n\n"

                # Final summary
                if usage_data:
                    cur_in = usage_data.get('input_tokens', 0)
                    cur_out = usage_data.get('output_tokens', 0)
                    metrics['total_input_tokens'] += cur_in
                    metrics['total_output_tokens'] += cur_out
                    metrics['total_cost'] += (cur_in * input_price) + (cur_out * output_price)

                    history = messages + [{'role': 'assistant', 'content': accumulated}]

                    if session_id:
                        try:
                            db = current_app.config['db']
                            db.update_session_state(session_id, metrics)
                        except Exception as e:
                            logger.warning(f"Could not auto-save session {session_id}: {e}")

                    yield f"data: {json.dumps({'type': 'stream_end', 'content': accumulated, 'session_metrics': metrics, 'conversation_history': history, 'usage': usage_data, 'stop_reason': stop_reason, 'tool_chain': []})}\n\n"

        except Exception as e:
            logger.error(f"Streaming error: {e}")
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@chat_bp.route('/api/check-credit', methods=['POST'])
def check_credit():
    """Check available credit / rate limits for the provided API key.

    Accepts ``api_key`` (required) and ``provider`` (default ``anthropic``).
    """
    try:
        data = request.get_json()
        api_key = data.get('api_key') if data else None
        if not api_key:
            return jsonify({"error": "API key is required"}), 400

        provider_name = (data.get('provider') or 'anthropic').lower()
        provider = get_provider(provider_name)
        if not provider:
            return jsonify({"error": f"Unsupported provider: {provider_name}"}), 400

        if provider_name == 'anthropic':
            result = check_anthropic_credit(api_key)
        else:
            result = provider.check_credit(api_key)
        status = result.pop('status', 200)

        if 'valid' in result and not result['valid']:
            return jsonify(result), status if status >= 400 else 401

        return jsonify(result), status if status < 400 else 200

    except requests.exceptions.Timeout:
        return jsonify({"error": "Request timed out"}), 504
    except Exception as e:
        logger.error(f"Error checking credit: {e}")
        return jsonify({"error": str(e)}), 500


@chat_bp.route('/api/chat', methods=['POST'])
def chat():
    """Proxy endpoint for AI provider API calls with optional streaming.

    Supports Anthropic, OpenAI, Google (Gemini), and Mistral.  The
    provider is determined from the ``token_id`` (looked up in the DB),
    from an explicit ``provider`` field, or defaults to ``anthropic``.

    MCP server tools are supported for all providers:
    - Anthropic: native ``mcp_servers`` in the API payload.
    - Others: client-side tool-call loop via ``mcp_client``.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400

        # Resolve API key and provider
        api_key, provider_name, err = _resolve_api_key_and_provider(data)
        if err:
            return err

        provider = get_provider(provider_name)
        if not provider:
            return jsonify({"error": f"Unsupported provider: {provider_name}"}), 400

        messages = data.get('messages', [])
        if not messages:
            return jsonify({"error": "Messages are required"}), 400

        # Inject token's system prompt if one is configured, and not already present
        token_id_for_prompt = data.get('token_id')
        if token_id_for_prompt:
            token_record = current_app.config['db'].get_token(token_id_for_prompt)
            if token_record:
                system_prompt = (token_record.get('system_prompt') or '').strip()
                if system_prompt and (not messages or messages[0].get('role') != 'system'):
                    messages = [{'role': 'system', 'content': system_prompt}] + messages

        use_streaming = data.get('stream', False)
        session_id = data.get('session_id')
        model = data.get('model', provider.default_model)

        # Load existing session metrics and provider-specific state
        sd = {}
        metrics = {'total_input_tokens': 0, 'total_output_tokens': 0, 'total_cost': 0.0}
        if session_id:
            try:
                db_inst = current_app.config['db']
                sd = db_inst.get_session_state(session_id)
                metrics['total_input_tokens'] = sd.get('total_input_tokens', 0)
                metrics['total_output_tokens'] = sd.get('total_output_tokens', 0)
                metrics['total_cost'] = sd.get('total_cost', 0.0)
            except Exception:
                pass

        # Provider-specific conversation state persisted across turns
        mistral_conversation_id = sd.get('mistral_conversation_id')
        openai_history = sd.get('openai_history')

        # Look up per-model pricing
        db = current_app.config['db']
        input_price, output_price = get_pricing(provider_name, model, db)

        # Extract optional sampling parameters from the request
        _temperature = data.get('temperature')
        _top_p = data.get('top_p')
        _stop_sequences = data.get('stop_sequences')

        # Build provider-specific payload
        extra_kwargs = {}
        if _temperature is not None:
            extra_kwargs['temperature'] = _temperature
        if _top_p is not None:
            extra_kwargs['top_p'] = _top_p
        if _stop_sequences:
            extra_kwargs['stop_sequences'] = _stop_sequences

        # ── MCP server enrichment (runs for ALL providers) ──────────
        enriched_servers = []
        servers_data = data.get('servers')
        if servers_data:
            saved = load_mcp_credentials(current_app)
            for srv in servers_data:
                sid = srv.get('id')
                if sid and sid in saved:
                    s = saved[sid]
                    auth_method = srv.get('auth_type') or s.get('auth_method') or s.get('auth_type')
                    if auth_method == 'oauth2':
                        token = s.get('access_token') or s.get('token') or s.get('auth_token', '')
                    else:
                        token = s.get('token') or s.get('auth_token', '')
                    enriched_servers.append({
                        'id': sid,
                        'name': srv.get('name') or s.get('name'),
                        'url': srv.get('url') or s.get('url'),
                        'auth_type': auth_method,
                        'auth_token': token,
                        'auth_method': auth_method,
                        **(({'headers': s['headers']} if s.get('headers') else {})),
                    })
                else:
                    enriched_servers.append(srv)

            # Log enriched servers summary (mask tokens for security)
            for es in enriched_servers:
                logger.info(
                    f"Enriched server {es.get('id')}: url={'SET' if es.get('url') else 'EMPTY'}, "
                    f"auth_type={es.get('auth_type')!r}, "
                    f"has_auth_token={bool(es.get('auth_token'))}, "
                    f"has_headers={bool(es.get('headers'))}"
                )

            proxy = current_app.config.get('proxy_manager')
            if proxy:
                proxy.sync_servers({s['id']: s for s in enriched_servers if s.get('id')})

        # ── Branch: per-provider MCP / SDK routing ──────────────────
        mcp_servers = None   # Anthropic-native MCP list
        tool_map = None      # Non-Anthropic client-side tool map
        has_tools = False

        if enriched_servers and provider_name == 'anthropic':
            # ── Anthropic: native MCP or client-side fallback ─────────
            # Servers that carry custom headers (e.g. Business Central)
            # can only use native Anthropic MCP when a public HTTPS proxy
            # is available to inject those headers.  Without it, fall back
            # to our client-side tool loop so the headers are applied here.
            proxy_mgr = current_app.config.get('proxy_manager')
            needs_client_side = any(
                bool(srv.get('headers'))
                and (not proxy_mgr or not proxy_mgr.is_publicly_accessible)
                for srv in enriched_servers
            )

            if needs_client_side:
                # Client-side loop: our server fetches tools + executes calls
                try:
                    result = run_anthropic_mcp_client_sync(
                        api_key=api_key,
                        model=model,
                        messages=messages,
                        enriched_servers=enriched_servers,
                        max_tokens=data.get('max_tokens', 2000),
                        app=current_app._get_current_object(),
                        stream=use_streaming,
                    )
                    if use_streaming:
                        return synthesize_anthropic_mcp_sse(
                            result, session_id, metrics, messages,
                            input_price, output_price,
                        )
                    usage = result.get('usage', {})
                    cur_in = usage.get('input_tokens', 0)
                    cur_out = usage.get('output_tokens', 0)
                    metrics['total_input_tokens'] += cur_in
                    metrics['total_output_tokens'] += cur_out
                    metrics['total_cost'] += (cur_in * input_price) + (cur_out * output_price)
                    result['session_metrics'] = metrics
                    # Use the full internal history with proper role alternation
                    # (tool_result in user messages, not assistant messages).
                    history = result.get('history') or (messages + [{'role': 'assistant', 'content': result.get('content', [])}])
                    result['conversation_history'] = history
                    _save_session(session_id, history, metrics)
                    return jsonify(result)
                except Exception as e:
                    logger.error(f"Anthropic client-side MCP error: {e}\n{traceback.format_exc()}")
                    return jsonify({'error': f'Anthropic MCP error: {str(e)}'}), 500
            else:
                # Native path: Anthropic's servers connect to MCP directly
                mgr = MCPManager.from_request_data({'servers': enriched_servers})
                mcp_servers = mgr.prepare_for_anthropic(data.get('enabled_servers'))
                # Anthropic requires every mcp_server to be referenced by an
                # mcp_toolset entry in tools, otherwise it returns a 400.
                extra_kwargs['tools'] = [
                    {'type': 'mcp_toolset', 'mcp_server_name': s.get('name', 'Unknown')}
                    for s in mcp_servers
                ]
                has_tools = True

        elif enriched_servers and provider_name == 'mistral':
            # ── Mistral: SDK with native MCP Conversations API ───────
            if use_streaming:
                # Live streaming path — returns SSE immediately, runs loop in thread
                return stream_mistral_mcp_live(
                    api_key=api_key,
                    model=model,
                    messages=messages,
                    enriched_servers=enriched_servers,
                    max_tokens=data.get('max_tokens', 2000),
                    app=current_app._get_current_object(),
                    session_id=session_id,
                    metrics=metrics,
                    messages_orig=messages,
                    input_price=input_price,
                    output_price=output_price,
                    conversation_id=mistral_conversation_id,
                )
            try:
                result = run_mistral_mcp_sync(
                    api_key=api_key,
                    model=model,
                    messages=messages,
                    enriched_servers=enriched_servers,
                    max_tokens=data.get('max_tokens', 2000),
                    app=current_app._get_current_object(),
                    stream=False,
                    conversation_id=mistral_conversation_id,
                )
                usage = result.get('usage', {})
                cur_in = usage.get('input_tokens', 0)
                cur_out = usage.get('output_tokens', 0)
                metrics['total_input_tokens'] += cur_in
                metrics['total_output_tokens'] += cur_out
                metrics['total_cost'] += (cur_in * input_price) + (cur_out * output_price)
                result['session_metrics'] = metrics
                history = messages + [{'role': 'assistant', 'content': result.get('content', [])}]
                result['conversation_history'] = history
                new_conv_id = result.get('mistral_conversation_id')
                extra = {'mistral_conversation_id': new_conv_id} if new_conv_id else None
                _save_session(session_id, history, metrics, extra=extra)
                return jsonify(result)
            except BaseException as e:
                logger.error(f"Mistral SDK MCP error: {e}\n{traceback.format_exc()}")
                return jsonify({'error': str(e)}), 500

        elif enriched_servers and provider_name == 'openai':
            # ── OpenAI: SDK with client-side MCP tool loop ───────────
            try:
                result = run_openai_mcp_sync(
                    api_key=api_key,
                    model=model,
                    messages=messages,
                    enriched_servers=enriched_servers,
                    max_tokens=data.get('max_tokens', 2000),
                    app=current_app._get_current_object(),
                    stream=use_streaming,
                    existing_oai_messages=openai_history,
                )
                if use_streaming:
                    return synthesize_openai_mcp_sse(
                        result, session_id, metrics, messages,
                        input_price, output_price,
                    )
                usage = result.get('usage', {})
                cur_in = usage.get('input_tokens', 0)
                cur_out = usage.get('output_tokens', 0)
                metrics['total_input_tokens'] += cur_in
                metrics['total_output_tokens'] += cur_out
                metrics['total_cost'] += (cur_in * input_price) + (cur_out * output_price)
                result['session_metrics'] = metrics
                history = messages + [{'role': 'assistant', 'content': result.get('content', [])}]
                result['conversation_history'] = history
                new_oai_history = result.get('oai_history')
                extra = {'openai_history': new_oai_history} if new_oai_history else None
                _save_session(session_id, history, metrics, extra=extra)
                return jsonify(result)
            except Exception as e:
                logger.error(f"OpenAI SDK MCP error: {e}\n{traceback.format_exc()}")
                return jsonify({'error': f'OpenAI MCP error: {str(e)}'}), 500

        elif enriched_servers and provider_name == 'google':
            # ── Google: client-side MCP tool loop (HTTP) ─────────────
            try:
                tool_defs, tool_map = fetch_mcp_tools(current_app, enriched_servers)
                if tool_defs:
                    extra_kwargs['tools'] = mcp_tools_to_google(tool_defs)
                    has_tools = True
                    logger.info(f"Loaded {len(tool_defs)} MCP tools for google")
            except Exception as e:
                logger.warning(f"Failed to fetch MCP tools for google: {e}")

        # ── Anthropic via SDK (standard + MCP) ──────────────────────
        if provider_name == 'anthropic':
            system = None
            filtered_messages = []
            for msg in messages:
                if msg.get('role') == 'system':
                    from server.providers import _content_blocks_to_text
                    system = _content_blocks_to_text(msg.get('content', ''))
                else:
                    filtered_messages.append(msg)

            sdk_messages = filtered_messages if filtered_messages else messages

            if use_streaming:
                return stream_anthropic_response(
                    api_key=api_key,
                    model=model,
                    messages=sdk_messages,
                    max_tokens=data.get('max_tokens', 2000),
                    mcp_servers=mcp_servers,
                    tools=extra_kwargs.get('tools'),
                    system=system,
                    session_id=session_id,
                    metrics=metrics,
                    input_price=input_price,
                    output_price=output_price,
                    existing_messages=messages,
                    temperature=_temperature,
                    top_p=_top_p,
                    stop_sequences=_stop_sequences,
                )

            # Non-streaming Anthropic
            try:
                result = run_anthropic_non_streaming(
                    api_key=api_key,
                    model=model,
                    messages=sdk_messages,
                    max_tokens=data.get('max_tokens', 2000),
                    mcp_servers=mcp_servers,
                    tools=extra_kwargs.get('tools'),
                    system=system,
                    temperature=_temperature,
                    top_p=_top_p,
                    stop_sequences=_stop_sequences,
                )
            except RuntimeError as e:
                logger.error(f"Anthropic SDK error: {e}")
                return jsonify({'error': str(e)}), 400

            usage = result.get('usage', {})
            cur_in = usage.get('input_tokens', 0)
            cur_out = usage.get('output_tokens', 0)
            metrics['total_input_tokens'] += cur_in
            metrics['total_output_tokens'] += cur_out
            metrics['total_cost'] += (cur_in * input_price) + (cur_out * output_price)

            result['session_metrics'] = metrics
            content = result.get('content', [])
            history = messages + [{'role': 'assistant', 'content': content}]
            result['conversation_history'] = history
            _save_session(session_id, history, metrics)
            return jsonify(result)

        # ── Non-Anthropic standard HTTP path (OpenAI no-MCP, Google) ─
        payload = provider.build_payload(
            model, messages, data.get('max_tokens', 2000),
            stream=use_streaming, **extra_kwargs,
        )
        headers = provider.build_headers(api_key)
        url = provider.build_url(model=model, stream=use_streaming, api_key=api_key)

        # Google client-side tool loop
        if has_tools and tool_map and provider_name == 'google':
            return _run_tool_loop(
                provider, api_key, url, headers, payload, tool_map,
                model, use_streaming, session_id, metrics, messages,
                input_price, output_price,
            )

        # ── Standard streaming / non-streaming ───────────────────────
        if use_streaming:
            return _stream_response(
                provider, api_key, url, headers, payload,
                session_id, metrics, messages, input_price, output_price,
            )

        # Non-streaming
        resp = requests.post(url, headers=headers, json=payload, timeout=300)

        if resp.status_code != 200:
            err = provider.parse_error(resp)
            logger.error(f"{provider_name} API error {resp.status_code}: {err.get('error')}")
            return jsonify(err), resp.status_code

        result = provider.parse_response(resp.json())

        usage = result.get('usage', {})
        cur_in = usage.get('input_tokens', 0)
        cur_out = usage.get('output_tokens', 0)
        metrics['total_input_tokens'] += cur_in
        metrics['total_output_tokens'] += cur_out
        metrics['total_cost'] += (cur_in * input_price) + (cur_out * output_price)

        result['session_metrics'] = metrics
        history = messages + [{'role': 'assistant', 'content': result.get('content', [])}]
        result['conversation_history'] = history
        _save_session(session_id, history, metrics)
        return jsonify(result)

    except requests.exceptions.Timeout:
        return jsonify({"error": "Request to AI provider timed out"}), 504
    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Network error: {str(e)}"}), 503
    except Exception as e:
        logger.error(f"Unexpected error in chat endpoint: {e}\n{traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500
