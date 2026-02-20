"""Quick debug script to inspect a session's structure."""
import json
from server.db import DatabaseManager

db = DatabaseManager('config.json')
data = db.get_session('session_1771495733565')

print(f"messages: {len(data.get('messages', []))}")
print(f"conv_history: {len(data.get('conversation_history', []))}")
print()

# Check conversation history roles
print("=== CONVERSATION HISTORY ===")
for i, msg in enumerate(data.get('conversation_history', [])):
    role = msg.get('role')
    content = msg.get('content', '')
    if isinstance(content, str):
        preview = content[:100]
    elif isinstance(content, list):
        preview = json.dumps(content, default=str)[:100]
    else:
        preview = str(content)[:100]
    print(f"  [{i}] role={role}, content preview: {preview}")

print()
print("=== SESSION MESSAGES (API requests) ===")
for i, msg in enumerate(data.get('messages', [])):
    req = msg.get('request', {})
    resp = msg.get('response', {})
    req_msgs = req.get('messages', [])
    has_content = 'content' in resp
    
    # Check what the last user message looks like
    last_user = None
    for m in reversed(req_msgs):
        if m.get('role') == 'user':
            last_user = m
            break
    
    print(f"  msg[{i}]:")
    print(f"    req keys: {list(req.keys())}")
    print(f"    req.messages count: {len(req_msgs)}")
    if last_user:
        c = last_user.get('content', '')
        if isinstance(c, str):
            print(f"    last user msg: {c[:100]}")
        elif isinstance(c, list):
            print(f"    last user msg (list): {json.dumps(c, default=str)[:100]}")
    else:
        print(f"    NO user message found in req.messages")
        if req_msgs:
            print(f"    roles in req.messages: {[m.get('role') for m in req_msgs]}")
    
    print(f"    resp keys: {list(resp.keys())}")
    print(f"    resp has content: {has_content}")
    if has_content:
        content = resp['content']
        if isinstance(content, list):
            types = [b.get('type', '?') for b in content]
            print(f"    resp content types: {types}")
