#!/usr/bin/env python3
"""
Claude API Token Usage Demo - Application Entry Point

Run with:
    python app.py
    # or
    FLASK_APP=app python -m flask run
"""

from server import create_app

app = create_app()

if __name__ == '__main__':
    port = int(__import__('os').environ.get('PORT', 5000))
    debug = __import__('os').environ.get('DEBUG', 'False').lower() == 'true'

    print("Registered Flask Routes:")
    for rule in app.url_map.iter_rules():
        print(f"   {', '.join(rule.methods)} {rule.rule}")

    print(f"""
Claude API Token Usage Demo Server Starting...

Local URL: http://localhost:{port}
Debug Mode: {debug}
CORS: Enabled
""")

    app.run(host='0.0.0.0', port=port, debug=debug)
