"""Quick smoke test for the API changes."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import create_app
app = create_app()
with app.test_client() as c:
    # Test tokens list
    r = c.get('/api/tokens')
    print('GET /api/tokens:', r.status_code)

    # Test creating token with invalid provider
    r = c.post('/api/tokens', json={'name': 'Test', 'provider': 'other', 'key': 'sk-test'})
    print('POST /api/tokens (other):', r.status_code, r.json.get('error', ''))

    # Test creating token with valid provider
    r = c.post('/api/tokens', json={'name': 'Test Mistral', 'provider': 'mistral', 'key': 'sk-test-123'})
    print('POST /api/tokens (mistral):', r.status_code, r.json)
    tid = r.json.get('id') if r.status_code == 200 else None

    # Test sessions list returns token_id/model
    r = c.get('/api/sessions')
    print('GET /api/sessions:', r.status_code)
    sessions = r.json.get('sessions', [])
    if sessions:
        s = sessions[0]
        print('  First session has token_id:', 'token_id' in s, '| model:', 'model' in s)

    # Cleanup test token
    if tid:
        r = c.delete('/api/tokens/' + tid)
        print('DELETE test token:', r.status_code)

    # Test connections has notes field
    r = c.get('/api/mcp/credentials')
    print('GET /api/mcp/credentials:', r.status_code)
    servers = r.json.get('servers', {})
    if servers:
        first = list(servers.values())[0]
        print('  First server has notes field:', 'notes' in first)

print('All tests done!')
