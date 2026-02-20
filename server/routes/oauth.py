"""
OAuth 2.0 routes (authorization URL generation and callback).
"""

import time
import json
import logging
import requests
from flask import Blueprint, request, jsonify, current_app
from urllib.parse import urlencode

from server import oauth_state_mapping
from server.helpers import (
    load_mcp_credentials, save_mcp_credentials,
    generate_pkce_pair, store_pkce_verifier, get_pkce_verifier,
    parse_sse_response,
)

logger = logging.getLogger(__name__)
oauth_bp = Blueprint('oauth', __name__)


@oauth_bp.route('/api/generate-oauth-state', methods=['POST'])
def generate_oauth_state():
    """Generate OAuth authorization URL with PKCE."""
    try:
        data = request.get_json()
        server_id = data.get('server_id')
        if not server_id:
            return jsonify({"error": "server_id is required"}), 400

        creds = load_mcp_credentials(current_app)
        if server_id not in creds:
            return jsonify({"error": f"Server {server_id} not found"}), 404

        cfg = creds[server_id]
        client_id = cfg.get('client_id')
        redirect_uri = cfg.get('redirect_uri')
        auth_endpoint = cfg.get('authorization_endpoint')
        scopes = cfg.get('scopes', '')

        if not all([client_id, redirect_uri, auth_endpoint]):
            return jsonify({"error": "OAuth configuration incomplete"}), 400

        verifier, challenge = generate_pkce_pair()
        store_pkce_verifier(current_app, server_id, verifier)
        oauth_state_mapping[server_id] = server_id

        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'state': server_id,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        }
        if scopes:
            params['scope'] = scopes
        if cfg.get('resource'):
            params['resource'] = cfg['resource']

        return jsonify({
            "state": server_id,
            "authorization_url": f"{auth_endpoint}?{urlencode(params)}",
        }), 200

    except Exception as e:
        logger.error(f"Error generating OAuth state: {e}")
        return jsonify({"error": str(e)}), 500


@oauth_bp.route('/oauth/callback', methods=['GET'])
def oauth_callback():
    """OAuth 2.0 callback – exchanges code for tokens."""
    try:
        code = request.args.get('code')
        state = request.args.get('state')
        error = request.args.get('error')
        error_desc = request.args.get('error_description')

        if error:
            return _error_page("Authorization Failed", error, error_desc), 400

        if not code or not state:
            return jsonify({"error": "Missing authorization code or state"}), 400

        server_id = oauth_state_mapping.get(state)
        if not server_id:
            return _error_page("Authorization Failed", "Invalid or expired state parameter"), 400

        creds = load_mcp_credentials(current_app)
        if server_id not in creds:
            return jsonify({"error": f"Server {server_id} not found"}), 404

        cfg = creds[server_id]
        client_id = cfg.get('client_id')
        client_secret = cfg.get('client_secret')
        redirect_uri = cfg.get('redirect_uri')
        token_endpoint = cfg.get('token_endpoint')

        if not all([client_id, client_secret, redirect_uri, token_endpoint]):
            return jsonify({"error": "Incomplete OAuth configuration"}), 400

        code_verifier = get_pkce_verifier(current_app, server_id)

        # Exchange code for tokens
        token_data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': redirect_uri,
            'client_id': client_id,
            'client_secret': client_secret,
        }
        if code_verifier:
            token_data['code_verifier'] = code_verifier

        resp = requests.post(token_endpoint, data=token_data,
                             headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=10)
        if resp.status_code != 200:
            return jsonify({"error": "Token exchange failed", "details": resp.text}), resp.status_code

        result = resp.json()
        access_token = result.get('access_token')
        if not access_token:
            return jsonify({"error": "No access token received"}), 500

        cfg['access_token'] = access_token
        cfg['token'] = access_token
        if result.get('refresh_token'):
            cfg['refresh_token'] = result['refresh_token']
        cfg['token_expires_at'] = int(time.time()) + int(result.get('expires_in', 3600))
        cfg['token_obtained_at'] = int(time.time())

        creds[server_id] = cfg
        save_mcp_credentials(current_app, creds)

        # Clean up state
        oauth_state_mapping.pop(state, None)

        # Fetch MCP capabilities
        prompts, tools = _fetch_capabilities(cfg, access_token)
        if prompts or tools:
            cfg['prompts'] = prompts
            cfg['tools'] = tools
            creds[server_id] = cfg
            save_mcp_credentials(current_app, creds)

        return _success_page(cfg.get('name', server_id), server_id, len(prompts), len(tools)), 200

    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        return jsonify({"error": str(e)}), 500


def _fetch_capabilities(cfg, access_token):
    """Fetch prompts and tools from an MCP server after OAuth."""
    mcp_url = cfg.get('url')
    if not mcp_url:
        return [], []

    headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {access_token}'}
    custom = cfg.get('headers', {})
    if custom:
        headers.update(custom)

    prompts, tools = [], []
    try:
        r = requests.post(mcp_url, headers=headers,
                          json={"jsonrpc": "2.0", "id": 1, "method": "prompts/list", "params": {}}, timeout=10)
        if r.status_code == 200 and r.content:
            res = parse_sse_response(r.text)
            prompts = res.get('result', {}).get('prompts', [])
    except Exception:
        pass
    try:
        r = requests.post(mcp_url, headers=headers,
                          json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, timeout=10)
        if r.status_code == 200 and r.content:
            res = parse_sse_response(r.text)
            tools = res.get('result', {}).get('tools', [])
    except Exception:
        pass
    return prompts, tools


def _error_page(title, error, description=None):
    desc = f"<p>Description: {description}</p>" if description else ""
    return f"""<html><head><title>OAuth Error</title></head><body>
<h2>{title}</h2><p>Error: {error}</p>{desc}
<p><a href="/">Return to app</a></p></body></html>"""


def _success_page(server_name, server_id, prompt_count, tool_count):
    caps = ""
    if prompt_count:
        caps += f"<br>📝 Prompts: {prompt_count}"
    if tool_count:
        caps += f"<br>🔧 Tools: {tool_count}"
    return f"""<html><head><title>Authorization Successful</title>
<style>
body {{ font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; padding:40px; text-align:center; background:linear-gradient(135deg,#667eea,#764ba2); color:white; }}
.box {{ background:white; color:#333; border-radius:12px; padding:30px; box-shadow:0 10px 40px rgba(0,0,0,.3); max-width:500px; margin:0 auto; }}
h2 {{ margin-top:0; color:#10b981; }}
</style>
<script>
if(window.opener){{ window.opener.postMessage({{ type:'oauth_success', server_id:'{server_id}' }}, window.location.origin); setTimeout(()=>window.close(),2000); }}
</script></head><body><div class="box">
<h2>✅ Authorization Successful!</h2>
<p><strong>{server_name}</strong> has been configured.</p>
<div style="margin:20px 0;font-size:16px;line-height:1.8">{caps}</div>
<p style="color:#666;font-size:14px">This window will close automatically...</p>
</div></body></html>"""
