import sys, os, json, requests
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = 'http://127.0.0.1:5000'

# Test save comparison
test_data = {
    'session_id': 'comparison_test_999',
    'timestamp': '2026-02-17T12:00:00Z',
    'type': 'comparison',
    'note': 'Test comparison',
    'left_session_id': 'comparison_test_999_left',
    'right_session_id': 'comparison_test_999_right',
    'left_config': {'servers': [{'name': 'ServerA'}], 'enabled_servers': ['s1']},
    'right_config': {'servers': [{'name': 'ServerB'}], 'enabled_servers': ['s2']},
    'left_data': {
        'messages': [{'userMessage': 'hello', 'response': {'content': [{'type': 'text', 'text': 'hi'}]}, 'tokens': 100, 'cost': 0.01, 'duration': 1.5, 'timestamp': '2026-02-17T12:00:01Z'}],
        'totalTokens': 100, 'totalTime': 1.5, 'totalCost': 0.01
    },
    'right_data': {
        'messages': [{'userMessage': 'hello', 'response': {'content': [{'type': 'text', 'text': 'hey'}]}, 'tokens': 80, 'cost': 0.008, 'duration': 1.2, 'timestamp': '2026-02-17T12:00:02Z'}],
        'totalTokens': 80, 'totalTime': 1.2, 'totalCost': 0.008
    }
}

r = requests.post(f'{BASE}/api/sessions', json=test_data)
print('Save:', r.status_code, r.json())

# Test load comparison
r = requests.get(f'{BASE}/api/sessions/comparison_test_999')
loaded = r.json()
print('Load status:', r.status_code)
print('Has left_data:', 'left_data' in loaded)
print('Has right_data:', 'right_data' in loaded)
print('Has left_config:', 'left_config' in loaded)
print('Left messages count:', len(loaded.get('left_data', {}).get('messages', [])))
print('Right totalTokens:', loaded.get('right_data', {}).get('totalTokens'))
print('Note:', loaded.get('note'))

# Cleanup
r = requests.delete(f'{BASE}/api/sessions/comparison_test_999')
print('Delete:', r.status_code, r.json())
