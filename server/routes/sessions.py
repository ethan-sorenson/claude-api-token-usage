"""
Session CRUD routes.
"""

import logging
from flask import Blueprint, request, jsonify, current_app

logger = logging.getLogger(__name__)
sessions_bp = Blueprint('sessions', __name__)


@sessions_bp.route('/api/sessions', methods=['GET'])
def list_sessions():
    try:
        db = current_app.config['db']
        rows = db.list_sessions(limit=100)
        sessions = [{
            'id': r.get('session_id'),
            'timestamp': r.get('timestamp'),
            'message_count': r.get('user_message_count', 0),
            'total_tokens': r.get('total_tokens', 0),
            'token_id': r.get('token_id', ''),
            'model': r.get('model', ''),
            'note': r.get('note', ''),
            'type': 'comparison' if r.get('session_id', '').startswith('comparison_') else 'standard',
        } for r in rows]
        return jsonify({'sessions': sessions})
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/api/sessions/<session_id>', methods=['GET'])
def get_session(session_id):
    try:
        db = current_app.config['db']
        # Try comparison-specific load first for comparison sessions
        if session_id.startswith('comparison_') and not session_id.endswith('_left') and not session_id.endswith('_right'):
            data = db.get_comparison(session_id)
            if data:
                return jsonify(data)
        # Fall back to standard session load
        data = db.get_session(session_id)
        if not data:
            return jsonify({'error': 'Session not found'}), 404
        return jsonify(data)
    except Exception as e:
        logger.error(f"Error loading session {session_id}: {e}")
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/api/sessions', methods=['POST'])
def save_session():
    try:
        data = request.json
        session_id = data.get('session_id')
        if not session_id:
            return jsonify({'error': 'session_id is required'}), 400
        db = current_app.config['db']
        # Route comparison sessions to comparison-specific save
        if data.get('type') == 'comparison' or (session_id.startswith('comparison_') and data.get('left_data')):
            db.save_comparison(data)
        else:
            db.save_session(data)
        return jsonify({'success': True, 'session_id': session_id})
    except Exception as e:
        logger.error(f"Error saving session: {e}")
        return jsonify({'error': str(e)}), 500


@sessions_bp.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id):
    try:
        db = current_app.config['db']
        if session_id.startswith('comparison_') and not session_id.endswith('_left') and not session_id.endswith('_right'):
            db.delete_comparison(session_id)
        else:
            if not db.delete_session(session_id):
                return jsonify({'error': 'Session not found or failed to delete'}), 404

        return jsonify({'success': True})
    except Exception as e:
        logger.error(f"Error deleting session {session_id}: {e}")
        return jsonify({'error': str(e)}), 500
