"""
Claude API Token Usage Demo - Flask Application Factory
"""

import os
import logging
import threading
from flask import Flask
from flask_cors import CORS

from server.db import get_db_manager
from server.auth import create_auth_from_config
from proxy.bc_mcp_proxy import ProxyManager

# Global state shared across modules
credentials_lock = threading.Lock()
oauth_state_mapping = {}

# Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

os.makedirs(LOGS_DIR, exist_ok=True)

# Anthropic API configuration (kept for backward-compatibility)
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
INPUT_PRICE = 3.00 / 1_000_000
OUTPUT_PRICE = 15.00 / 1_000_000

# Multi-provider default pricing (per million tokens).
# Per-model overrides are stored in the AllowedModels table and take
# precedence when available.  See server.providers.get_pricing().
PROVIDER_PRICING = {
    'anthropic': {'input': 3.00, 'output': 15.00},
    'openai':    {'input': 2.50, 'output': 10.00},
    'google':    {'input': 0.10, 'output': 0.40},
    'mistral':   {'input': 2.00, 'output': 6.00},
}


def create_app():
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        static_folder=os.path.join(BASE_DIR, 'static'),
        template_folder=os.path.join(BASE_DIR, 'templates'),
    )
    CORS(app)

    # Disable browser caching for static files in development
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

    # ---------- Logging ----------
    log_file = os.path.join(LOGS_DIR, 'app.log')
    file_handler = logging.FileHandler(log_file, mode='a')
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    )
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[file_handler],
    )
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False
    app.logger.info(f"Logging to: {log_file}")

    # ---------- Database ----------
    try:
        db = get_db_manager()
        app.config['db'] = db
        app.logger.info("Database manager initialized successfully")
    except Exception as e:
        app.logger.error(f"Failed to initialize database manager: {e}")
        raise

    # ---------- Auth handlers ----------
    auth_handlers = create_auth_from_config()
    app.config['auth_handlers'] = auth_handlers
    app.logger.info(f"Loaded {len(auth_handlers)} auth handlers: {list(auth_handlers.keys())}")

    # ---------- MCP Header Proxy ----------
    # Read optional proxy config from config.json
    try:
        import json as _json
        with open(os.path.join(BASE_DIR, 'config.json'), 'r') as _f:
            _cfg = _json.load(_f)
        proxy_cfg = _cfg.get('proxy', {})
    except Exception:
        proxy_cfg = {}

    proxy_port = proxy_cfg.get('port', ProxyManager.DEFAULT_PORT)
    proxy_public_url = proxy_cfg.get('public_url')  # e.g. 'https://abc.ngrok.io'

    proxy = ProxyManager(port=proxy_port, public_url=proxy_public_url,
                         auto_detect_tunnel=True)
    proxy.start()
    app.config['proxy_manager'] = proxy

    # Log effective public URL (may be auto-detected from ngrok)
    effective_url = proxy.public_url
    if effective_url:
        app.logger.info(f"MCP proxy public URL: {effective_url}"
                        + (" (auto-detected)" if not proxy_public_url else ""))
    else:
        app.logger.info(
            "No proxy public_url configured and no ngrok tunnel detected. "
            "MCP servers with custom headers will send the real URL to Anthropic "
            "without headers. Start ngrok (ngrok http %d) to enable proxying.",
            proxy_port
        )

    # Inject into MCP module so to_anthropic_format() can route through proxy
    from server.mcp import set_proxy_manager
    set_proxy_manager(proxy)

    # Initial sync: register any servers that already have headers
    try:
        creds = db.load_mcp_credentials().get('servers', {})
        proxy.sync_servers(creds)
    except Exception as e:
        app.logger.warning(f"Could not sync proxy on startup: {e}")

    # ---------- Register blueprints ----------
    from server.routes import register_routes
    register_routes(app)

    # ---------- Error handlers ----------
    from flask import jsonify

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Endpoint not found"}), 404

    @app.errorhandler(500)
    def internal_error(_error):
        return jsonify({"error": "Internal server error"}), 500

    return app
