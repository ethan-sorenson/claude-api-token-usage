"""
Route blueprint registration.
"""


def register_routes(app):
    """Register all route blueprints with the Flask app."""
    from server.routes.pages import pages_bp
    from server.routes.chat import chat_bp
    from server.routes.mcp_routes import mcp_bp
    from server.routes.oauth import oauth_bp
    from server.routes.sessions import sessions_bp
    from server.routes.tokens import tokens_bp
    from server.routes.models import models_bp

    app.register_blueprint(pages_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(mcp_bp)
    app.register_blueprint(oauth_bp)
    app.register_blueprint(sessions_bp)
    app.register_blueprint(tokens_bp)
    app.register_blueprint(models_bp)
