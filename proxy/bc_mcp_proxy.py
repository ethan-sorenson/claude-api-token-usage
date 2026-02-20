"""
Generic MCP Header Proxy

A lightweight HTTP proxy that injects custom headers into MCP requests before
forwarding them to the real MCP server.  This is necessary because Claude's
built-in MCP client does not support custom headers, but some MCP servers
(e.g. Business Central) require them.

The proxy is started on a background thread by the Flask app and managed
through ``ProxyManager``.  Each proxied MCP server gets its own route:

    POST /proxy/<server_id>/mcp   →  forwards to real MCP URL with headers

The proxy is only active for MCP servers that have ≥1 custom header configured.

Supports MCP Streamable HTTP transport including SSE (Server-Sent Events)
streaming responses for tool listings and tool call results.
"""

import json
import logging
import socket
import threading
import time
from typing import Dict, Optional

import requests
from flask import Flask, request, Response, stream_with_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Proxy registry – shared between the proxy Flask app and ProxyManager
# ---------------------------------------------------------------------------

_registry: Dict[str, dict] = {}
_registry_lock = threading.Lock()

# Track active MCP session IDs per server so we can close them proactively
_sessions: Dict[str, str] = {}  # server_id → Mcp-Session-Id
_sessions_lock = threading.Lock()


def register_server(server_id: str, target_url: str, headers: Dict[str, str],
                    auth_token: Optional[str] = None, auth_type: Optional[str] = None):
    """Register (or update) an MCP server for proxying."""
    with _registry_lock:
        _registry[server_id] = {
            'target_url': target_url,
            'headers': dict(headers),
            'auth_token': auth_token,
            'auth_type': auth_type,
        }
    logger.info(f"Proxy registered: {server_id} → {target_url} ({len(headers)} custom header(s))")


def unregister_server(server_id: str):
    with _registry_lock:
        removed = _registry.pop(server_id, None)
    if removed:
        logger.info(f"Proxy unregistered: {server_id}")


def get_registered_servers() -> Dict[str, dict]:
    with _registry_lock:
        return dict(_registry)


def clear_registry():
    with _registry_lock:
        _registry.clear()


# ---------------------------------------------------------------------------
# Proxy Flask application
# ---------------------------------------------------------------------------

_proxy_app = Flask(__name__)
_proxy_app.logger.setLevel(logging.WARNING)  # quiet werkzeug noise


@_proxy_app.route('/proxy/<server_id>/mcp', methods=['POST', 'GET', 'DELETE'])
def proxy_mcp(server_id: str):
    """Forward an MCP request to the real server, injecting stored headers.

    Supports MCP Streamable HTTP transport:
    - POST with JSON-RPC body (tools/list, tools/call, etc.)
    - GET for SSE notification streams
    - DELETE for session cleanup

    SSE responses (text/event-stream) are streamed through in real-time
    rather than buffered, preventing truncation of large tool schemas.
    """
    with _registry_lock:
        entry = _registry.get(server_id)

    if not entry:
        return Response(
            json.dumps({'error': f'No proxy registration for server {server_id}'}),
            status=404, mimetype='application/json',
        )

    target_url = entry['target_url']
    custom_headers = entry['headers']
    auth_token = entry.get('auth_token')
    auth_type = entry.get('auth_type')

    # Start with required MCP headers
    fwd_headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json,text/event-stream',
    }

    # Forward MCP protocol headers from the incoming request (Claude sends these)
    _MCP_FORWARD_HEADERS = (
        'Mcp-Protocol-Version',
        'Mcp-Session-Id',
        'Last-Event-ID',
    )
    for hdr in _MCP_FORWARD_HEADERS:
        val = request.headers.get(hdr)
        if val:
            fwd_headers[hdr] = val

    # Inject custom headers from config
    fwd_headers.update(custom_headers)

    # Carry over Authorization from the incoming request (Claude sends this)
    incoming_auth = request.headers.get('Authorization')
    if incoming_auth:
        fwd_headers['Authorization'] = incoming_auth
    elif auth_token:
        # Fall back to stored token if Claude didn't send one
        if auth_type in ('bearer_token', 'bearer', 'api_key', 'oauth2'):
            fwd_headers['Authorization'] = f'Bearer {auth_token}'
        elif auth_type == 'url_token':
            sep = '&' if '?' in target_url else '?'
            target_url = f"{target_url}{sep}token={auth_token}"

    # Log the JSON-RPC method being called (for debugging tool discovery)
    req_body = request.get_json(silent=True) if request.method == 'POST' else None
    rpc_method = req_body.get('method', '?') if req_body else request.method
    logger.info(f"Proxy [{server_id}] {request.method} → {target_url} "
                f"(rpc_method={rpc_method}, headers: {list(fwd_headers.keys())})")

    # Response headers to forward back to the MCP client
    _MCP_RESPONSE_HEADERS = (
        'Mcp-Session-Id',
        'Mcp-Protocol-Version',
    )

    try:
        if request.method == 'DELETE':
            resp = requests.delete(target_url, headers=fwd_headers, timeout=30)
            response_headers = {}
            for hdr in _MCP_RESPONSE_HEADERS:
                val = resp.headers.get(hdr)
                if val:
                    response_headers[hdr] = val
            # Clear tracked session on DELETE
            with _sessions_lock:
                _sessions.pop(server_id, None)
            logger.info(f"Proxy [{server_id}] DELETE response: {resp.status_code}")
            return Response(
                resp.content,
                status=resp.status_code,
                headers=response_headers,
                mimetype=resp.headers.get('Content-Type', 'application/json'),
            )

        # POST and GET: use stream=True so we can handle SSE properly
        # GET SSE notification streams use a short read timeout since
        # BC typically sends nothing on this channel; keeping it open just
        # causes the MCP session to go stale and expire.
        if request.method == 'POST':
            resp = requests.post(target_url, headers=fwd_headers,
                                 json=req_body,
                                 stream=True, timeout=300)
        else:
            # (connect_timeout, read_timeout) – close quickly if no data arrives
            resp = requests.get(target_url, headers=fwd_headers,
                                stream=True, timeout=(10, 15))

        # Auto-recovery from stale/expired MCP sessions:
        # If BC returns 404 (session not found) or 408 (session timed out)
        # and we sent an Mcp-Session-Id header, retry WITHOUT the session
        # header so BC creates a fresh session.
        if resp.status_code in (404, 408) and request.method == 'POST' and fwd_headers.get('Mcp-Session-Id'):
            stale_session = fwd_headers.pop('Mcp-Session-Id')
            with _sessions_lock:
                _sessions.pop(server_id, None)
            logger.warning(f"Proxy [{server_id}] stale session detected "
                           f"(status={resp.status_code}, session={stale_session[:16]}...). "
                           f"Retrying {rpc_method} without session header...")
            resp.close()
            resp = requests.post(target_url, headers=fwd_headers,
                                 json=req_body,
                                 stream=True, timeout=300)
            logger.info(f"Proxy [{server_id}] retry result: {resp.status_code}")

        content_type = resp.headers.get('Content-Type', 'application/json')

        # Build response headers
        response_headers = {}
        for hdr in _MCP_RESPONSE_HEADERS:
            val = resp.headers.get(hdr)
            if val:
                response_headers[hdr] = val

        # Track session ID so we can close it proactively later
        session_id = resp.headers.get('Mcp-Session-Id')
        if session_id:
            with _sessions_lock:
                _sessions[server_id] = session_id
            logger.info(f"Proxy [{server_id}] tracking session: {session_id[:16]}...")

        # SSE streaming response – forward chunks in real-time
        if 'text/event-stream' in content_type:
            def generate():
                total_bytes = 0
                try:
                    for chunk in resp.iter_content(chunk_size=None):
                        if chunk:
                            total_bytes += len(chunk)
                            yield chunk
                finally:
                    resp.close()
                    logger.info(f"Proxy [{server_id}] SSE stream ended "
                                f"(rpc_method={rpc_method}, total={total_bytes} bytes)")

            logger.info(f"Proxy [{server_id}] streaming SSE response "
                        f"(rpc_method={rpc_method})")
            return Response(
                stream_with_context(generate()),
                status=resp.status_code,
                headers=response_headers,
                mimetype='text/event-stream',
            )

        # Regular JSON response – read fully, log size, and forward
        content = resp.content
        resp.close()

        logger.info(f"Proxy [{server_id}] response: {resp.status_code}, "
                     f"content-type={content_type}, size={len(content)} bytes, "
                     f"rpc_method={rpc_method}")

        # For tools/list responses, log tool count so we can verify completeness
        if rpc_method == 'tools/list' and resp.status_code == 200:
            try:
                rpc_resp = json.loads(content)
                tools = rpc_resp.get('result', {}).get('tools', [])
                tool_names = [t.get('name', '?') for t in tools]
                logger.info(f"Proxy [{server_id}] tools/list returned {len(tools)} tools: "
                            f"{tool_names}")
                # Log each tool's input_schema size for debugging truncation
                for t in tools:
                    schema = t.get('inputSchema') or t.get('input_schema', {})
                    schema_str = json.dumps(schema)
                    props = schema.get('properties', {})
                    logger.debug(f"  Tool '{t.get('name')}': "
                                 f"{len(props)} properties, "
                                 f"schema size={len(schema_str)} bytes")
            except Exception as e:
                logger.warning(f"Proxy [{server_id}] could not parse tools/list response: {e}")

        return Response(
            content,
            status=resp.status_code,
            headers=response_headers,
            mimetype=content_type,
        )

    except requests.exceptions.ReadTimeout:
        # GET SSE streams will timeout quickly by design – this is normal
        if request.method == 'GET':
            logger.info(f"Proxy [{server_id}] GET SSE stream closed (read timeout, normal)")
            return Response('', status=200, mimetype='text/event-stream')
        logger.error(f"Proxy [{server_id}] read timeout (rpc_method={rpc_method})")
        return Response(
            json.dumps({'error': f'Proxy read timeout for {rpc_method}'}),
            status=504, mimetype='application/json',
        )

    except requests.exceptions.RequestException as e:
        logger.error(f"Proxy [{server_id}] error: {e}")
        return Response(
            json.dumps({'error': f'Proxy error: {str(e)}'}),
            status=502, mimetype='application/json',
        )


@_proxy_app.route('/proxy/<server_id>/close', methods=['POST'])
def close_mcp_session(server_id: str):
    """Proactively close the MCP session for a server by sending DELETE to BC.

    This should be called after each Anthropic API call completes so that
    BC doesn't have a stale session.  The next API call will create a fresh one.
    """
    with _sessions_lock:
        session_id = _sessions.pop(server_id, None)

    if not session_id:
        logger.info(f"Proxy [{server_id}] close: no active session to close")
        return Response(
            json.dumps({'status': 'no_session'}),
            status=200, mimetype='application/json',
        )

    with _registry_lock:
        entry = _registry.get(server_id)

    if not entry:
        logger.warning(f"Proxy [{server_id}] close: server not registered")
        return Response(
            json.dumps({'status': 'not_registered'}),
            status=200, mimetype='application/json',
        )

    target_url = entry['target_url']
    custom_headers = entry['headers']
    auth_token = entry.get('auth_token')
    auth_type = entry.get('auth_type')

    fwd_headers = {
        'Content-Type': 'application/json',
        'Mcp-Session-Id': session_id,
    }
    fwd_headers.update(custom_headers)
    if auth_token and auth_type in ('bearer_token', 'bearer', 'api_key', 'oauth2'):
        fwd_headers['Authorization'] = f'Bearer {auth_token}'

    try:
        resp = requests.delete(target_url, headers=fwd_headers, timeout=10)
        logger.info(f"Proxy [{server_id}] session closed: "
                    f"DELETE → {resp.status_code} (session={session_id[:16]}...)")
        return Response(
            json.dumps({'status': 'closed', 'bc_status': resp.status_code}),
            status=200, mimetype='application/json',
        )
    except Exception as e:
        logger.warning(f"Proxy [{server_id}] session close error (non-fatal): {e}")
        return Response(
            json.dumps({'status': 'close_error', 'error': str(e)}),
            status=200, mimetype='application/json',
        )


@_proxy_app.route('/proxy/health', methods=['GET'])
def proxy_health():
    with _registry_lock:
        registered = list(_registry.keys())
    with _sessions_lock:
        active_sessions = {k: v[:16] + '...' for k, v in _sessions.items()}
    return Response(
        json.dumps({
            'status': 'healthy',
            'registered_servers': registered,
            'active_sessions': active_sessions,
        }),
        status=200, mimetype='application/json',
    )


# ---------------------------------------------------------------------------
# ProxyManager – lifecycle management
# ---------------------------------------------------------------------------

class ProxyManager:
    """Manages the MCP header-injection proxy running on a background thread.

    If ``public_url`` is set (e.g. an ngrok/cloudflare tunnel HTTPS endpoint),
    the proxy URL returned by :meth:`proxy_url_for` will use that so that
    Anthropic's servers can reach the proxy.  Otherwise the proxy only runs
    locally and cannot be used as an MCP connector URL (Anthropic requires
    public HTTPS endpoints).

    When ``auto_detect_tunnel`` is True (the default) and no ``public_url``
    is provided, the manager will attempt to discover a running ngrok tunnel
    on the standard ngrok API port (4040) that forwards to the proxy port.
    """

    DEFAULT_PORT = 5001
    NGROK_API = 'http://127.0.0.1:4040/api/tunnels'

    def __init__(self, host: str = '127.0.0.1', port: int = DEFAULT_PORT,
                 public_url: Optional[str] = None,
                 auto_detect_tunnel: bool = True):
        self.host = host
        self.port = port
        self._static_public_url = public_url  # explicitly configured URL
        self._cached_tunnel_url: Optional[str] = None
        self._auto_detect = auto_detect_tunnel
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # -- ngrok auto-detection ------------------------------------------

    def _detect_ngrok_url(self) -> Optional[str]:
        """Query the local ngrok API for a tunnel pointing at our port."""
        try:
            resp = requests.get(self.NGROK_API, timeout=2)
            if resp.status_code != 200:
                return None
            tunnels = resp.json().get('tunnels', [])
            for t in tunnels:
                # Match tunnels whose local address includes our port
                addr = t.get('config', {}).get('addr', '')
                public = t.get('public_url', '')
                if str(self.port) in addr and public.startswith('https://'):
                    return public
            # Fallback: return the first HTTPS tunnel
            for t in tunnels:
                if t.get('public_url', '').startswith('https://'):
                    return t['public_url']
        except Exception:
            pass
        return None

    @property
    def public_url(self) -> Optional[str]:
        """Return the public URL for this proxy, auto-detecting if needed."""
        if self._static_public_url:
            return self._static_public_url
        if self._auto_detect:
            # Re-detect each time so we pick up new tunnels / URL changes
            detected = self._detect_ngrok_url()
            if detected and detected != self._cached_tunnel_url:
                logger.info(f"Auto-detected ngrok tunnel: {detected}")
                self._cached_tunnel_url = detected
            return self._cached_tunnel_url
        return None

    @property
    def base_url(self) -> str:
        return f'http://{self.host}:{self.port}'

    @property
    def is_publicly_accessible(self) -> bool:
        """True when a public HTTPS tunnel URL is available (configured or detected)."""
        url = self.public_url
        return bool(url and url.startswith('https://'))

    def proxy_url_for(self, server_id: str) -> str:
        """Return the proxy URL a Claude MCP client should connect to.

        Uses the public tunnel URL if configured, otherwise falls back to
        the local address (which will NOT work with Anthropic's MCP connector).
        """
        base = self.public_url.rstrip('/') if self.public_url else self.base_url
        return f'{base}/proxy/{server_id}/mcp'

    def start(self):
        """Start the proxy in a daemon thread (idempotent)."""
        if self._running:
            return

        # Check if port is already in use
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((self.host, self.port))
            sock.close()
        except OSError:
            logger.warning(f"MCP proxy port {self.port} already in use – assuming proxy is running")
            self._running = True
            return

        def _run():
            import werkzeug.serving
            srv = werkzeug.serving.make_server(self.host, self.port, _proxy_app,
                                                threaded=True)
            self._running = True
            logger.info(f"MCP header proxy listening on {self.base_url}")
            srv.serve_forever()

        self._thread = threading.Thread(target=_run, name='mcp-proxy', daemon=True)
        self._thread.start()

        # Wait briefly for the server to bind
        for _ in range(20):
            if self._running:
                break
            time.sleep(0.1)

    def stop(self):
        self._running = False
        clear_registry()
        logger.info("MCP header proxy stopped")

    def sync_servers(self, servers: Dict[str, dict]):
        """Sync the proxy registry with the current set of MCP servers.

        Only servers with ≥1 custom header will be registered.
        Servers without headers will be unregistered.
        """
        current = get_registered_servers()
        new_ids = set()

        for server_id, cfg in servers.items():
            headers = cfg.get('headers') or {}
            if not headers:
                continue
            new_ids.add(server_id)
            register_server(
                server_id,
                target_url=cfg.get('url', ''),
                headers=headers,
                auth_token=cfg.get('auth_token') or cfg.get('token') or cfg.get('access_token'),
                auth_type=cfg.get('auth_type') or cfg.get('auth_method'),
            )

        # Remove servers that no longer need proxying
        for old_id in set(current.keys()) - new_ids:
            unregister_server(old_id)

        if new_ids:
            logger.info(f"Proxy sync: {len(new_ids)} server(s) with headers registered")

    def needs_proxy(self, server_cfg: dict) -> bool:
        """Return True if a server config has ≥1 custom header."""
        return bool(server_cfg.get('headers'))


# Standalone entry-point (for manual testing)
if __name__ == '__main__':
    import os
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    port = int(os.environ.get('PROXY_PORT', 5001))
    logger.info(f"Starting MCP header proxy on port {port}")
    _proxy_app.run(host='127.0.0.1', port=port, debug=False)
