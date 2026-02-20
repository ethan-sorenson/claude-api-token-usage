"""
Page-serving routes.
"""

from flask import Blueprint, render_template

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def index():
    return render_template('index.html')


@pages_bp.route('/compare.html')
def compare():
    return render_template('compare.html')


@pages_bp.route('/connections')
def connections():
    return render_template('connections.html')


@pages_bp.route('/tokens')
def tokens():
    return render_template('tokens.html')
