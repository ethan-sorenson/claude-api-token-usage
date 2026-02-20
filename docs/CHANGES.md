# Simplified MCP Credential Storage - Changes Summary

## What Changed

Removed the complex Flask-Session caching system and replaced it with a simple local JSON file for storing MCP server credentials.

## Files Modified

### 1. app.py
- **Removed**: Flask-Session imports and configuration
- **Removed**: Session directory setup
- **Added**: `MCP_CREDENTIALS_FILE` constant pointing to `mcp_credentials.json`
- **Added**: `load_mcp_credentials()` function to read from JSON file
- **Added**: `save_mcp_credentials()` function to write to JSON file
- **Added**: Two new API endpoints:
  - `GET /api/mcp/credentials` - Load saved credentials
  - `POST /api/mcp/credentials` - Save credentials

### 2. requirements.txt
- **Removed**: `Flask-Session==0.5.0` dependency

### 3. index.html
- **Modified**: `saveMcpServers()` - Now saves to backend API instead of localStorage
- **Modified**: `loadMcpServers()` - Now loads from backend API instead of localStorage
- **Modified**: Made `loadFromSession()` and `toggleMcpConfig()` async to properly await API calls

### 4. .gitignore
- **Added**: `mcp_credentials.json` to prevent committing credentials
- **Added**: `logs/` and `flask_session/` directories

### 5. New Files
- **MCP_CREDENTIALS.md** - Documentation for the credentials file format

## How It Works

1. When you configure MCP servers in the UI and click "Test Connection" or "Send Message", the credentials are automatically saved to `mcp_credentials.json`
2. When you reload the page, credentials are loaded from `mcp_credentials.json` automatically
3. All credentials are stored in plain text (no encryption) - suitable for personal use only

## Testing

To verify the changes work:

1. Stop the Flask server if running
2. Delete the `flask_session` directory (no longer needed)
3. Restart the server: `python app.py`
4. Open the web interface
5. Add an MCP server with credentials
6. Check that `mcp_credentials.json` file is created
7. Reload the page and verify credentials are loaded

## Security Note

**This stores credentials in PLAIN TEXT.** This is intentional for personal use. Do not use this in production or share the `mcp_credentials.json` file.

## Benefits

- ✅ Much simpler than Flask-Session
- ✅ Easy to backup (just copy the JSON file)
- ✅ Easy to edit manually if needed
- ✅ No complex session management
- ✅ One less dependency (Flask-Session removed)
- ✅ Persistent across server restarts
- ✅ Human-readable format
