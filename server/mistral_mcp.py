"""
Mistral SDK-based MCP integration.

Uses the ``mistralai`` Python SDK's Conversations API with MCP clients
to natively handle remote MCP servers.  The SDK manages the tool-call loop
internally, so we just need to translate inputs/outputs for our front-end.

Supports **both** MCP transport protocols:
- Streamable HTTP (newer, POST-based) – tried first
- SSE (legacy, GET-based)              – fallback

Key classes from the SDK:
- ``Mistral``              – client initialised with the API key
- ``MCPClientBase``        – abstract base for MCP clients
- ``RunContext``           – holds registered MCP clients and tools
- ``RunResult``            – final result of a conversation run
- ``RunResultEvents``      – individual streamed events
"""

import asyncio
import json
import logging
import queue as _queue
import threading
import typing
from contextlib import AsyncExitStack
from typing import List, Optional

import httpx
from mistralai import Mistral
from mistralai.extra.mcp.base import MCPClientBase
from mistralai.extra.mcp.sse import MCPClientSSE, SSEServerParams
from mistralai.extra.run.context import RunContext, RunMCPTool, _validate_run
from mistralai.extra.run.tools import get_function_calls
from mistralai.models.functioncallentry import FunctionCallEntry
from mistralai.models.functionresultentry import FunctionResultEntry
from mistralai.models.messageoutputentry import MessageOutputEntry
from mcp.client.streamable_http import streamable_http_client

from server.helpers import apply_auth_to_request

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Direct tool execution — bypasses RunContext.execute_function_calls()
# ---------------------------------------------------------------------------

async def _execute_tools_direct(
    run_ctx: RunContext,
    fcalls: list,
) -> list:
    """Execute MCP tool calls directly, bypassing the SDK's name-lookup check.

    ``RunContext.execute_function_calls`` aborts with an empty list if any
    function-call name is not found in ``_callable_tools``.  This happens
    intermittently with some MCP servers (e.g. GitHub Copilot) whose GET
    stream returns 405, leaving an anyio reconnect task in-flight that
    prevents normal asyncio dispatch.

    This helper:
    1. Looks up each call in ``_callable_tools`` (exact match).
    2. Falls back to calling ``execute_tool`` on every registered MCP client
       if the name is missing from the registry.
    3. Always returns one ``FunctionResultEntry`` per input call — never an
       empty list — so the loop can continue.
    """
    # Collect all unique MCP clients currently registered
    all_clients = list({
        tool.mcp_client
        for tool in run_ctx._callable_tools.values()
        if isinstance(tool, RunMCPTool)
    })

    results = []
    for fc in fcalls:
        name = fc.name
        tool_call_id = fc.tool_call_id

        # Parse arguments
        raw_args = fc.arguments
        if isinstance(raw_args, str):
            try:
                arguments = json.loads(raw_args)
            except (json.JSONDecodeError, TypeError):
                arguments = {}
        elif isinstance(raw_args, dict):
            arguments = raw_args
        else:
            arguments = {}

        result_text: str | None = None
        try:
            run_tool = run_ctx._callable_tools.get(name)
            if run_tool is not None and isinstance(run_tool, RunMCPTool):
                # Standard path
                chunks = await run_tool.mcp_client.execute_tool(name, arguments)
                result_text = _chunks_to_text(chunks)
            else:
                # Name not in registry — try every registered client
                logger.warning(
                    f"Tool '{name}' not in _callable_tools "
                    f"(registered: {list(run_ctx._callable_tools.keys())}); "
                    f"trying all {len(all_clients)} client(s) directly"
                )
                for client in all_clients:
                    try:
                        chunks = await client.execute_tool(name, arguments)
                        result_text = _chunks_to_text(chunks)
                        logger.info(f"Tool '{name}' executed via client '{client._name}'")
                        break
                    except Exception as exc:
                        logger.debug(
                            f"Client '{client._name}' failed for '{name}': {exc}"
                        )
                if result_text is None:
                    result_text = f"Error: tool '{name}' not found on any registered MCP server"
        except Exception as exc:
            logger.warning(f"Tool execution failed for '{name}': {exc}")
            result_text = f"Error executing '{name}': {exc}"

        results.append(FunctionResultEntry(
            tool_call_id=tool_call_id,
            result=result_text,
        ))

    return results


def _chunks_to_text(chunks) -> str:
    """Convert MCP content chunks (list of TextChunkTypedDict) to a plain string."""
    if isinstance(chunks, str):
        return chunks
    if isinstance(chunks, list):
        return "\n".join(
            c.get("text", "") if isinstance(c, dict) else str(c)
            for c in chunks
        )
    return str(chunks) if chunks else ""


# ---------------------------------------------------------------------------
# Exception-group helpers
# ---------------------------------------------------------------------------

def _flatten_exception_group(exc):
    """Recursively extract leaf exceptions from an ExceptionGroup."""
    leaves = []
    if isinstance(exc, BaseExceptionGroup):
        for sub in exc.exceptions:
            leaves.extend(_flatten_exception_group(sub))
    else:
        leaves.append(exc)
    return leaves


def _format_exception_group(exc):
    """Return a human-readable string from an ExceptionGroup."""
    if not isinstance(exc, BaseExceptionGroup):
        return str(exc)
    leaves = _flatten_exception_group(exc)
    parts = [f"{type(e).__name__}: {e}" for e in leaves]
    return "; ".join(parts) or str(exc)


# ---------------------------------------------------------------------------
# Streamable-HTTP MCP client (subclass of the SDK base class)
# ---------------------------------------------------------------------------

class MCPClientStreamableHTTP(MCPClientBase):
    """MCP client using the newer *Streamable HTTP* transport.

    The ``mcp`` library's ``streamable_http_client`` connects via POST-based
    HTTP rather than a long-lived SSE GET stream.  Many newer MCP servers
    (e.g. Popdock) require this transport.

    Overrides ``aclose()`` to suppress the ``BaseExceptionGroup`` that
    ``anyio``'s task-group teardown raises when background transport tasks
    accumulated errors (e.g. a 401 during ``initialize``).
    """

    def __init__(self, url: str, headers: dict | None = None,
                 name: str | None = None, timeout: float = 30):
        super().__init__(name=name)
        self._url = url
        self._headers = headers or {}
        self._timeout = timeout

    async def _get_transport(self, exit_stack: AsyncExitStack):
        http_client = httpx.AsyncClient(
            headers=self._headers,
            timeout=httpx.Timeout(self._timeout, read=300),
        )
        # streamable_http_client returns (read, write, get_session_id)
        # MCPClientBase.initialize() only uses [0] and [1]
        return await exit_stack.enter_async_context(
            streamable_http_client(
                url=self._url,
                http_client=http_client,
            )
        )

    async def aclose(self):
        """Close the client, suppressing anyio task-group cleanup errors."""
        try:
            await super().aclose()
        except BaseExceptionGroup as eg:
            logger.debug(
                f"Suppressed transport cleanup error for '{self._name}': "
                f"{_format_exception_group(eg)}"
            )


# ---------------------------------------------------------------------------
# Build MCP clients – tries Streamable HTTP first, falls back to SSE
# ---------------------------------------------------------------------------

def _build_mcp_clients(app, enriched_servers):
    """Build MCP client instances from enriched server dicts.

    For each server we create **two** candidate clients:
    1. ``MCPClientStreamableHTTP`` (preferred – newer POST-based transport)
    2. ``MCPClientSSE``           (fallback – legacy GET-based SSE transport)

    The caller (``_run_mistral_conversation``) will attempt to register them
    with the ``RunContext``; if the first fails, the fallback is tried.

    Returns
    -------
    list[tuple[MCPClientBase, MCPClientBase | None]]
        Each element is ``(primary_client, fallback_client_or_None)``.
    """
    client_pairs = []
    logger.info(f"Building MCP clients for {len(enriched_servers)} enriched servers")
    for srv in enriched_servers:
        sid = srv.get('id', '')
        url = srv.get('url', '')
        auth_type = srv.get('auth_type') or srv.get('auth_method', '')
        has_token = bool(srv.get('token') or srv.get('auth_token') or srv.get('access_token'))
        logger.info(
            f"MCP server {sid}: url={'SET' if url else 'EMPTY'}, "
            f"auth_type={auth_type!r}, has_token={has_token}"
        )
        if not url:
            logger.warning(f"Skipping MCP server {sid}: no URL")
            continue

        # Build auth headers the same way the rest of the app does
        hdrs = {
            'Content-Type': 'application/json',
            'Accept': 'application/json,text/event-stream',
        }

        # Merge custom server headers (e.g. Company, ConfigurationName for BC)
        custom_headers = srv.get('headers')
        if custom_headers and isinstance(custom_headers, dict):
            hdrs.update(custom_headers)

        try:
            url, hdrs, err = apply_auth_to_request(app, sid, srv, url, hdrs)
        except Exception as exc:
            # apply_auth_to_request may call jsonify() which needs Flask
            # context — fall back to manual auth when outside request context
            logger.warning(
                f"apply_auth_to_request raised for {sid}: {exc}.  "
                f"Falling back to manual auth."
            )
            err = None
            token_value = (srv.get('token') or srv.get('auth_token')
                           or srv.get('access_token'))
            if auth_type in ('bearer', 'bearer_token'):
                if token_value:
                    hdrs['Authorization'] = f'Bearer {token_value}'
            elif auth_type == 'oauth2':
                if token_value:
                    hdrs['Authorization'] = f'Bearer {token_value}'

        if err:
            logger.warning(f"Auth error for MCP server {sid}, skipping: {err}")
            continue

        has_auth = 'Authorization' in hdrs
        logger.info(
            f"MCP server {sid} auth applied: has_authorization_header={has_auth}"
        )

        name = srv.get('name') or sid

        # Primary: Streamable HTTP
        primary = MCPClientStreamableHTTP(
            url=url, headers=hdrs, name=name, timeout=30,
        )

        # Fallback: SSE
        sse_params = SSEServerParams(url=url, headers=hdrs, timeout=30)
        fallback = MCPClientSSE(sse_params=sse_params, name=name)

        client_pairs.append((primary, fallback))
        logger.info(f"Prepared MCP clients for server {sid} ({name})")

    return client_pairs


# ---------------------------------------------------------------------------
# Safe client initialisation helpers
# ---------------------------------------------------------------------------

async def _safe_init_and_register(run_ctx, mcp_client: MCPClientBase):
    """Initialise an MCP client with its **own** exit stack.

    By *not* passing ``run_ctx._exit_stack`` we isolate the anyio
    task-group that ``streamable_http_client`` / ``sse_client`` create.
    If initialisation fails, the client's resources are cleaned up
    immediately (suppressing any ``BaseExceptionGroup``).

    On success the client keeps its own exit stack alive — the caller
    is responsible for eventually calling ``mcp_client.aclose()``.

    Raises on failure (after cleanup).
    """
    try:
        # initialize() with no exit_stack → client creates its own
        await mcp_client.initialize()
    except BaseException:
        # Clean up immediately; suppress any cascading cleanup errors
        try:
            await mcp_client.aclose()
        except BaseException:
            pass
        raise


async def _attach_clients_to_run_ctx(run_ctx: RunContext,
                                     clients: list[MCPClientBase]):
    """Register already-initialised MCP clients' tools with a RunContext.

    We intentionally do **not** append to ``run_ctx._mcp_clients`` because
    the caller manages client lifecycle in its own ``finally`` block.
    Appending would cause RunContext.__aexit__ to double-close them.
    """
    for mcp_client in clients:
        tools = await mcp_client.get_tools()
        for tool in tools:
            logger.info(
                f"Adding tool {tool.function.name} from "
                f"{mcp_client._name or 'mcp client'}"
            )
            run_ctx._callable_tools[tool.function.name] = RunMCPTool(
                name=tool.function.name,
                tool=tool,
                mcp_client=mcp_client,
            )


async def _run_mistral_conversation(
    api_key: str,
    model: str,
    messages: list,
    enriched_servers: list,
    max_tokens: int,
    app,
    stream: bool = False,
    conversation_id: Optional[str] = None,
    event_queue: Optional[_queue.Queue] = None,
):
    """Run a Mistral conversation with MCP tools via the SDK.

    Parameters
    ----------
    api_key : str
        Mistral API key.
    model : str
        Model name (e.g. ``mistral-large-latest``).
    messages : list
        Conversation history in Anthropic format (will be converted).
    enriched_servers : list
        MCP server dicts with auth already enriched.
    max_tokens : int
        Max output tokens.
    app : Flask app
        Needed for ``apply_auth_to_request``.
    stream : bool
        Whether to stream the response.

    Returns
    -------
    For non-streaming: dict with ``content``, ``usage``, ``model``, etc.
    For streaming: async generator yielding Anthropic-normalised SSE strings.
    """
    client = Mistral(api_key=api_key)
    client_pairs = _build_mcp_clients(app, enriched_servers)

    if not client_pairs:
        raise RuntimeError("No MCP servers could be initialised")

    # Convert Anthropic-format messages to a single user input string
    # The Conversations API takes ``inputs`` as the user prompt; prior
    # context is managed as conversation history on Mistral's side.
    user_input = _extract_latest_user_input(messages)

    # Initialise each MCP client with its **own** exit stack (not
    # RunContext's) so that if a transport fails (e.g. 401 from BC),
    # the broken anyio-task-group context doesn't linger in RunContext's
    # stack and explode during cleanup.
    #
    # On success we manually register the tools with RunContext.  The
    # client's own exit stack keeps the transport alive and is closed
    # when RunContext.__aexit__ calls mcp_client.aclose().
    successfully_registered: list[MCPClientBase] = []

    for primary, fallback in client_pairs:
        registered = False
        # Try primary (Streamable HTTP) first
        try:
            await _safe_init_and_register(run_ctx=None, mcp_client=primary)
            registered = True
            successfully_registered.append(primary)
            logger.info(f"Registered MCP client '{primary._name}' via Streamable HTTP")
        except BaseException as e:
            logger.info(
                f"Streamable HTTP failed for '{primary._name}': "
                f"{_format_exception_group(e)}.  Trying SSE fallback..."
            )
        # Fallback to SSE if primary failed
        if not registered and fallback:
            try:
                await _safe_init_and_register(run_ctx=None, mcp_client=fallback)
                successfully_registered.append(fallback)
                logger.info(f"Registered MCP client '{fallback._name}' via SSE")
            except BaseException as e2:
                logger.warning(
                    f"Both transports failed for '{fallback._name}': "
                    f"{_format_exception_group(e2)}.  Skipping this server."
                )

    if not successfully_registered:
        raise RuntimeError(
            "No MCP tools could be registered — all servers failed to connect"
        )

    # Now run inside RunContext, registering pre-initialised clients
    result = None
    try:
        async with RunContext(model=model, continue_on_fn_error=True) as run_ctx:
            await _attach_clients_to_run_ctx(run_ctx, successfully_registered)

            registered_tools = run_ctx.get_tools()
            logger.info(
                f"Mistral run_async: model={model}, "
                f"user_input={user_input!r:.200}, "
                f"tools_count={len(registered_tools)}, "
                f"tool_names={[t.function.name for t in registered_tools]}"
            )

            if not registered_tools:
                raise RuntimeError(
                    "No MCP tools could be registered — servers connected "
                    "but exposed no tools"
                )

            result = await _run_manual_loop(
                client, run_ctx, user_input, model, stream=stream,
                conversation_id=conversation_id,
                event_queue=event_queue,
            )
    except BaseException as exc:
        # Suppress cleanup ExceptionGroup if we already have a result
        if result is not None:
            logger.warning(
                f"Ignoring cleanup error after successful Mistral conversation: "
                f"{_format_exception_group(exc)}"
            )
        else:
            detail = _format_exception_group(exc)
            logger.error(f"Mistral MCP conversation failed: {detail}")
            raise RuntimeError(f"Mistral MCP error: {detail}") from exc
    finally:
        # Close all clients we initialised (suppress cleanup errors)
        for mcp_client in successfully_registered:
            try:
                await mcp_client.aclose()
            except BaseException as close_err:
                logger.debug(
                    f"Suppressed close error for '{mcp_client._name}': "
                    f"{_format_exception_group(close_err)}"
                )

    return result


# ---------------------------------------------------------------------------
# Manual conversation loop — replaces SDK's run_async so we can capture
# usage and intermediate tool call / tool result entries.
# ---------------------------------------------------------------------------

async def _run_manual_loop(client, run_ctx, user_input, model, stream=False,
                           conversation_id=None, event_queue=None):
    """Run the Mistral conversation loop manually (start_async + append_async).

    This mirrors what ``client.beta.conversations.run_async()`` does internally
    but also captures ``res.usage`` at each step and builds Anthropic-format
    content blocks for tool_use / tool_result so the frontend can display them.

    If ``conversation_id`` is provided the loop resumes an existing Mistral
    Conversations API session (calls ``append_async`` immediately rather than
    ``start_async``), preserving server-side history across HTTP requests.

    If ``event_queue`` is provided, progress events are pushed to it as the
    loop runs so a streaming Flask response can relay them to the browser.
    """
    from mistralai.beta import Beta
    from mistralai.models import MessageInputEntry

    # Resume an existing server-side conversation when we have an ID
    if conversation_id:
        run_ctx.conversation_id = conversation_id

    # Prepare the request kwargs (model, tools, etc.)
    req, run_result, input_entries = await _validate_run(
        beta_client=Beta(client.sdk_configuration),
        run_ctx=run_ctx,
        inputs=user_input,
    )

    # Accumulate usage across all loop iterations
    total_usage = {
        'input_tokens': 0,
        'output_tokens': 0,
        'cache_creation_input_tokens': 0,
        'cache_read_input_tokens': 0,
    }

    # Anthropic-format content blocks (tool_use, tool_result, text)
    content_blocks = []

    # SSE block index — monotonically increasing across all content blocks emitted
    block_idx = 0

    MAX_ITERATIONS = 10
    for iteration in range(MAX_ITERATIONS):
        # Signal to the browser that the model is thinking
        if event_queue:
            event_queue.put({'type': 'progress', 'text': 'Thinking...'})

        if run_ctx.conversation_id is None:
            res = await client.beta.conversations.start_async(
                inputs=input_entries,
                **req,
            )
            run_ctx.conversation_id = res.conversation_id
            logger.info(f"Started conversation {res.conversation_id}")
        else:
            res = await client.beta.conversations.append_async(
                conversation_id=run_ctx.conversation_id,
                inputs=input_entries,
            )

        run_ctx.request_count += 1

        # Accumulate usage from this response
        if hasattr(res, 'usage') and res.usage:
            u = res.usage
            total_usage['input_tokens'] += getattr(u, 'prompt_tokens', 0) or 0
            total_usage['output_tokens'] += getattr(u, 'completion_tokens', 0) or 0

        # Process output entries
        run_result.output_entries.extend(res.outputs)

        logger.info(
            f"Iteration {iteration} outputs: "
            + ", ".join(f"{type(e).__name__}({getattr(e, 'content', getattr(e, 'result', ''))!r:.80}"
                        for e in res.outputs)
        )

        # Check for function calls
        fcalls = get_function_calls(res.outputs)

        if not fcalls:
            # No more tool calls — extract final text from output entries
            for entry in res.outputs:
                if isinstance(entry, MessageOutputEntry):
                    thinking_text = ''
                    text = ''
                    c = entry.content
                    if isinstance(c, str):
                        text = c
                    elif hasattr(c, 'text'):
                        text = c.text
                    elif isinstance(c, list):
                        for part in c:
                            ptype = getattr(part, 'type', None)
                            # ThinkChunk: Magistral reasoning — extract as thinking
                            if ptype == 'thinking' or type(part).__name__ == 'ThinkChunk':
                                chunks = getattr(part, 'thinking', None) or []
                                thinking_text += ''.join(
                                    getattr(ch, 'text', '') for ch in chunks
                                    if hasattr(ch, 'text')
                                )
                            elif hasattr(part, 'text'):
                                text += part.text
                            # Skip other chunk types (e.g. unknown) rather than str()
                    else:
                        text = str(c) if c else ''

                    # Emit thinking block if present (Magistral extended thinking)
                    if thinking_text:
                        content_blocks.append({'type': 'thinking', 'thinking': thinking_text})
                        if event_queue:
                            event_queue.put({'type': 'content_block_start', 'index': block_idx,
                                             'content_block': {'type': 'thinking', 'thinking': ''}})
                            event_queue.put({'type': 'content_block_delta', 'index': block_idx,
                                             'delta': {'type': 'thinking_delta', 'thinking': thinking_text}})
                            event_queue.put({'type': 'content_block_stop', 'index': block_idx})
                            block_idx += 1

                    if text:
                        content_blocks.append({'type': 'text', 'text': text})
                        if event_queue:
                            event_queue.put({'type': 'content_block_start', 'index': block_idx,
                                             'content_block': {'type': 'text', 'text': ''}})
                            event_queue.put({'type': 'content_block_delta', 'index': block_idx,
                                             'delta': {'type': 'text_delta', 'text': text}})
                            event_queue.put({'type': 'content_block_stop', 'index': block_idx})
                            block_idx += 1
                else:
                    # Log unexpected entry types so we can handle them
                    logger.info(
                        f"Non-MessageOutputEntry in final outputs: "
                        f"{type(entry).__name__}: {entry!r:.200}"
                    )
            break
        else:
            # Convert function calls to Anthropic-format tool_use blocks
            for fc in fcalls:
                args = fc.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {'raw': args}

                content_blocks.append({
                    'type': 'tool_use',
                    'id': fc.tool_call_id,
                    'name': fc.name,
                    'input': args if isinstance(args, dict) else {},
                })
                if event_queue:
                    event_queue.put({'type': 'content_block_start', 'index': block_idx,
                                     'content_block': {'type': 'tool_use', 'id': fc.tool_call_id,
                                                       'name': fc.name,
                                                       'input': args if isinstance(args, dict) else {}}})
                    event_queue.put({'type': 'content_block_stop', 'index': block_idx})
                    block_idx += 1

            # Signal which tools are being called
            if event_queue:
                names = ', '.join(fc.name for fc in fcalls)
                event_queue.put({'type': 'progress', 'text': f'Calling {names}...'})

            # Execute tool calls directly — bypasses RunContext name-check
            fresults = await _execute_tools_direct(run_ctx, fcalls)

            if not fresults:
                logger.warning("_execute_tools_direct returned empty list; breaking loop")
                break

            # Convert function results to Anthropic-format tool_result blocks
            for fr in fresults:
                result_text = fr.result if isinstance(fr.result, str) else json.dumps(fr.result)
                content_blocks.append({
                    'type': 'tool_result',
                    'tool_use_id': fr.tool_call_id,
                    'content': result_text,
                })
                if event_queue:
                    event_queue.put({'type': 'content_block_start', 'index': block_idx,
                                     'content_block': {'type': 'tool_result',
                                                       'tool_use_id': fr.tool_call_id,
                                                       'content': result_text}})
                    event_queue.put({'type': 'content_block_stop', 'index': block_idx})
                    block_idx += 1

            run_result.output_entries.extend(fresults)
            input_entries = typing.cast(list, fresults)

    logger.info(
        f"Mistral loop done: iterations={run_ctx.request_count}, "
        f"content_blocks={len(content_blocks)}, "
        f"usage={total_usage}"
    )

    # If no text block was captured (e.g. tool calls but no final response extracted),
    # fall back to the SDK's accumulated output text.
    has_text = any(b.get('type') == 'text' for b in content_blocks)
    if not has_text:
        fallback = run_result.output_as_text
        if fallback:
            logger.info(f"Using run_result.output_as_text fallback: {fallback!r:.200}")
            content_blocks.append({'type': 'text', 'text': fallback})
        else:
            content_blocks.append({'type': 'text', 'text': '(No response)'})

    return {
        'id': run_ctx.conversation_id or '',
        'mistral_conversation_id': run_ctx.conversation_id,
        'model': model,
        'content': content_blocks,
        'stop_reason': 'end_turn',
        'usage': total_usage,
        'provider': 'mistral',
    }


def _extract_latest_user_input(messages):
    """Extract the last user message text from Anthropic-format messages."""
    for msg in reversed(messages):
        if msg.get('role') == 'user':
            content = msg.get('content', '')
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for c in content:
                    if isinstance(c, dict) and c.get('type') == 'text':
                        parts.append(c.get('text', ''))
                    elif isinstance(c, str):
                        parts.append(c)
                return '\n'.join(parts)
    return ''


def run_mistral_mcp_sync(
    api_key: str,
    model: str,
    messages: list,
    enriched_servers: list,
    max_tokens: int,
    app,
    stream: bool = False,
    conversation_id: Optional[str] = None,
):
    """Synchronous wrapper around the async Mistral MCP conversation.

    Called from the Flask chat route. Returns the same format as
    ``_run_mistral_conversation``.

    Pass ``conversation_id`` to resume an existing Mistral Conversations API
    session, preserving server-side history across HTTP requests.
    """
    coro = _run_mistral_conversation(
        api_key, model, messages, enriched_servers,
        max_tokens, app, stream,
        conversation_id=conversation_id,
    )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an already-running loop (e.g. if Flask uses async)
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        pass

    return asyncio.run(coro)


def stream_mistral_mcp_live(
    api_key, model, messages, enriched_servers, max_tokens,
    app, session_id, metrics, messages_orig,
    input_price, output_price, conversation_id=None,
):
    """Stream live progress events from the Mistral MCP loop to the browser.

    Runs ``_run_mistral_conversation`` in a daemon thread and relays its
    progress events (thinking, tool calls, tool results, final text) to the
    client via SSE as they happen, rather than waiting for the full result.

    The final ``stream_end`` event mirrors the structure of the non-streaming
    JSON response so the frontend render logic works unchanged.
    """
    from flask import Response, stream_with_context
    from server.routes.chat import _save_session

    event_queue: _queue.Queue = _queue.Queue()
    result_holder: dict = {}

    def run_in_thread():
        try:
            coro = _run_mistral_conversation(
                api_key, model, messages, enriched_servers, max_tokens, app,
                stream=True, conversation_id=conversation_id,
                event_queue=event_queue,
            )
            result_holder['result'] = asyncio.run(coro)
        except Exception as exc:
            result_holder['error'] = str(exc)
        finally:
            event_queue.put(None)  # sentinel — signals generator to stop reading

    threading.Thread(target=run_in_thread, daemon=True).start()

    def generate():
        yield f"data: {json.dumps({'type': 'message_start', 'message': {'model': model, 'usage': {}}})}\n\n"

        while True:
            try:
                item = event_queue.get(timeout=300)
            except _queue.Empty:
                yield f"data: {json.dumps({'type': 'error', 'error': 'Timeout waiting for Mistral response'})}\n\n"
                return

            if item is None:  # sentinel
                break
            yield f"data: {json.dumps(item)}\n\n"

        if 'error' in result_holder:
            yield f"data: {json.dumps({'type': 'error', 'error': result_holder['error']})}\n\n"
            return

        result = result_holder['result']
        usage = result.get('usage', {})
        metrics['total_input_tokens'] += usage.get('input_tokens', 0)
        metrics['total_output_tokens'] += usage.get('output_tokens', 0)
        metrics['total_cost'] += (
            usage.get('input_tokens', 0) * input_price
            + usage.get('output_tokens', 0) * output_price
        )
        conv_id = result.get('mistral_conversation_id')
        content = result.get('content', [])
        history = messages_orig + [{'role': 'assistant', 'content': content}]
        _save_session(
            session_id, history, metrics,
            extra={'mistral_conversation_id': conv_id} if conv_id else None,
        )
        yield f"data: {json.dumps({'type': 'stream_end', 'content': content, 'conversation_history': history, 'usage': usage, 'session_metrics': metrics, 'stop_reason': 'end_turn', 'mistral_conversation_id': conv_id})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


def synthesize_mistral_mcp_sse(result, session_id, metrics, messages,
                                input_price, output_price):
    """Wrap a Mistral MCP dict result in Anthropic-style SSE events.

    Both streaming and non-streaming paths now return a dict from
    ``_run_manual_loop`` with ``content`` (list of Anthropic-format blocks),
    ``usage``, ``model``, ``id``, etc.
    """
    import json as _json
    from flask import Response, stream_with_context

    conv_id = result.get('mistral_conversation_id')

    def _save(history):
        from server.routes.chat import _save_session
        extra = {'mistral_conversation_id': conv_id} if conv_id else None
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
        yield f"data: {_json.dumps({'type': 'stream_end', 'session_metrics': metrics, 'conversation_history': history, 'usage': usage, 'stop_reason': 'end_turn'})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')
