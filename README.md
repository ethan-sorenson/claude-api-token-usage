# Claude API Token Usage Demo - Python Web Server

A Flask-based web application that demonstrates Claude API usage with real-time token tracking, cost estimation, and **OAuth 2.0 authentication for multiple MCP servers**.

## 🚀 Features

- **Token Usage Tracking**: Real-time monitoring of input/output tokens
- **Cost Estimation**: Live cost calculation based on current Anthropic pricing
- **Context Window Visualization**: Visual progress bar showing context usage
- **Session Management**: Save, load, and resume conversation sessions
- **Session Auditing**: Full API request/response logging for each session
- **OAuth 2.0 with PKCE**: Secure authentication without client secrets
- **Multiple MCP Servers**: Manage unlimited MCP servers with shared OAuth
- **Modular Architecture**: Separated OAuth and MCP management modules
- **Token Caching**: Automatic token refresh and session management (7-day expiration)
- **Secure API Handling**: API keys and OAuth tokens processed server-side
- **No CORS Issues**: Works on any deployment platform

---

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Detailed Setup](#detailed-setup)
- [OAuth Configuration](#oauth-configuration)
- [Using the Application](#using-the-application)
- [MCP Server Management](#mcp-server-management)
- [Architecture](#architecture)
- [Deployment](#deployment)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [Development](#development)

---

## ⚡ Quick Start

Get up and running in 5 minutes!

### 1. Install Dependencies (1 minute)

```bash
# Clone the repository
git clone https://github.com/ethan-sorenson/claude-api-token-usage.git
cd claude-api-token-usage

# Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure OAuth - Optional (2 minutes)

**Choose your preferred method:**

#### Option A: Environment Variables (Recommended for Docker/Cloud)
```bash
# Windows PowerShell
$env:POPDOCK_OAUTH_CLIENT_ID="your-client-id"
$env:SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"

# Linux/Mac
export POPDOCK_OAUTH_CLIENT_ID="your-client-id"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

#### Option B: Using .env file (Recommended for local dev)
```bash
cp .env.example .env
# Edit .env with your credentials
```

#### Option C: Skip OAuth (Simplest)
- Just skip to Step 3
- OAuth features will be disabled
- You can configure OAuth later when needed

**Note**: Popdock uses PKCE (Proof Key for Code Exchange), so no client secret is required.

### 3. Start the Server (30 seconds)

```bash
python app.py
```

You should see:
```
Claude API Token Usage Demo Server Starting...
Local URL: http://localhost:5000
```

### 4. Open Browser

Navigate to: **http://localhost:5000**

### 5. Configure & Start Chatting

1. Enter your Anthropic API key
2. (Optional) Enable MCP servers and authenticate with OAuth
3. Start chatting to see real-time token usage!

---

## 🛠️ Detailed Setup

### Prerequisites

- **Python 3.8 or higher**
- **pip** (Python package installer)
- **Anthropic API key** - Get from https://console.anthropic.com/
- **OAuth Client ID** (Optional) - For MCP authentication

### Installation Steps

1. **Create a virtual environment (recommended)**
   ```bash
   python -m venv venv
   
   # On Windows:
   venv\Scripts\activate
   
   # On macOS/Linux:
   source venv/bin/activate
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

   Key dependencies:
   - `Flask` - Web framework
   - `Flask-CORS` - Cross-origin resource sharing
   - `Flask-Session` - Server-side session management
   - `requests` - HTTP library
   - `requests-oauthlib` - OAuth 2.0 client
   - `python-dotenv` (optional) - Environment variable management

3. **Verify Setup**
   ```bash
   python setup_check.py
   ```
   This will check all dependencies and configuration.

---

## 🔐 OAuth Configuration

### Overview

The application supports OAuth 2.0 with PKCE for secure MCP server authentication:

- **No Client Secret Required**: Uses PKCE for enhanced security
- **Automatic Token Refresh**: Tokens refresh 60 seconds before expiration
- **Session-Based Caching**: Tokens stored server-side for 7 days
- **Shared Authentication**: All MCP servers use the same OAuth token

### Configuration Methods

#### Method 1: Environment Variables (Production)

```bash
# Required
export POPDOCK_OAUTH_CLIENT_ID="your-client-id"
export SECRET_KEY="your-secret-key"

# Optional (have defaults)
export POPDOCK_OAUTH_AUTH_URL="https://mcp-eqa.popdock.com/oauth/authorize"
export POPDOCK_OAUTH_TOKEN_URL="https://mcp-eqa.popdock.com/oauth/token"
export OAUTH_REDIRECT_URI="http://localhost:5000/oauth/callback"
export POPDOCK_OAUTH_SCOPE="mcp:read mcp:write"
```

#### Method 2: .env File (Development)

1. Copy the example file:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env`:
   ```env
   POPDOCK_OAUTH_CLIENT_ID=your-client-id
   SECRET_KEY=your-secret-key
   ```

3. Generate a secure secret key:
   ```python
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

#### Method 3: No Configuration (OAuth Disabled)

- Start without any OAuth setup
- Application works normally without MCP features
- Configure OAuth later when needed

### Obtaining OAuth Credentials

Contact your Popdock administrator to register your application and obtain:

- **Client ID**: Unique identifier for your application
- **Redirect URI**: `http://localhost:5000/oauth/callback` (or your production URL)
- **Scopes**: `mcp:read mcp:write`

**Important**: Popdock MCP uses PKCE, so no client secret is needed!

### PKCE (Proof Key for Code Exchange)

PKCE is a security extension for OAuth 2.0:

1. **Code Verifier**: Random 43-128 character string
2. **Code Challenge**: SHA256 hash of the verifier
3. **Authorization**: Challenge sent to OAuth provider
4. **Token Exchange**: Verifier proves the request is legitimate

This prevents authorization code interception attacks.

---

## 💻 Using the Application

### Basic Usage

1. **Start the server**
   ```bash
   python app.py
   ```

2. **Open the web interface**
   - Navigate to http://localhost:5000
   - Enter your Anthropic API key

3. **Start chatting**
   - Type your message
   - See real-time token usage
   - Monitor costs and context window

### OAuth Authentication Flow

1. **Enable MCP Servers**
   - Check "Enable MCP Servers"
   - Add one or more MCP servers

2. **Authenticate**
   - Click "🔐 Authenticate with OAuth"
   - A popup window opens with OAuth provider
   - Log in and authorize the application
   - Popup closes automatically on success

3. **Verify Authentication**
   - Status shows "✓ Authenticated"
   - Test connection with 🔌 icon on server cards

4. **Use in Chat**
   - Send messages as usual
   - OAuth tokens automatically included
   - Tokens automatically refresh when needed

### Token Management

- **Token Expiration**: Access tokens typically last 1 hour
- **Refresh Tokens**: Last 7 days
- **Auto-Refresh**: Happens 60 seconds before expiration
- **Re-authentication**: Prompted if refresh fails

### Session Management

**Automatic Session Saving**

The application **automatically saves your conversation sessions** after every message exchange - no manual saving required! Each session includes:
- All messages exchanged
- Full API requests and responses
- Token usage metrics
- Timestamps

**Working with Sessions:**

1. **Auto-Save**: ✅ Sessions are saved automatically after each message (you'll see "Auto-saved at [time]" in the session info)
2. **Start New Session**: Click "➕ New Session" to begin fresh (auto-saves current session first)
3. **Load Previous Session**: Click "📁 Load Session" to browse and restore saved conversations
4. **Session Persistence**: All sessions are preserved across application restarts

**No Manual Saving Needed!**

Sessions save automatically in the background - just chat naturally and your conversation is continuously preserved. The session info panel shows when the last auto-save occurred.

**Session Storage:**

- Sessions are stored as JSON files in the `sessions/` directory
- Each session includes complete audit trail of API interactions
- Use for debugging, analysis, or compliance requirements
- Sessions persist across application restarts

---

## 🖥️ MCP Server Management

### Adding MCP Servers

1. Click "Enable MCP Servers"
2. Click "➕ Add MCP Server"
3. Configure:
   - **Server Name**: e.g., "Popdock CRM"
   - **Server URL**: e.g., "https://mcp-eqa.popdock.com/mcp/..."
4. Enable/disable with checkbox
5. Test connection with 🔌 icon

### Managing Multiple Servers

- **Add Unlimited Servers**: No limit on number of servers
- **Enable/Disable**: Toggle servers with checkbox
- **Shared OAuth**: All servers use same OAuth token
- **Individual Testing**: Test each server independently
- **Remove Servers**: Click 🗑️ to remove

### Server Storage

- Configurations saved in browser localStorage
- Persists across browser sessions
- OAuth token stored server-side in Flask session

---

## 🏗️ Architecture

### Modular Design

The application uses a clean, modular architecture:

```
claude-api-token-usage/
├── app.py                      # Flask backend (routes, API proxy)
├── oauth_handler.py            # OAuth 2.0 implementation with PKCE
├── mcp_manager.py              # Multi-MCP server management
├── index.html                  # Frontend web application
├── requirements.txt            # Python dependencies
├── .env.example               # Environment variables template
├── setup_check.py             # Configuration validation
└── flask_session/             # Server-side session storage
```

### Backend Modules

#### `oauth_handler.py`
**Purpose**: Generic OAuth 2.0 authentication with PKCE

**Key Classes**:
- `OAuthConfig`: Configuration container
- `PKCEHelper`: PKCE code generation and validation
- `OAuthTokenManager`: Session-based token storage
- `OAuthFlow`: Main OAuth flow orchestration

**Benefits**:
- MCP-agnostic implementation
- Reusable across different OAuth providers
- Centralized token management
- Easy to test and maintain

#### `mcp_manager.py`
**Purpose**: Manage multiple MCP server configurations

**Key Classes**:
- `MCPServer`: Represents a single MCP server
- `MCPManager`: Manages collection of servers

**Features**:
- Add/remove servers dynamically
- OAuth authentication for all servers
- Convert servers to Anthropic API format
- Enable/disable individual servers

#### `app.py`
**Main Flask Application**:
- Uses `oauth_handler` for OAuth operations
- Uses `mcp_manager` for server management
- Proxies requests to Anthropic API
- Handles token refresh automatically

### Frontend

**Single-page application** with:
- Real-time token tracking
- Cost estimation
- Context window visualization
- MCP server management UI
- OAuth authentication flow

### Data Flow

```
User → Frontend (index.html)
    → Backend (app.py)
        → OAuth Handler (oauth_handler.py)
        → MCP Manager (mcp_manager.py)
            → Anthropic API
```

---

## 🌐 Deployment

### Local Development

```bash
python app.py
```
Access at: http://localhost:5000

### Heroku

```bash
# Create Procfile
echo "web: python app.py" > Procfile

# Create runtime.txt
echo "python-3.11.6" > runtime.txt

# Deploy
git add .
git commit -m "Deploy to Heroku"
heroku create your-app-name
heroku config:set POPDOCK_OAUTH_CLIENT_ID=your-client-id
heroku config:set SECRET_KEY=your-secret-key
git push heroku main
```

### Railway

1. Connect your GitHub repo to Railway
2. Set environment variables in Railway dashboard
3. Railway auto-detects Flask and deploys

### Render

1. Connect your GitHub repo to Render
2. Set build command: `pip install -r requirements.txt`
3. Set start command: `python app.py`
4. Set environment variables in Render dashboard

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
EXPOSE 5000
CMD ["python", "app.py"]
```

Build and run:
```bash
docker build -t claude-token-usage .
docker run -p 5000:5000 \
  -e POPDOCK_OAUTH_CLIENT_ID=your-client-id \
  -e SECRET_KEY=your-secret-key \
  claude-token-usage
```

### Environment Variables for Production

```bash
# Required
POPDOCK_OAUTH_CLIENT_ID=your-client-id
SECRET_KEY=your-secret-key

# Optional
PORT=5000
DEBUG=false
OAUTH_REDIRECT_URI=https://yourdomain.com/oauth/callback
```

---

## 📡 API Reference

### Endpoints

#### `GET /`
Main web application

#### `POST /api/chat`
Proxy endpoint for Anthropic API with MCP support

**Request Body**:
```json
{
  "api_key": "sk-ant-...",
  "model": "claude-sonnet-4-20250514",
  "max_tokens": 2000,
  "messages": [...],
  "servers": [
    {
      "id": "server-1",
      "name": "Popdock CRM",
      "url": "https://mcp-eqa.popdock.com/mcp/...",
      "use_oauth": true
    }
  ]
}
```

**Response**:
```json
{
  "content": [...],
  "usage": {
    "input_tokens": 100,
    "output_tokens": 50
  }
}
```

#### `POST /api/test-mcp`
Test MCP server connection

**Request Body**:
```json
{
  "server_id": "server-1",
  "servers": [...]
}
```

**Response**:
```json
{
  "status": "success",
  "message": "MCP server connection successful!",
  "prompts_count": 5,
  "prompts": [...]
}
```

#### `GET /api/oauth/status`
Check OAuth authentication status

**Response**:
```json
{
  "authenticated": true,
  "token_present": true,
  "token_valid": true,
  "expires_at": 1734658800
}
```

#### `GET /oauth/authorize`
Initiate OAuth authorization flow

#### `GET /oauth/callback`
Handle OAuth callback and exchange code for token

#### `POST /api/oauth/logout`
Clear OAuth session

#### `GET /api/health`
Health check endpoint

---

## 🔧 Troubleshooting

### Common Issues

#### "Module not found" Error
```bash
pip install -r requirements.txt
```

#### Port Already in Use
```bash
# Kill process on port 5000 or change port
export PORT=8000
python app.py
```

#### "OAuth not configured" Error
- Ensure `POPDOCK_OAUTH_CLIENT_ID` is set
- Restart the Flask server after updating configuration

#### "OAuth token expired" Error
- Click "🔐 Authenticate with OAuth" to re-authenticate
- Check that token refresh is working in logs

#### Popup Blocked
- Allow popups for localhost:5000 in your browser
- Check browser console for errors

#### Can't Connect to MCP Server
- Verify MCP server URL is correct
- Ensure OAuth authentication is successful
- Test connection with 🔌 icon
- Check server logs for detailed error messages

#### Import Errors
```bash
pip install --upgrade -r requirements.txt
```

#### Session Issues
- Clear Flask session: `rm -rf flask_session/`
- Clear browser localStorage
- Restart the application

---

## 🔒 Security

### Best Practices

1. **Never commit `.env` file**
   - Add to `.gitignore`
   - Use environment variables in production

2. **Use HTTPS in production**
   - OAuth requires secure connections
   - Use proper SSL certificates

3. **Rotate secrets regularly**
   - Update `SECRET_KEY` periodically
   - Monitor for security advisories

4. **Monitor token usage**
   - Check logs for authentication issues
   - Review token expiration patterns

5. **Validate inputs**
   - Application validates all user inputs
   - Prevents injection attacks

### Security Features

- **PKCE for OAuth**: Prevents authorization code interception
- **Server-side sessions**: Tokens never exposed to client
- **Automatic token refresh**: Reduces token exposure time
- **Input validation**: Prevents malicious inputs
- **Error handling**: Doesn't leak sensitive information

### Token Storage

- **OAuth Tokens**: Stored in Flask sessions (server-side filesystem)
- **API Keys**: Sent with each request, never stored
- **Session Files**: Located in `flask_session/` directory
- **Expiration**: Sessions expire after 7 days

---

## 👨‍💻 Development

### Project Structure

```
claude-api-token-usage/
├── app.py                      # Flask backend server
├── oauth_handler.py            # OAuth 2.0 module
├── mcp_manager.py              # MCP server manager
├── index.html                  # Frontend web application
├── requirements.txt            # Python dependencies
├── .env.example               # Environment template
├── setup_check.py             # Setup validation
├── .gitignore                 # Git ignore rules
├── flask_session/             # Session storage (gitignored)
└── logs/                      # Application logs (gitignored)
```

### Adding Features

1. **Backend changes**: Modify `app.py`, `oauth_handler.py`, or `mcp_manager.py`
2. **Frontend changes**: Modify `index.html`
3. **New dependencies**: Add to `requirements.txt`
4. **Documentation**: Update this README

### Code Examples

#### Add MCP Server Programmatically

```python
from mcp_manager import MCPServer, MCPManager

# Create manager
manager = MCPManager()

# Add OAuth server
server = MCPServer(
    name='Popdock CRM',
    url='https://mcp-eqa.popdock.com/mcp/...',
    use_oauth=True
)
manager.add_server('server-1', server)

# Prepare for Anthropic
servers = manager.prepare_for_anthropic(oauth_token='bearer-token')
```

#### Use OAuth Flow

```python
from oauth_handler import create_oauth_from_env

# Create OAuth flow
oauth_flow = create_oauth_from_env()

# Initiate authorization
auth_url, state, verifier = oauth_flow.initiate_authorization()

# Exchange code for token
token = oauth_flow.exchange_code_for_token(code, verifier)

# Refresh token
new_token = oauth_flow.refresh_token(refresh_token)
```

### Testing

```bash
# Run setup check
python setup_check.py

# Test OAuth configuration
python -c "from oauth_handler import create_oauth_from_env; print(create_oauth_from_env())"

# Check logs
tail -f logs/app.log
```

---

## 📊 Token Pricing (Current)

- **Input tokens**: $3.00 per 1M tokens
- **Output tokens**: $15.00 per 1M tokens
- **Context window**: 200,000 tokens (adjustable)
- **Model**: Claude Sonnet 4 (claude-sonnet-4-20250514)

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature-name`
3. Make your changes
4. Test thoroughly
5. Submit a pull request

---

## 📄 License

This project is open source and available under the MIT License.

---

## 🆘 Support

If you encounter issues:

1. Check the [Troubleshooting](#troubleshooting) section
2. Review Flask server logs in terminal
3. Open browser developer console for frontend errors
4. Check `logs/app.log` for detailed logs
5. Create an issue on GitHub with error details

---

## 🎯 Key Differences from HTML Version

- ✅ **No CORS issues** - Works on any hosting platform
- ✅ **Secure API handling** - Keys processed server-side
- ✅ **Better error handling** - More informative error messages
- ✅ **Deployment ready** - Works with Heroku, Railway, Render, etc.
- ✅ **Environment configuration** - Configurable via environment variables
- ✅ **Modular architecture** - Separated OAuth and MCP modules
- ✅ **Multiple MCP servers** - Unlimited server support

---

**Built with ❤️ using Flask, HTML5, and the Anthropic Claude API**

---

## 📚 Additional Documentation

For more detailed information, see the following files in this repository:

- `.env.example` - Environment variable template
- `setup_check.py` - Setup validation script
- `oauth_handler.py` - OAuth implementation source code
- `mcp_manager.py` - MCP manager source code