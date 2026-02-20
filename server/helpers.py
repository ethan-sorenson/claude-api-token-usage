"""
Shared helper functions used across route modules.
"""

import os
import re
import json
import hashlib
import base64
import secrets
import time
import logging
import requests

logger = logging.getLogger(__name__)

# ── SSE Parsing ────────────────────────────────────────────────────────

def parse_sse_response(response_text):
    """Parse SSE-formatted response, falling back to plain JSON."""
    data_match = re.search(r'^data:\s*(.+)$', response_text, re.MULTILINE)
    if data_match:
        return json.loads(data_match.group(1).strip())
    return json.loads(response_text)


# ── MCP Credential Storage ─────────────────────────────────────────────

def load_mcp_credentials(app, auto_refresh=True):
    """Load MCP credentials from database, optionally auto-refreshing OAuth tokens."""
    from server import credentials_lock

    db = app.config['db']

    with credentials_lock:
        try:
            credentials = db.load_mcp_credentials().get('servers', {})
        except Exception as e:
            logger.error(f"Failed to load MCP credentials: {e}")
            return {}

        if auto_refresh:
            updated = False
            for server_id, cfg in list(credentials.items()):
                auth_type = cfg.get('auth_type') or cfg.get('auth_method')
                if auth_type != 'oauth2':
                    continue
                expires_at = cfg.get('token_expires_at')
                if expires_at and int(time.time()) >= (expires_at - 300):
                    logger.info(f"Auto-refreshing expired OAuth token for {server_id}")
                    credentials_lock.release()
                    try:
                        refreshed = refresh_oauth_token(app, server_id, cfg)
                    finally:
                        credentials_lock.acquire()
                    if refreshed:
                        credentials[server_id] = refreshed
                        updated = True
            if updated:
                _save_credentials_locked(app, credentials)

        return credentials


def _save_credentials_locked(app, credentials):
    """Save credentials while lock is already held."""
    try:
        app.config['db'].save_mcp_credentials({'servers': credentials})
        return True
    except Exception as e:
        logger.error(f"Failed to save MCP credentials: {e}")
        return False


def save_mcp_credentials(app, credentials):
    """Thread-safe credential save + proxy sync."""
    from server import credentials_lock
    with credentials_lock:
        result = _save_credentials_locked(app, credentials)

    # Keep the MCP header proxy in sync with the latest server configs
    proxy = app.config.get('proxy_manager')
    if proxy and result:
        try:
            proxy.sync_servers(credentials)
        except Exception as e:
            logger.warning(f"Failed to sync proxy after credential save: {e}")

    return result


# ── PKCE ────────────────────────────────────────────────────────────────

def generate_pkce_pair():
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip('=')
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip('=')
    return verifier, challenge


def store_pkce_verifier(app, server_id, code_verifier):
    creds = load_mcp_credentials(app, auto_refresh=False)
    creds.setdefault(server_id, {})['pkce_code_verifier'] = code_verifier
    save_mcp_credentials(app, creds)


def get_pkce_verifier(app, server_id):
    creds = load_mcp_credentials(app, auto_refresh=False)
    if server_id in creds:
        verifier = creds[server_id].pop('pkce_code_verifier', None)
        if verifier:
            save_mcp_credentials(app, creds)
        return verifier
    return None


# ── OAuth Token Refresh ─────────────────────────────────────────────────

def refresh_oauth_token(app, server_id, server_config):
    """Refresh an expired OAuth access token. Returns updated config or None."""
    refresh_token = server_config.get('refresh_token')
    client_id = server_config.get('client_id')
    client_secret = server_config.get('client_secret')
    token_endpoint = server_config.get('token_endpoint')

    if not all([refresh_token, client_id, client_secret, token_endpoint]):
        logger.error(f"Incomplete OAuth config for refresh on {server_id}")
        return None

    try:
        resp = requests.post(token_endpoint, data={
            'grant_type': 'refresh_token',
            'refresh_token': refresh_token,
            'client_id': client_id,
            'client_secret': client_secret,
        }, headers={'Content-Type': 'application/x-www-form-urlencoded'}, timeout=10)

        if resp.status_code != 200:
            logger.error(f"Token refresh failed: {resp.status_code}")
            return None

        result = resp.json()
        access_token = result.get('access_token')
        if not access_token:
            return None

        server_config['access_token'] = access_token
        server_config['token'] = access_token
        if result.get('refresh_token'):
            server_config['refresh_token'] = result['refresh_token']
        server_config['token_expires_at'] = int(time.time()) + int(result.get('expires_in', 3600))
        server_config['token_refreshed_at'] = int(time.time())
        logger.info(f"Token refreshed for {server_id}")
        return server_config
    except Exception as e:
        logger.error(f"Error refreshing token for {server_id}: {e}")
        return None


def check_and_refresh_token(app, server_id, server_config):
    """Check if OAuth token is expired and refresh if needed."""
    auth_type = server_config.get('auth_type') or server_config.get('auth_method')
    if auth_type != 'oauth2':
        return server_config

    expires_at = server_config.get('token_expires_at')
    if not expires_at:
        return server_config

    if int(time.time()) >= (expires_at - 300):
        refreshed = refresh_oauth_token(app, server_id, server_config)
        if refreshed:
            creds = load_mcp_credentials(app, auto_refresh=False)
            creds[server_id] = refreshed
            save_mcp_credentials(app, creds)
            return refreshed
        return None

    return server_config


# ── Auth Header Builder ─────────────────────────────────────────────────

def build_oauth_auth_url(server_id, server_config, app):
    """Build an OAuth authorization URL with PKCE parameters."""
    from urllib.parse import urlencode
    from server import oauth_state_mapping

    client_id = server_config.get('client_id')
    redirect_uri = server_config.get('redirect_uri')
    auth_endpoint = server_config.get('authorization_endpoint')
    scopes = server_config.get('scopes', '')

    if not all([client_id, redirect_uri, auth_endpoint]):
        return None

    verifier, challenge = generate_pkce_pair()
    store_pkce_verifier(app, server_id, verifier)
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
    resource = server_config.get('resource')
    if resource:
        params['resource'] = resource

    return f"{auth_endpoint}?{urlencode(params)}"


def apply_auth_to_request(app, server_id, server_data, mcp_url, headers):
    """Apply authentication to MCP request headers/URL.

    Returns (url, headers, error_response_or_None).
    The error may be a Flask Response tuple OR a plain dict when called
    outside Flask request context (e.g. from async Mistral/OpenAI paths).
    """
    def _make_error(payload, status):
        """Return a jsonify response when in Flask context, else a dict."""
        try:
            from flask import jsonify
            return (jsonify(payload), status)
        except RuntimeError:
            # Outside Flask request context (async providers)
            return payload

    auth_handlers = app.config.get('auth_handlers', {})
    auth_type = server_data.get('auth_type')
    token_value = (server_data.get('token') or server_data.get('auth_token')
                   or server_data.get('access_token'))

    handler = auth_handlers.get(auth_type)

    if handler:
        method = handler.get_auth_type()
        if method in ('bearer_token', 'url_token', 'oauth2'):
            if not token_value:
                return mcp_url, headers, _make_error({
                    "status": "error", "error": f"{method} token required",
                    "require_auth": True
                }, 401)
            mcp_url, headers = handler.apply_auth(mcp_url, headers, token_value)
        return mcp_url, headers, None

    # Fallback for types without a registered handler
    if auth_type in ('bearer', 'bearer_token'):
        if token_value:
            headers['Authorization'] = f'Bearer {token_value}'
    elif auth_type == 'url_token':
        param = server_data.get('token_param_name', 'token')
        if token_value:
            sep = '&' if '?' in mcp_url else '?'
            mcp_url = f"{mcp_url}{sep}{param}={token_value}"
    elif auth_type == 'oauth2':
        refreshed = check_and_refresh_token(app, server_id, server_data)
        if not refreshed:
            auth_url = build_oauth_auth_url(server_id, server_data, app)
            if not auth_url:
                return mcp_url, headers, _make_error({
                    "status": "error", "error": "OAuth configuration incomplete",
                    "require_auth": True
                }, 400)
            return mcp_url, headers, _make_error({
                "status": "oauth_required", "authorization_url": auth_url,
                "require_auth": True
            }, 401)

        access_token = refreshed.get('access_token') or refreshed.get('token')
        if not access_token:
            auth_url = build_oauth_auth_url(server_id, server_data, app)
            if not auth_url:
                return mcp_url, headers, _make_error({
                    "status": "error", "error": "OAuth configuration incomplete",
                    "require_auth": True
                }, 400)
            return mcp_url, headers, _make_error({
                "status": "oauth_required", "authorization_url": auth_url,
                "require_auth": True
            }, 401)
        headers['Authorization'] = f'Bearer {access_token}'

    return mcp_url, headers, None
