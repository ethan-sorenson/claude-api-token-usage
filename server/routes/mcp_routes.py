"""
MCP server testing, credential management, and debug routes.
"""

import os
import json
import logging
import requests
from flask import Blueprint, request, jsonify, current_app
from urllib.parse import urlparse

from server.mcp import MCPManager
from server.helpers import (
    parse_sse_response, load_mcp_credentials, save_mcp_credentials,
    check_and_refresh_token, apply_auth_to_request,
)

logger = logging.getLogger(__name__)
mcp_bp = Blueprint('mcp', __name__)


# ── Test Endpoints ──────────────────────────────────────────────────────

@mcp_bp.route('/api/test-mcp', methods=['POST'])
def test_mcp():
    """Test MCP server connection by calling prompts/list and tools/list."""
    try:
        data = request.get_json()
        server_id = data.get('server_id')
        if not server_id:
            return jsonify({"error": "Server ID is required"}), 400

        servers_data = data.get('servers', [])
        if not servers_data:
            return jsonify({"error": "MCP servers configuration is required"}), 400

        mgr = MCPManager.from_request_data({'servers': servers_data})
        server = mgr.get_server(server_id)
        if not server:
            return jsonify({"error": f"Server {server_id} not found"}), 404

        mcp_url = server.url
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json,text/event-stream'}

        # Find server data from request
        server_data = next((s for s in servers_data if s.get('id') == server_id), {})

        # Apply authentication
        mcp_url, headers, err_resp = apply_auth_to_request(
            current_app, server_id, server_data, mcp_url, headers)
        if err_resp:
            return err_resp

        # Apply any custom headers (e.g. Business Central Company/ConfigurationName)
        custom_headers = server_data.get('headers') or server.headers
        if custom_headers:
            headers.update(custom_headers)

        # Fetch prompts
        prompts, tools = [], []
        try:
            resp = requests.post(mcp_url, headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "prompts/list", "params": {}
            }, timeout=10)

            if resp.status_code == 200 and resp.content:
                result = parse_sse_response(resp.text)
                if 'result' in result:
                    prompts = result['result'].get('prompts', [])

                # Fetch tools
                tresp = requests.post(mcp_url, headers=headers, json={
                    "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
                }, timeout=10)
                if tresp.status_code == 200 and tresp.content:
                    tres = parse_sse_response(tresp.text)
                    if 'result' in tres:
                        tools = tres['result'].get('tools', [])

                return jsonify({
                    "status": "success",
                    "message": f"Found {len(prompts)} prompts and {len(tools)} tools.",
                    "prompts_count": len(prompts), "tools_count": len(tools),
                    "prompts": prompts, "tools": tools,
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": f"MCP server returned status {resp.status_code}",
                    "mcp_url": mcp_url,
                    "response_text": (resp.text or "")[:200],
                }), resp.status_code

        except requests.exceptions.ConnectionError:
            return jsonify({"status": "error", "message": "Cannot connect to MCP server", "mcp_url": mcp_url}), 503
        except requests.exceptions.Timeout:
            return jsonify({"status": "error", "message": "MCP server connection timed out", "mcp_url": mcp_url}), 504

    except Exception as e:
        logger.error(f"MCP test error: {e}")
        return jsonify({"error": f"MCP test failed: {str(e)}"}), 500


@mcp_bp.route('/api/test-mcp-single', methods=['POST'])
def test_mcp_single():
    """Test a single MCP server connection."""
    try:
        data = request.get_json()
        server_id = data.get('server_id')
        if not server_id:
            return jsonify({"error": "Server ID is required"}), 400

        servers_data = data.get('servers', [])
        srv = next((s for s in servers_data if s.get('id') == server_id), None)
        if not srv:
            return jsonify({"error": f"Server {server_id} not found"}), 404

        # Reuse test_mcp with scoped data
        with current_app.test_request_context(
            json={'server_id': server_id, 'servers': [srv]}, method='POST'
        ):
            return test_mcp()

    except Exception as e:
        logger.error(f"Error testing MCP server: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@mcp_bp.route('/api/test-mcp-all', methods=['POST'])
def test_mcp_all():
    """Test all enabled MCP servers."""
    try:
        data = request.get_json()
        servers_data = data.get('servers', [])
        if not servers_data:
            return jsonify({"error": "MCP servers configuration is required"}), 400

        results = []
        for srv in servers_data:
            if not srv.get('enabled', True):
                continue
            sid = srv.get('id')
            try:
                with current_app.test_request_context(
                    json={'server_id': sid, 'servers': [srv]}, method='POST'
                ):
                    resp = test_mcp()
                    resp_data, status = (resp if isinstance(resp, tuple)
                                         else (resp, 200))
                    result_json = resp_data.get_json() if hasattr(resp_data, 'get_json') else resp_data
                    results.append({
                        'server_id': sid,
                        'server_name': srv.get('name', 'Unnamed'),
                        'status': 'success' if status == 200 else 'error',
                        **({'data': result_json} if status == 200 else {'error': result_json.get('error', str(result_json))}),
                    })
            except Exception as e:
                results.append({'server_id': sid, 'server_name': srv.get('name', 'Unnamed'),
                                'status': 'error', 'error': str(e)})

        return jsonify({'results': results, 'total_servers': len(servers_data), 'tested_servers': len(results)})

    except Exception as e:
        logger.error(f"Error testing all MCP servers: {e}")
        return jsonify({"error": str(e)}), 500


# ── Debug ───────────────────────────────────────────────────────────────

@mcp_bp.route('/api/debug-mcp-url', methods=['POST'])
def debug_mcp_url():
    """Debug MCP URL connectivity with multiple tests."""
    try:
        data = request.get_json()
        mcp_url = data.get('mcp_url')
        if not mcp_url:
            return jsonify({"error": "MCP URL is required"}), 400

        parsed = urlparse(mcp_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        tests = []

        # Test base domain
        try:
            r = requests.get(base_url, timeout=5)
            tests.append({"test": "Base domain", "url": base_url, "status": r.status_code, "success": True})
        except Exception as e:
            tests.append({"test": "Base domain", "url": base_url, "success": False, "message": str(e)})

        # Test JSON-RPC POST
        try:
            r = requests.post(mcp_url, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                              headers={'Content-Type': 'application/json'}, timeout=5)
            tests.append({"test": "JSON-RPC POST", "url": mcp_url, "status": r.status_code,
                          "success": r.status_code < 400, "response_preview": r.text[:300]})
        except Exception as e:
            tests.append({"test": "JSON-RPC POST", "url": mcp_url, "success": False, "message": str(e)})

        # Test OPTIONS
        try:
            r = requests.options(mcp_url, timeout=5)
            tests.append({"test": "OPTIONS", "url": mcp_url, "status": r.status_code, "success": r.status_code < 400})
        except Exception as e:
            tests.append({"test": "OPTIONS", "url": mcp_url, "success": False, "message": str(e)})

        return jsonify({"status": "debug_complete", "results": {"original_url": mcp_url, "tests": tests}})

    except Exception as e:
        return jsonify({"error": f"Debug failed: {str(e)}"}), 500


# ── Health ──────────────────────────────────────────────────────────────

@mcp_bp.route('/api/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy", "service": "Claude API Token Usage Demo", "version": "1.0.0"})


# ── Credential CRUD ────────────────────────────────────────────────────

@mcp_bp.route('/api/mcp/credentials', methods=['GET'])
def get_credentials():
    try:
        creds = load_mcp_credentials(current_app)
        return jsonify({"servers": creds}), 200
    except Exception as e:
        return jsonify({"error": str(e), "servers": {}}), 500


@mcp_bp.route('/api/mcp/credentials', methods=['POST'])
def save_credentials():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        servers = data.get('servers', {})
        if save_mcp_credentials(current_app, servers):
            return jsonify({"status": "success", "message": f"Saved {len(servers)} server(s)"}), 200
        return jsonify({"error": "Failed to save credentials"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@mcp_bp.route('/api/mcp/refresh-token/<server_id>', methods=['POST'])
def refresh_token(server_id):
    try:
        from server.helpers import refresh_oauth_token
        creds = load_mcp_credentials(current_app, auto_refresh=False)
        if server_id not in creds:
            return jsonify({"error": "Server not found"}), 404
        cfg = creds[server_id]
        if (cfg.get('auth_type') or cfg.get('auth_method')) != 'oauth2':
            return jsonify({"error": "Not an OAuth2 server"}), 400
        refreshed = refresh_oauth_token(current_app, server_id, cfg)
        if refreshed:
            creds[server_id] = refreshed
            save_mcp_credentials(current_app, creds)
            return jsonify({"status": "success", "expires_at": refreshed.get('token_expires_at')}), 200
        return jsonify({"status": "error", "error": "Token refresh failed"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@mcp_bp.route('/api/mcp/auth-types', methods=['GET'])
def get_auth_types():
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.json')
        if not os.path.exists(config_path):
            return jsonify({"auth_types": []}), 200
        with open(config_path, 'r') as f:
            cfg = json.load(f)
        return jsonify({"auth_types": cfg.get('mcp_auth_types', cfg.get('mcp_servers_type', []))}), 200
    except Exception as e:
        return jsonify({"error": str(e), "auth_types": []}), 500


@mcp_bp.route('/api/mcp/get-prompt', methods=['POST'])
def get_prompt():
    """Get prompt content from an MCP server."""
    try:
        data = request.get_json()
        server_id = data.get('server_id')
        prompt_name = data.get('prompt_name')
        arguments = data.get('arguments', {})

        if not server_id or not prompt_name:
            return jsonify({"error": "server_id and prompt_name are required"}), 400

        creds = load_mcp_credentials(current_app)
        if server_id not in creds:
            return jsonify({"error": f"Server {server_id} not found"}), 404

        cfg = creds[server_id]
        mcp_url = cfg.get('url')
        if not mcp_url:
            return jsonify({"error": "Server URL not configured"}), 400

        headers = {'Content-Type': 'application/json'}
        mcp_url, headers, err = apply_auth_to_request(current_app, server_id, cfg, mcp_url, headers)
        if err:
            return err

        resp = requests.post(mcp_url, headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "prompts/get",
            "params": {"name": prompt_name, "arguments": arguments},
        }, timeout=10)

        if resp.status_code != 200:
            return jsonify({"error": f"MCP server returned status {resp.status_code}"}), 500

        result = parse_sse_response(resp.text)
        if 'error' in result:
            return jsonify({"error": result['error'].get('message', 'Unknown error')}), 400
        if 'result' not in result:
            return jsonify({"error": "Invalid response from MCP server"}), 500

        return jsonify(result['result']), 200

    except requests.exceptions.Timeout:
        return jsonify({"error": "Request to MCP server timed out"}), 504
    except Exception as e:
        logger.error(f"Error fetching prompt: {e}")
        return jsonify({"error": str(e)}), 500


@mcp_bp.route('/api/mcp/available', methods=['GET'])
def get_available():
    try:
        config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'config.json')
        if not os.path.exists(config_path):
            return jsonify({"mcp_servers": [], "auth_handlers": []}), 200
        with open(config_path, 'r') as f:
            cfg = json.load(f)
        servers = cfg.get('mcp_servers', [])
        handlers = current_app.config.get('auth_handlers', {})
        for s in servers:
            at = s.get('auth_type')
            if at and at in handlers:
                h = handlers[at]
                s['auth_method'] = h.get_auth_type()
                s['auth_configured'] = h.is_configured()
            else:
                s['auth_method'] = 'none'
                s['auth_configured'] = True
        auth_info = [{'name': n, 'type': h.get_auth_type(), 'configured': h.is_configured()}
                     for n, h in handlers.items()]
        return jsonify({"mcp_servers": servers, "auth_handlers": auth_info}), 200
    except Exception as e:
        return jsonify({"error": str(e), "mcp_servers": [], "auth_handlers": []}), 500
