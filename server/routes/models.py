"""
AI Model management routes - fetch available models from providers, manage allowed models, usage stats.
"""

import logging
import requests as http_requests
from flask import Blueprint, request, jsonify, current_app

logger = logging.getLogger(__name__)
models_bp = Blueprint('models', __name__)


# ── Provider model fetching ────────────────────────────────────────────

PROVIDER_MODEL_ENDPOINTS = {
    'anthropic': {
        'url': 'https://api.anthropic.com/v1/models',
        'method': 'GET',
    },
    'openai': {
        'url': 'https://api.openai.com/v1/models',
        'method': 'GET',
    },
    'google': {
        'url': 'https://generativelanguage.googleapis.com/v1beta/models',
        'method': 'GET',
    },
    'mistral': {
        'url': 'https://api.mistral.ai/v1/models',
        'method': 'GET',
    },
}


# Known pricing per million tokens (input, output) for popular models.
# Used as fallback when the provider API doesn't return pricing.
KNOWN_PRICING = {
    # Anthropic
    'claude-sonnet-4-20250514':       (3.00, 15.00),
    'claude-sonnet-4-5-20250929':     (3.00, 15.00),
    'claude-opus-4-20250514':         (15.00, 75.00),
    'claude-3-7-sonnet-20250219':     (3.00, 15.00),
    'claude-3-5-sonnet-20241022':     (3.00, 15.00),
    'claude-3-5-sonnet-20240620':     (3.00, 15.00),
    'claude-3-5-haiku-20241022':      (0.80, 4.00),
    'claude-3-opus-20240229':         (15.00, 75.00),
    'claude-3-haiku-20240307':        (0.25, 1.25),
    # OpenAI
    'gpt-4.1':                        (2.00, 8.00),
    'gpt-4.1-mini':                   (0.40, 1.60),
    'gpt-4.1-nano':                   (0.10, 0.40),
    'gpt-4o':                         (2.50, 10.00),
    'gpt-4o-2024-11-20':              (2.50, 10.00),
    'gpt-4o-2024-08-06':              (2.50, 10.00),
    'gpt-4o-mini':                    (0.15, 0.60),
    'gpt-4o-mini-2024-07-18':         (0.15, 0.60),
    'o3':                             (2.00, 8.00),
    'o3-mini':                        (1.10, 4.40),
    'o4-mini':                        (1.10, 4.40),
    'o1':                             (15.00, 60.00),
    'o1-mini':                        (1.10, 4.40),
    # Mistral
    'mistral-large-latest':           (2.00, 6.00),
    'mistral-small-latest':           (0.10, 0.30),
    'codestral-latest':               (0.30, 0.90),
    'mistral-embed':                  (0.10, 0.00),
    'open-mistral-nemo':              (0.15, 0.15),
    # Google
    'gemini-2.5-pro':                 (1.25, 10.00),
    'gemini-2.5-flash':               (0.15, 0.60),
    'gemini-2.0-flash':               (0.10, 0.40),
    'gemini-1.5-pro':                 (1.25, 5.00),
    'gemini-1.5-flash':               (0.075, 0.30),
}


def _lookup_known_pricing(model_id: str):
    """Return (input_price, output_price) per 1M tokens if known, else (None, None)."""
    if model_id in KNOWN_PRICING:
        return KNOWN_PRICING[model_id]
    # Try prefix match for versioned model IDs
    for known_id, prices in KNOWN_PRICING.items():
        if model_id.startswith(known_id):
            return prices
    return (None, None)


# Known context windows for models whose APIs don't return them.
KNOWN_CONTEXT_WINDOWS = {
    # Anthropic
    'claude-sonnet-4-20250514':       200000,
    'claude-sonnet-4-5-20250929':     200000,
    'claude-opus-4-20250514':         200000,
    'claude-3-7-sonnet-20250219':     200000,
    'claude-3-5-sonnet-20241022':     200000,
    'claude-3-5-sonnet-20240620':     200000,
    'claude-3-5-haiku-20241022':      200000,
    'claude-3-opus-20240229':         200000,
    'claude-3-haiku-20240307':        200000,
    # OpenAI
    'gpt-4.1':                        1047576,
    'gpt-4.1-mini':                   1047576,
    'gpt-4.1-nano':                   1047576,
    'gpt-4o':                         128000,
    'gpt-4o-mini':                    128000,
    'o3':                             200000,
    'o3-mini':                        200000,
    'o4-mini':                        200000,
    'o1':                             200000,
    'o1-mini':                        128000,
    'chatgpt-4o-latest':              128000,
}


def _lookup_known_context(model_id: str):
    """Return context window size if known, else None."""
    if model_id in KNOWN_CONTEXT_WINDOWS:
        return KNOWN_CONTEXT_WINDOWS[model_id]
    for known_id, ctx in KNOWN_CONTEXT_WINDOWS.items():
        if model_id.startswith(known_id):
            return ctx
    return None


def _fetch_anthropic_models(api_key: str) -> list:
    """Fetch models from Anthropic API."""
    from server import ANTHROPIC_VERSION
    headers = {
        'x-api-key': api_key,
        'anthropic-version': ANTHROPIC_VERSION,
        'content-type': 'application/json',
    }
    models = []
    has_more = True
    after_id = None
    while has_more:
        url = 'https://api.anthropic.com/v1/models?limit=100'
        if after_id:
            url += f'&after_id={after_id}'
        resp = http_requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        for m in data.get('data', []):
            mid = m.get('id', '')
            ip, op = _lookup_known_pricing(mid)
            models.append({
                'model_id': mid,
                'display_name': m.get('display_name', mid),
                'provider': 'anthropic',
                'context_window': _lookup_known_context(mid),
                'input_price': ip,
                'output_price': op,
            })
        has_more = data.get('has_more', False)
        if has_more and data.get('data'):
            after_id = data['data'][-1].get('id')
        else:
            has_more = False
    return models


def _fetch_openai_models(api_key: str) -> list:
    """Fetch models from OpenAI API."""
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    resp = http_requests.get('https://api.openai.com/v1/models', headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    models = []
    for m in data.get('data', []):
        model_id = m.get('id', '')
        # Filter to chat-capable models (gpt, o1, o3, chatgpt)
        if any(model_id.startswith(prefix) for prefix in ('gpt-', 'o1', 'o3', 'o4', 'chatgpt')):
            ip, op = _lookup_known_pricing(model_id)
            models.append({
                'model_id': model_id,
                'display_name': model_id,
                'provider': 'openai',
                'context_window': _lookup_known_context(model_id),
                'input_price': ip,
                'output_price': op,
            })
    models.sort(key=lambda x: x['model_id'])
    return models


def _fetch_google_models(api_key: str) -> list:
    """Fetch models from Google Generative Language API."""
    resp = http_requests.get(
        f'https://generativelanguage.googleapis.com/v1beta/models?key={api_key}',
        timeout=15
    )
    resp.raise_for_status()
    data = resp.json()
    models = []
    for m in data.get('models', []):
        name = m.get('name', '')
        # name is like "models/gemini-2.0-flash" - extract the model part
        model_id = name.replace('models/', '') if name.startswith('models/') else name
        display_name = m.get('displayName', model_id)
        # Filter to generative models
        if 'generateContent' in str(m.get('supportedGenerationMethods', [])):
            ip, op = _lookup_known_pricing(model_id)
            models.append({
                'model_id': model_id,
                'display_name': display_name,
                'provider': 'google',
                'context_window': m.get('inputTokenLimit'),
                'input_price': ip,
                'output_price': op,
            })
    models.sort(key=lambda x: x['display_name'])
    return models


def _fetch_mistral_models(api_key: str) -> list:
    """Fetch models from Mistral API."""
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    resp = http_requests.get('https://api.mistral.ai/v1/models', headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    models = []
    for m in data.get('data', []):
        model_id = m.get('id', '')
        ip, op = _lookup_known_pricing(model_id)
        models.append({
            'model_id': model_id,
            'display_name': model_id,
            'provider': 'mistral',
            'context_window': m.get('max_context_length'),
            'input_price': ip,
            'output_price': op,
        })
    models.sort(key=lambda x: x['model_id'])
    return models


PROVIDER_FETCHERS = {
    'anthropic': _fetch_anthropic_models,
    'openai': _fetch_openai_models,
    'google': _fetch_google_models,
    'mistral': _fetch_mistral_models,
}


# ── Routes ─────────────────────────────────────────────────────────────

@models_bp.route('/api/tokens/<token_id>/available-models', methods=['GET'])
def fetch_available_models(token_id):
    """Query the AI provider API for available models using a stored token."""
    try:
        db = current_app.config['db']
        token = db.get_token(token_id)
        if not token:
            return jsonify({'error': 'Token not found'}), 404

        provider = token.get('provider', '').lower()
        api_key = token.get('key', '')

        fetcher = PROVIDER_FETCHERS.get(provider)
        if not fetcher:
            return jsonify({'error': f'Unsupported provider: {provider}'}), 400

        models = fetcher(api_key)
        return jsonify({'models': models, 'provider': provider, 'token_id': token_id})
    except http_requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else 500
        logger.error(f"Provider API error fetching models for {token_id}: {e}")
        return jsonify({'error': f'Provider API returned status {status}'}), status
    except Exception as e:
        logger.error(f"Error fetching available models for {token_id}: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/api/models', methods=['GET'])
def list_allowed_models():
    """List all allowed models, optionally filtered by token_id or enabled_only."""
    try:
        db = current_app.config['db']
        token_id = request.args.get('token_id')
        enabled_only = request.args.get('enabled_only', '').lower() in ('true', '1', 'yes')
        models = db.list_allowed_models(token_id=token_id, enabled_only=enabled_only)
        return jsonify({'models': models})
    except Exception as e:
        logger.error(f"Error listing allowed models: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/api/models', methods=['POST'])
def save_allowed_models():
    """Save allowed models for a token. Expects { token_id, models: [...] }."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        token_id = data.get('token_id')
        models = data.get('models', [])
        if not token_id:
            return jsonify({'error': 'token_id is required'}), 400

        db = current_app.config['db']
        saved = db.save_allowed_models(token_id, models)
        return jsonify({'message': f'Saved {saved} models', 'count': saved})
    except Exception as e:
        logger.error(f"Error saving allowed models: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/api/models/<int:model_id>/toggle', methods=['PUT'])
def toggle_model(model_id):
    """Toggle the enabled state of an allowed model."""
    try:
        data = request.get_json()
        if not data or 'enabled' not in data:
            return jsonify({'error': 'enabled field is required'}), 400

        db = current_app.config['db']
        updated = db.toggle_allowed_model(model_id, data['enabled'])
        if not updated:
            return jsonify({'error': 'Model not found'}), 404
        return jsonify({'message': 'Model updated'})
    except Exception as e:
        logger.error(f"Error toggling model {model_id}: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/api/models/<int:model_id>/cost', methods=['PUT'])
def update_model_cost(model_id):
    """Update the cost per million tokens for an allowed model."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        updates = {}
        for field in ('input_price', 'output_price'):
            if field in data:
                updates[field] = data[field]

        if not updates:
            return jsonify({'error': 'No cost fields provided'}), 400

        db = current_app.config['db']
        updated = db.update_model_cost(model_id, updates)
        if not updated:
            return jsonify({'error': 'Model not found'}), 404
        return jsonify({'message': 'Cost updated'})
    except Exception as e:
        logger.error(f"Error updating model cost {model_id}: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/api/models/<int:model_id>', methods=['DELETE'])
def delete_model(model_id):
    """Delete an allowed model."""
    try:
        db = current_app.config['db']
        deleted = db.delete_allowed_model(model_id)
        if not deleted:
            return jsonify({'error': 'Model not found'}), 404
        return jsonify({'message': 'Model deleted'})
    except Exception as e:
        logger.error(f"Error deleting model {model_id}: {e}")
        return jsonify({'error': str(e)}), 500


@models_bp.route('/api/models/token/<token_id>', methods=['DELETE'])
def delete_models_for_token(token_id):
    """Delete all allowed models for a specific token."""
    try:
        db = current_app.config['db']
        count = db.delete_allowed_models_for_token(token_id)
        return jsonify({'message': f'Deleted {count} models', 'count': count})
    except Exception as e:
        logger.error(f"Error deleting models for token {token_id}: {e}")
        return jsonify({'error': str(e)}), 500


# ── Usage Statistics ───────────────────────────────────────────────────

@models_bp.route('/api/usage-stats', methods=['GET'])
def get_usage_stats():
    """Get usage statistics for charts. Query params: start_date, end_date, token_id, model."""
    try:
        db = current_app.config['db']
        stats = db.get_usage_stats(
            start_date=request.args.get('start_date'),
            end_date=request.args.get('end_date'),
            token_id=request.args.get('token_id'),
            model=request.args.get('model'),
            server_id=request.args.get('server_id'),
        )

        # ── Calculate costs ────────────────────────────────────────────
        total_cost = 0.0

        # Cost per model
        for entry in stats.get('by_model', []):
            model_id = entry.get('model', '')
            ip, op = _lookup_known_pricing(model_id)
            if ip is not None and op is not None:
                input_cost = entry['input_tokens'] * ip / 1_000_000
                output_cost = entry['output_tokens'] * op / 1_000_000
                # Cache: creation = 1.25× input price, read = 0.1× input price
                cache_create_cost = entry.get('cache_creation', 0) * ip * 1.25 / 1_000_000
                cache_read_cost = entry.get('cache_read', 0) * ip * 0.1 / 1_000_000
                model_cost = input_cost + output_cost + cache_create_cost + cache_read_cost
            else:
                model_cost = None
            entry['cost'] = round(model_cost, 4) if model_cost is not None else None
            if model_cost is not None:
                total_cost += model_cost

        stats['totals']['total_cost'] = round(total_cost, 4)
        stats['totals']['has_pricing'] = total_cost > 0

        # Daily costs (aggregate daily_by_model rows by date)
        daily_costs = {}
        for row in stats.get('daily_by_model', []):
            model_id = row.get('model', '')
            ip, op = _lookup_known_pricing(model_id)
            if ip is None or op is None:
                continue
            day_cost = (
                row['input_tokens'] * ip / 1_000_000
                + row['output_tokens'] * op / 1_000_000
                + row.get('cache_creation', 0) * ip * 1.25 / 1_000_000
                + row.get('cache_read', 0) * ip * 0.1 / 1_000_000
            )
            date_key = row['date']
            daily_costs[date_key] = daily_costs.get(date_key, 0) + day_cost

        # Merge daily costs into the existing daily array
        for entry in stats.get('daily', []):
            entry['cost'] = round(daily_costs.get(entry['date'], 0), 4)

        # Remove the raw daily_by_model from response (not needed by frontend)
        stats.pop('daily_by_model', None)

        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting usage stats: {e}")
        return jsonify({'error': str(e)}), 500
