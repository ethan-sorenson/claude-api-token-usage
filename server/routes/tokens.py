"""
AI Token CRUD routes.
"""

import logging
from flask import Blueprint, request, jsonify, current_app

logger = logging.getLogger(__name__)
tokens_bp = Blueprint('tokens', __name__)


@tokens_bp.route('/api/tokens', methods=['GET'])
def list_tokens():
    """List all stored AI tokens (keys are masked)."""
    try:
        db = current_app.config['db']
        tokens = db.list_tokens()
        return jsonify({'tokens': tokens})
    except Exception as e:
        logger.error(f"Error listing tokens: {e}")
        return jsonify({'error': str(e)}), 500


@tokens_bp.route('/api/tokens', methods=['POST'])
def create_token():
    """Create a new AI token."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        if not data.get('key'):
            return jsonify({'error': 'API key is required'}), 400
        if not data.get('name'):
            return jsonify({'error': 'Display name is required'}), 400

        allowed_providers = ('anthropic', 'openai', 'google', 'mistral')
        provider = (data.get('provider') or '').lower()
        if provider not in allowed_providers:
            return jsonify({'error': f"Provider must be one of: {', '.join(allowed_providers)}"}), 400
        data['provider'] = provider

        db = current_app.config['db']
        token_id = db.save_token(data)
        return jsonify({'id': token_id, 'message': 'Token created successfully'})
    except Exception as e:
        logger.error(f"Error creating token: {e}")
        return jsonify({'error': str(e)}), 500


@tokens_bp.route('/api/tokens/<token_id>', methods=['PUT'])
def update_token(token_id):
    """Update an existing AI token."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        if data.get('provider'):
            allowed_providers = ('anthropic', 'openai', 'google', 'mistral')
            provider = data['provider'].lower()
            if provider not in allowed_providers:
                return jsonify({'error': f"Provider must be one of: {', '.join(allowed_providers)}"}), 400
            data['provider'] = provider

        data['id'] = token_id
        db = current_app.config['db']
        db.save_token(data)
        return jsonify({'message': 'Token updated successfully'})
    except Exception as e:
        logger.error(f"Error updating token: {e}")
        return jsonify({'error': str(e)}), 500


@tokens_bp.route('/api/tokens/<token_id>', methods=['DELETE'])
def delete_token(token_id):
    """Delete an AI token."""
    try:
        db = current_app.config['db']
        deleted = db.delete_token(token_id)
        if not deleted:
            return jsonify({'error': 'Token not found'}), 404
        return jsonify({'message': 'Token deleted successfully'})
    except Exception as e:
        logger.error(f"Error deleting token: {e}")
        return jsonify({'error': str(e)}), 500


@tokens_bp.route('/api/tokens/<token_id>/key', methods=['GET'])
def get_token_key(token_id):
    """Retrieve the actual API key for a token (used internally by chat)."""
    try:
        db = current_app.config['db']
        token = db.get_token(token_id)
        if not token:
            return jsonify({'error': 'Token not found'}), 404
        return jsonify({'key': token['key']})
    except Exception as e:
        logger.error(f"Error getting token key: {e}")
        return jsonify({'error': str(e)}), 500


@tokens_bp.route('/api/check-credit-by-token', methods=['POST'])
def check_credit_by_token():
    """Check credit using a stored token_id instead of raw API key.

    Automatically determines the provider from the stored token and
    dispatches to the appropriate provider credit-check endpoint.
    """
    try:
        from server.providers import get_provider

        data = request.get_json()
        token_id = data.get('token_id') if data else None
        if not token_id:
            return jsonify({'error': 'token_id is required'}), 400

        db = current_app.config['db']
        token = db.get_token(token_id)
        if not token:
            return jsonify({'error': 'Token not found'}), 404

        api_key = token['key']
        provider_name = (token.get('provider') or 'anthropic').lower()

        provider = get_provider(provider_name)
        if not provider:
            return jsonify({'error': f'Unsupported provider: {provider_name}'}), 400

        result = provider.check_credit(api_key)
        status = result.pop('status', 200)

        if 'valid' in result and not result['valid']:
            return jsonify(result), status if status >= 400 else 401

        return jsonify(result), status if status < 400 else 200

    except Exception as e:
        logger.error(f"Error checking credit by token: {e}")
        return jsonify({'error': str(e)}), 500
