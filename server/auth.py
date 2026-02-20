"""
Authentication Handler Module
Provides multiple authentication methods: Bearer Token, URL Token, OAuth2
"""

import os
import json
import logging
import uuid

logger = logging.getLogger(__name__)


class AuthConfig:
    """Base authentication configuration."""

    def __init__(self, auth_type, **kwargs):
        self.auth_type = auth_type
        self.config = kwargs

    def is_configured(self):
        if self.auth_type == 'bearer_token':
            return bool(self.config.get('token_param_name'))
        if self.auth_type == 'url_token':
            return bool(self.config.get('token_param_name'))
        if self.auth_type == 'oauth2':
            return all([
                self.config.get('client_id'),
                self.config.get('client_secret'),
                self.config.get('token_endpoint'),
            ])
        return False


class AuthHandler:
    """Generic authentication handler supporting multiple auth types."""

    def __init__(self, auth_config: AuthConfig):
        self.config = auth_config
        self.oauth_state = None

    def apply_auth(self, url, headers=None, token_value=None):
        if headers is None:
            headers = {}

        if self.config.auth_type in ('bearer_token', 'oauth2'):
            if token_value:
                headers['Authorization'] = f'Bearer {token_value}'
        elif self.config.auth_type == 'url_token':
            if token_value:
                param = self.config.config.get('token_param_name', 'token')
                sep = '&' if '?' in url else '?'
                url = f"{url}{sep}{param}={token_value}"

        return url, headers

    def get_auth_type(self):
        return self.config.auth_type

    def requires_oauth_flow(self):
        return self.config.auth_type == 'oauth2'

    def is_configured(self):
        return self.config.is_configured()

    def generate_oauth_state(self):
        self.oauth_state = str(uuid.uuid4())
        return self.oauth_state

    def validate_oauth_state(self, received_state):
        if not self.oauth_state:
            logger.warning("No OAuth state was generated for validation")
            return False
        return self.oauth_state == received_state

    def clear_oauth_state(self):
        self.oauth_state = None


def create_auth_from_config(config_path='config.json'):
    """Create AuthHandler instances from config file.

    Returns dict of {auth_type: AuthHandler}.
    """
    auth_handlers = {}

    if not os.path.exists(config_path):
        logger.warning(f"Config file not found: {config_path}")
        return auth_handlers

    try:
        with open(config_path, 'r') as f:
            config_data = json.load(f)
        logger.info(f"Loaded authentication configuration from {config_path}")
    except Exception as e:
        logger.error(f"Failed to load config file {config_path}: {e}")
        return auth_handlers

    for auth_type_cfg in config_data.get('mcp_auth_types', []):
        auth_type = auth_type_cfg.get('type')
        name = auth_type_cfg.get('name')

        if not auth_type:
            continue

        if auth_type in ('bearer', 'bearer_token'):
            cfg = AuthConfig(auth_type='bearer_token', token_param_name='token')
        elif auth_type == 'url_token':
            cfg = AuthConfig(auth_type='url_token', token_param_name='token')
        elif auth_type == 'oauth2':
            cfg = AuthConfig(auth_type='oauth2', client_id='', client_secret='', token_endpoint='')
        else:
            logger.debug(f"Skipping auth type '{auth_type}' – no handler needed")
            continue

        auth_handlers[auth_type] = AuthHandler(cfg)
        logger.info(f"Created {auth_type} auth handler for {name}")

    return auth_handlers
