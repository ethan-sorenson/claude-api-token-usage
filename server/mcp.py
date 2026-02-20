"""
MCP (Model Context Protocol) Manager Module
Handles multiple MCP server configurations and authentication.
"""

import logging

logger = logging.getLogger(__name__)

# Will be set by the Flask app at startup
_proxy_manager = None


def set_proxy_manager(pm):
    """Called once from create_app() to inject the ProxyManager instance."""
    global _proxy_manager
    _proxy_manager = pm


class MCPServer:
    """Represents a single MCP server configuration with authentication."""

    def __init__(self, name, url, auth_type=None, auth_token=None, headers=None,
                 server_id=None):
        self.name = name
        self.url = url
        self.auth_type = auth_type or 'bearer_token'
        self.auth_token = auth_token
        self.headers = headers or {}
        self.server_id = server_id

    def to_anthropic_format(self):
        """Convert to Anthropic API mcp_servers format.

        When the server has custom headers AND a publicly accessible proxy
        (with an HTTPS tunnel URL) is configured, route through the proxy
        so the headers are injected transparently.

        If the proxy is only running locally (no tunnel), fall back to
        the real URL because Anthropic requires public HTTPS endpoints and
        cannot reach localhost.
        """
        # If there are custom headers, a proxy exists, and the proxy is
        # reachable from Anthropic (public HTTPS URL), use the proxy.
        if self.headers and _proxy_manager and self.server_id and _proxy_manager.is_publicly_accessible:
            proxy_url = _proxy_manager.proxy_url_for(self.server_id)
            config = {'type': 'url', 'url': proxy_url, 'name': self.name}
            # The proxy already handles auth, but still pass the token so
            # Claude includes it as Authorization header in the proxy request
            if self.auth_type in ('bearer_token', 'bearer', 'api_key', 'oauth2') and self.auth_token:
                config['authorization_token'] = self.auth_token
            return config

        if self.headers and _proxy_manager and self.server_id and not _proxy_manager.is_publicly_accessible:
            logger.warning(
                f"Server '{self.name}' has custom headers but the MCP proxy has no "
                f"public HTTPS URL configured.  Anthropic's MCP connector requires "
                f"public HTTPS endpoints.  Sending the real URL without custom headers. "
                f"Set 'proxy_public_url' in config.json or use a tunnel (e.g. ngrok)."
            )

        # Normal path – no headers needed (or proxy not publicly reachable)
        config = {'type': 'url', 'url': self.url, 'name': self.name}

        if self.auth_type in ('bearer_token', 'bearer', 'api_key', 'oauth2') and self.auth_token:
            config['authorization_token'] = self.auth_token
        elif self.auth_type == 'url_token' and self.auth_token:
            sep = '&' if '?' in self.url else '?'
            config['url'] = f"{self.url}{sep}token={self.auth_token}"

        return config

    def to_dict(self):
        result = {'name': self.name, 'url': self.url}
        if self.headers:
            result['headers'] = self.headers
        return result


class MCPManager:
    """Manages multiple MCP server configurations."""

    def __init__(self):
        self.servers = {}

    def add_server(self, server_id, server: MCPServer):
        self.servers[server_id] = server

    def remove_server(self, server_id):
        if server_id in self.servers:
            del self.servers[server_id]
            return True
        return False

    def get_server(self, server_id):
        return self.servers.get(server_id)

    def get_all_servers(self):
        return self.servers

    def get_server_list(self):
        return {sid: s.to_dict() for sid, s in self.servers.items()}

    def prepare_for_anthropic(self, enabled_server_ids=None):
        targets = self.servers
        if enabled_server_ids:
            targets = {k: v for k, v in self.servers.items() if k in enabled_server_ids}

        result = []
        for sid, server in targets.items():
            try:
                result.append(server.to_anthropic_format())
            except Exception as e:
                logger.error(f"Failed to prepare server {sid}: {e}")
        return result

    @classmethod
    def from_request_data(cls, data):
        manager = cls()
        for srv in data.get('servers', []):
            server_id = srv.get('id')
            if not server_id:
                continue
            server = MCPServer(
                name=srv.get('name', 'Unnamed Server'),
                url=srv.get('url', ''),
                auth_type=srv.get('auth_method'),
                auth_token=srv.get('auth_token') or srv.get('token'),
                headers=srv.get('headers', {}),
                server_id=server_id,
            )
            manager.add_server(server_id, server)
        return manager
