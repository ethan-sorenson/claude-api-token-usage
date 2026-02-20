"""
Database Manager Module
Handles all SQL Server database operations for MCP credentials and sessions.
"""

import json
import logging
import os
import pyodbc
from datetime import datetime
from typing import Dict, List, Any, Optional
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manages SQL Server database operations for MCP and sessions."""

    def __init__(self, config_path: str = "config.json"):
        self.config = self._load_config(config_path)
        self.connection_string = self._build_connection_string()
        self._test_connection()

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            logger.error(f"Config file not found: {config_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise

    def _build_connection_string(self) -> str:
        sql = self.config.get('sql_server', {})
        server = sql.get('server', 'localhost')
        database = sql.get('database', 'MCPTokenUsage')
        driver = sql.get('driver', 'ODBC Driver 17 for SQL Server')

        if sql.get('use_windows_auth', True):
            return f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"
        username = sql.get('username', '')
        password = sql.get('password', '')
        if not username or not password:
            raise ValueError("SQL Server username and password required when use_windows_auth is false")
        return f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};UID={username};PWD={password}"

    def _test_connection(self):
        try:
            with self.get_connection() as conn:
                conn.cursor().execute("SELECT 1").fetchone()
            logger.info("Database connection successful")
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            raise

    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = pyodbc.connect(self.connection_string)
            yield conn
        except Exception as e:
            logger.error(f"Database connection error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn:
                conn.close()

    # ── MCP CREDENTIALS ────────────────────────────────────────────────

    def load_mcp_credentials(self) -> Dict[str, Any]:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT ServerID, ServerName, URL, AuthMethod, Enabled, Collapsed, Notes, LastValidated
                    FROM MCPServers ORDER BY ServerName
                """)

                servers = {}
                for row in cursor.fetchall():
                    sid = row.ServerID
                    servers[sid] = {
                        'name': row.ServerName, 'url': row.URL,
                        'auth_method': row.AuthMethod,
                        'enabled': bool(row.Enabled),
                        'collapsed': bool(row.Collapsed) if row.Collapsed is not None else False,
                        'notes': row.Notes or '',
                    }
                    auth = self._get_server_auth(cursor, sid)
                    if auth:
                        servers[sid].update(auth)
                    headers = self._get_server_headers(cursor, sid)
                    if headers:
                        servers[sid]['headers'] = headers
                    prompts = self._get_server_prompts(cursor, sid)
                    if prompts:
                        servers[sid]['prompts'] = prompts
                    tools = self._get_server_tools(cursor, sid)
                    if tools:
                        servers[sid]['tools'] = tools

                logger.info(f"Loaded {len(servers)} MCP servers from database")
                return {'servers': servers}
        except Exception as e:
            logger.error(f"Failed to load MCP credentials: {e}")
            raise

    def _get_server_auth(self, cursor, server_id: str) -> Optional[Dict[str, Any]]:
        cursor.execute("""
            SELECT AuthType, Token, ClientID, ClientSecret, AuthorizationEndpoint,
                   TokenEndpoint, RedirectURI, RefreshToken, AccessToken,
                   TokenExpiresAt, TokenObtainedAt, Scopes, Resource, PKCECodeVerifier
            FROM MCPServerAuth WHERE ServerID = ?
        """, server_id)
        row = cursor.fetchone()
        if not row:
            return None
        d = {}
        for attr, key in [
            ('Token', 'auth_token'), ('ClientID', 'client_id'),
            ('ClientSecret', 'client_secret'), ('AuthorizationEndpoint', 'authorization_endpoint'),
            ('TokenEndpoint', 'token_endpoint'), ('RedirectURI', 'redirect_uri'),
            ('RefreshToken', 'refresh_token'), ('AccessToken', 'access_token'),
            ('TokenExpiresAt', 'token_expires_at'), ('TokenObtainedAt', 'token_obtained_at'),
            ('Scopes', 'scopes'), ('Resource', 'resource'),
            ('PKCECodeVerifier', 'pkce_code_verifier'),
        ]:
            val = getattr(row, attr, None)
            if val is not None:
                d[key] = val
        return d or None

    def _get_server_headers(self, cursor, server_id: str) -> Optional[Dict[str, str]]:
        cursor.execute("SELECT HeaderName, HeaderValue FROM MCPServerHeaders WHERE ServerID = ?", server_id)
        headers = {r.HeaderName: r.HeaderValue for r in cursor.fetchall()}
        return headers or None

    def _get_server_prompts(self, cursor, server_id: str) -> Optional[List[Dict]]:
        cursor.execute("SELECT PromptID, PromptName, Description FROM MCPServerPrompts WHERE ServerID = ?", server_id)
        prompts = []
        for row in cursor.fetchall():
            prompt = {'name': row.PromptName, 'description': row.Description}
            cursor.execute("SELECT ArgumentName, Required FROM MCPServerPromptArguments WHERE PromptID = ?", row.PromptID)
            args = [{'name': a.ArgumentName, 'required': bool(a.Required)} for a in cursor.fetchall()]
            if args:
                prompt['arguments'] = args
            prompts.append(prompt)
        return prompts or None

    def _get_server_tools(self, cursor, server_id: str) -> Optional[List[Dict]]:
        cursor.execute("SELECT ToolID, ToolName, ToolTitle, Description, InputSchema, OutputSchema FROM MCPServerTools WHERE ServerID = ?", server_id)
        tools = []
        for row in cursor.fetchall():
            tool = {'name': row.ToolName}
            if row.ToolTitle:
                tool['title'] = row.ToolTitle
            if row.Description:
                tool['description'] = row.Description
            if row.InputSchema:
                tool['inputSchema'] = json.loads(row.InputSchema)
            if row.OutputSchema:
                tool['outputSchema'] = json.loads(row.OutputSchema)
            cursor.execute("SELECT AnnotationKey, AnnotationValue FROM MCPServerToolAnnotations WHERE ToolID = ?", row.ToolID)
            anns = {}
            for a in cursor.fetchall():
                val = a.AnnotationValue
                if val == 'True':
                    val = True
                elif val == 'False':
                    val = False
                anns[a.AnnotationKey] = val
            if anns:
                tool['annotations'] = anns
            tools.append(tool)
        return tools or None

    def save_mcp_credentials(self, credentials: Dict[str, Any]) -> bool:
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                for sid, data in credentials.get('servers', {}).items():
                    cursor.execute("""
                        IF EXISTS (SELECT 1 FROM MCPServers WHERE ServerID = ?)
                            UPDATE MCPServers SET ServerName=?, URL=?, AuthMethod=?, Enabled=?, Collapsed=?, Notes=?, LastValidated=GETDATE() WHERE ServerID=?
                        ELSE
                            INSERT INTO MCPServers (ServerID, ServerName, URL, AuthMethod, Enabled, Collapsed, Notes) VALUES (?,?,?,?,?,?,?)
                    """, sid, data.get('name'), data.get('url'), data.get('auth_method'),
                        data.get('enabled', True), data.get('collapsed', False), data.get('notes', ''), sid,
                        sid, data.get('name'), data.get('url'), data.get('auth_method'),
                        data.get('enabled', True), data.get('collapsed', False), data.get('notes', ''))
                    self._save_server_auth(cursor, sid, data)
                    self._save_server_headers(cursor, sid, data.get('headers', {}))
                    self._save_server_prompts(cursor, sid, data.get('prompts', []))
                    self._save_server_tools(cursor, sid, data.get('tools', []))
                conn.commit()
                logger.info(f"Saved {len(credentials.get('servers', {}))} MCP servers to database")
                return True
        except Exception as e:
            logger.error(f"Failed to save MCP credentials: {e}")
            raise

    def _save_server_auth(self, cursor, server_id, data):
        cursor.execute("DELETE FROM MCPServerAuth WHERE ServerID = ?", server_id)
        # 'token' comes from config.json user_inputs field name;
        # 'auth_token' is the canonical DB key — accept either.
        token_value = data.get('auth_token') or data.get('token')
        cursor.execute("""
            INSERT INTO MCPServerAuth (ServerID, AuthType, Token, ClientID, ClientSecret,
                AuthorizationEndpoint, TokenEndpoint, RedirectURI, RefreshToken, AccessToken,
                TokenExpiresAt, TokenObtainedAt, Scopes, Resource, PKCECodeVerifier)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, server_id, data.get('auth_method'), token_value,
            data.get('client_id'), data.get('client_secret'),
            data.get('authorization_endpoint'), data.get('token_endpoint'),
            data.get('redirect_uri'), data.get('refresh_token'), data.get('access_token'),
            data.get('token_expires_at'), data.get('token_obtained_at'),
            data.get('scopes'), data.get('resource'), data.get('pkce_code_verifier'))

    def _save_server_headers(self, cursor, server_id, headers):
        cursor.execute("DELETE FROM MCPServerHeaders WHERE ServerID = ?", server_id)
        for k, v in headers.items():
            cursor.execute("INSERT INTO MCPServerHeaders (ServerID, HeaderName, HeaderValue) VALUES (?,?,?)", server_id, k, v)

    def _save_server_prompts(self, cursor, server_id, prompts):
        cursor.execute("DELETE FROM MCPServerPrompts WHERE ServerID = ?", server_id)
        for p in prompts:
            cursor.execute("INSERT INTO MCPServerPrompts (ServerID, PromptName, Description) OUTPUT INSERTED.PromptID VALUES (?,?,?)",
                           server_id, p.get('name'), p.get('description'))
            pid = cursor.fetchone()[0]
            for a in p.get('arguments', []):
                cursor.execute("INSERT INTO MCPServerPromptArguments (PromptID, ArgumentName, Required) VALUES (?,?,?)",
                               pid, a.get('name'), a.get('required', False))

    def _save_server_tools(self, cursor, server_id, tools):
        cursor.execute("DELETE FROM MCPServerTools WHERE ServerID = ?", server_id)
        for t in tools:
            inp = json.dumps(t.get('inputSchema')) if t.get('inputSchema') else None
            out = json.dumps(t.get('outputSchema')) if t.get('outputSchema') else None
            cursor.execute("""
                INSERT INTO MCPServerTools (ServerID, ToolName, ToolTitle, Description, InputSchema, OutputSchema)
                OUTPUT INSERTED.ToolID VALUES (?,?,?,?,?,?)
            """, server_id, t.get('name'), t.get('title'), t.get('description'), inp, out)
            tid = cursor.fetchone()[0]
            for k, v in t.get('annotations', {}).items():
                cursor.execute("INSERT INTO MCPServerToolAnnotations (ToolID, AnnotationKey, AnnotationValue) VALUES (?,?,?)", tid, k, str(v))

    # ── SESSIONS ───────────────────────────────────────────────────────

    def _ensure_sessions_provider_state(self):
        """Add ProviderState column if it doesn't exist (migration helper)."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    IF NOT EXISTS (
                        SELECT * FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME = 'Sessions' AND COLUMN_NAME = 'ProviderState'
                    )
                    ALTER TABLE Sessions ADD ProviderState NVARCHAR(MAX) NULL
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to ensure ProviderState column: {e}")

    def get_session_state(self, session_id):
        """Load lightweight session metrics and provider-specific state.

        Returns a dict with total_input_tokens, total_output_tokens, total_cost,
        and any provider-specific fields (e.g. mistral_conversation_id, openai_history).
        Returns empty dict if session not found.
        """
        self._ensure_sessions_provider_state()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT TotalInputTokens, TotalOutputTokens, ProviderState FROM Sessions WHERE SessionID = ?",
                    session_id,
                )
                row = cursor.fetchone()
                if not row:
                    return {}
                state = {}
                if row.ProviderState:
                    try:
                        state = json.loads(row.ProviderState)
                    except (json.JSONDecodeError, TypeError):
                        pass
                state.setdefault('total_input_tokens', row.TotalInputTokens or 0)
                state.setdefault('total_output_tokens', row.TotalOutputTokens or 0)
                state.setdefault('total_cost', 0.0)
                return state
        except Exception as e:
            logger.error(f"Failed to get session state {session_id}: {e}")
            return {}

    def update_session_state(self, session_id, metrics, extra=None):
        """Update session metrics and provider state mid-conversation.

        *metrics* must contain total_input_tokens, total_output_tokens, total_cost.
        *extra* is an optional dict of provider-specific fields to persist.
        """
        self._ensure_sessions_provider_state()
        try:
            provider_state = {'total_cost': metrics.get('total_cost', 0.0)}
            if extra:
                provider_state.update(extra)
            ps_json = json.dumps(provider_state, default=str)

            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    IF EXISTS (SELECT 1 FROM Sessions WHERE SessionID = ?)
                        UPDATE Sessions
                        SET TotalInputTokens = ?, TotalOutputTokens = ?, ProviderState = ?
                        WHERE SessionID = ?
                    ELSE
                        INSERT INTO Sessions (SessionID, SessionTimestamp, TotalInputTokens, TotalOutputTokens, ProviderState)
                        VALUES (?, GETDATE(), ?, ?, ?)
                """,
                    session_id,
                    metrics.get('total_input_tokens', 0),
                    metrics.get('total_output_tokens', 0),
                    ps_json,
                    session_id,
                    session_id,
                    metrics.get('total_input_tokens', 0),
                    metrics.get('total_output_tokens', 0),
                    ps_json,
                )
                conn.commit()
        except Exception as e:
            logger.warning(f"Could not update session state {session_id}: {e}")

    def list_sessions(self, limit=None):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                q = """SELECT s.SessionID, s.SessionTimestamp, s.TotalInputTokens, s.TotalOutputTokens, s.TotalTokens, s.TokenID, s.Model, s.Note,
                              (SELECT COUNT(*) FROM SessionMessages m WHERE m.SessionID = s.SessionID AND m.Role = 'user') AS UserMessageCount
                       FROM Sessions s ORDER BY s.SessionTimestamp DESC"""
                if limit:
                    q = f"SELECT TOP {limit} " + q[7:]  # replace 'SELECT ' with 'SELECT TOP N '
                cursor.execute(q)
                return [{
                    'session_id': r.SessionID,
                    'timestamp': r.SessionTimestamp.isoformat() if r.SessionTimestamp else None,
                    'total_input_tokens': r.TotalInputTokens,
                    'total_output_tokens': r.TotalOutputTokens,
                    'total_tokens': r.TotalTokens,
                    'token_id': r.TokenID or '',
                    'model': r.Model or '',
                    'note': r.Note or '',
                    'user_message_count': r.UserMessageCount or 0,
                } for r in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            raise

    def get_session(self, session_id):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT SessionID, SessionTimestamp, TotalInputTokens, TotalOutputTokens, TokenID, Model, Note FROM Sessions WHERE SessionID = ?", session_id)
                row = cursor.fetchone()
                if not row:
                    return None
                data = {
                    'session_id': row.SessionID,
                    'timestamp': row.SessionTimestamp.isoformat() if row.SessionTimestamp else None,
                    'total_input_tokens': row.TotalInputTokens,
                    'total_output_tokens': row.TotalOutputTokens,
                    'token_id': row.TokenID or '',
                    'model': row.Model or '',
                    'note': row.Note or '',
                }
                cursor.execute("SELECT MessageIndex, Role, Content FROM SessionMessages WHERE SessionID = ? ORDER BY MessageIndex", session_id)
                data['conversation_history'] = [{'role': m.Role, 'content': json.loads(m.Content) if m.Content else []} for m in cursor.fetchall()]

                cursor.execute("""
                    SELECT RequestTimestamp, APIKey, Model, MaxTokens, RequestPayload, ResponsePayload,
                           InputTokens, OutputTokens, CacheCreationInputTokens, CacheReadInputTokens, StopReason
                    FROM SessionAPIRequests WHERE SessionID = ? ORDER BY RequestTimestamp
                """, session_id)
                msgs = []
                for r in cursor.fetchall():
                    req = json.loads(r.RequestPayload) if r.RequestPayload else {}
                    resp = json.loads(r.ResponsePayload) if r.ResponsePayload else {}
                    msgs.append({
                        'timestamp': r.RequestTimestamp.isoformat() if r.RequestTimestamp else None,
                        'request': {'api_key': r.APIKey, 'model': r.Model, 'max_tokens': r.MaxTokens, **req},
                        'response': {
                            'usage': {'input_tokens': r.InputTokens, 'output_tokens': r.OutputTokens,
                                      'cache_creation_input_tokens': r.CacheCreationInputTokens,
                                      'cache_read_input_tokens': r.CacheReadInputTokens},
                            'stop_reason': r.StopReason, **resp,
                        },
                    })
                data['messages'] = msgs

                cursor.execute("SELECT ServerID, ServerName, ServerURL, AuthType FROM SessionServers WHERE SessionID = ?", session_id)
                servers = [{'id': s.ServerID, 'name': s.ServerName, 'url': s.ServerURL, 'auth_type': s.AuthType} for s in cursor.fetchall()]
                if servers:
                    data['servers'] = servers
                return data
        except Exception as e:
            logger.error(f"Failed to get session {session_id}: {e}")
            raise

    def save_session(self, session_data):
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                sid = session_data.get('session_id')
                ts_str = session_data.get('timestamp')
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')) if ts_str else datetime.now()

                note = session_data.get('note', '')
                token_id = session_data.get('token_id', '')
                model = session_data.get('model', '')
                cursor.execute("""
                    IF EXISTS (SELECT 1 FROM Sessions WHERE SessionID = ?)
                        UPDATE Sessions SET SessionTimestamp=?, TotalInputTokens=?, TotalOutputTokens=?, TokenID=?, Model=?, Note=? WHERE SessionID=?
                    ELSE
                        INSERT INTO Sessions (SessionID, SessionTimestamp, TotalInputTokens, TotalOutputTokens, TokenID, Model, Note) VALUES (?,?,?,?,?,?,?)
                """, sid, ts, session_data.get('total_input_tokens', 0), session_data.get('total_output_tokens', 0), token_id or None, model or None, note, sid,
                    sid, ts, session_data.get('total_input_tokens', 0), session_data.get('total_output_tokens', 0), token_id or None, model or None, note)

                for table in ('SessionMessages', 'SessionAPIRequests', 'SessionServers'):
                    cursor.execute(f"DELETE FROM {table} WHERE SessionID = ?", sid)

                for idx, msg in enumerate(session_data.get('conversation_history', [])):
                    cursor.execute("INSERT INTO SessionMessages (SessionID, MessageIndex, Role, Content) VALUES (?,?,?,?)",
                                   sid, idx, msg.get('role'), json.dumps(msg.get('content')))

                for msg in session_data.get('messages', []):
                    req = msg.get('request', {})
                    resp = msg.get('response', {})
                    usage = resp.get('usage', {})
                    msg_ts_str = msg.get('timestamp')
                    msg_ts = datetime.fromisoformat(msg_ts_str.replace('Z', '+00:00')) if msg_ts_str else ts
                    cursor.execute("""
                        INSERT INTO SessionAPIRequests (SessionID, RequestTimestamp, APIKey, Model, MaxTokens,
                            RequestPayload, ResponsePayload, InputTokens, OutputTokens,
                            CacheCreationInputTokens, CacheReadInputTokens, StopReason)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """, sid, msg_ts, req.get('api_key'), req.get('model'), req.get('max_tokens'),
                        json.dumps(req), json.dumps(resp),
                        usage.get('input_tokens', 0), usage.get('output_tokens', 0),
                        usage.get('cache_creation_input_tokens', 0), usage.get('cache_read_input_tokens', 0),
                        resp.get('stop_reason'))
                    for srv in req.get('servers', []):
                        cursor.execute("INSERT INTO SessionServers (SessionID, ServerID, ServerName, ServerURL, AuthType) VALUES (?,?,?,?,?)",
                                       sid, srv.get('id'), srv.get('name'), srv.get('url'), srv.get('auth_type'))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
            raise

    def save_comparison(self, data):
        """Save a comparison session to Comparisons + ComparisonConfigs tables."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cid = data.get('session_id')
                ts_str = data.get('timestamp')
                ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00')) if ts_str else datetime.now()
                note = data.get('note', '')
                left_sid = data.get('left_session_id', f"{cid}_left")
                right_sid = data.get('right_session_id', f"{cid}_right")

                # Upsert the comparison's own row into Sessions (for listing)
                cursor.execute("""
                    IF EXISTS (SELECT 1 FROM Sessions WHERE SessionID = ?)
                        UPDATE Sessions SET SessionTimestamp=?, Note=? WHERE SessionID=?
                    ELSE
                        INSERT INTO Sessions (SessionID, SessionTimestamp, TotalInputTokens, TotalOutputTokens, Note) VALUES (?,?,0,0,?)
                """, cid, ts, note, cid, cid, ts, note)

                # Ensure left and right session IDs exist in Sessions (FK requirement)
                for side_id in (left_sid, right_sid):
                    cursor.execute("""
                        IF NOT EXISTS (SELECT 1 FROM Sessions WHERE SessionID = ?)
                            INSERT INTO Sessions (SessionID, SessionTimestamp, TotalInputTokens, TotalOutputTokens, Note) VALUES (?,?,0,0,?)
                    """, side_id, side_id, ts, f"Side session for {cid}")

                # Upsert into Comparisons
                cursor.execute("""
                    IF EXISTS (SELECT 1 FROM Comparisons WHERE ComparisonID = ?)
                        UPDATE Comparisons SET ComparisonTimestamp=?, Note=?, LeftSessionID=?, RightSessionID=? WHERE ComparisonID=?
                    ELSE
                        INSERT INTO Comparisons (ComparisonID, ComparisonTimestamp, Note, LeftSessionID, RightSessionID) VALUES (?,?,?,?,?)
                """, cid, ts, note, left_sid, right_sid, cid, cid, ts, note, left_sid, right_sid)

                # Save left and right data+config into ComparisonConfigs
                cursor.execute("DELETE FROM ComparisonConfigs WHERE ComparisonID = ?", cid)
                for side in ('left', 'right'):
                    side_payload = {
                        'config': data.get(f'{side}_config', {}),
                        'data': data.get(f'{side}_data', {}),
                    }
                    cursor.execute(
                        "INSERT INTO ComparisonConfigs (ComparisonID, Side, ConfigJSON) VALUES (?,?,?)",
                        cid, side, json.dumps(side_payload, default=str)
                    )

                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to save comparison: {e}")
            raise

    def get_comparison(self, comparison_id):
        """Load a comparison session from Comparisons + ComparisonConfigs tables."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT ComparisonID, ComparisonTimestamp, Note, LeftSessionID, RightSessionID FROM Comparisons WHERE ComparisonID = ?", comparison_id)
                row = cursor.fetchone()
                if not row:
                    return None

                result = {
                    'session_id': row.ComparisonID,
                    'timestamp': row.ComparisonTimestamp.isoformat() if row.ComparisonTimestamp else None,
                    'note': row.Note or '',
                    'left_session_id': row.LeftSessionID,
                    'right_session_id': row.RightSessionID,
                    'type': 'comparison',
                }

                cursor.execute("SELECT Side, ConfigJSON FROM ComparisonConfigs WHERE ComparisonID = ?", comparison_id)
                for cfg_row in cursor.fetchall():
                    side = cfg_row.Side  # 'left' or 'right'
                    payload = json.loads(cfg_row.ConfigJSON) if cfg_row.ConfigJSON else {}
                    result[f'{side}_config'] = payload.get('config', {})
                    result[f'{side}_data'] = payload.get('data', {})

                return result
        except Exception as e:
            logger.error(f"Failed to get comparison {comparison_id}: {e}")
            raise

    def delete_comparison(self, comparison_id):
        """Delete a comparison and its configs."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                # Get left/right session IDs before deleting
                cursor.execute("SELECT LeftSessionID, RightSessionID FROM Comparisons WHERE ComparisonID = ?", comparison_id)
                row = cursor.fetchone()
                left_sid = row.LeftSessionID if row else None
                right_sid = row.RightSessionID if row else None
                # ComparisonConfigs deleted by CASCADE
                cursor.execute("DELETE FROM Comparisons WHERE ComparisonID = ?", comparison_id)
                # Clean up session stubs
                cursor.execute("DELETE FROM Sessions WHERE SessionID = ?", comparison_id)
                if left_sid:
                    cursor.execute("DELETE FROM Sessions WHERE SessionID = ?", left_sid)
                if right_sid:
                    cursor.execute("DELETE FROM Sessions WHERE SessionID = ?", right_sid)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to delete comparison: {e}")
            return False

    def delete_session(self, session_id):
        try:
            with self.get_connection() as conn:
                conn.cursor().execute("DELETE FROM Sessions WHERE SessionID = ?", session_id)
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to delete session: {e}")
            return False

    # ── AI TOKENS ──────────────────────────────────────────────────────

    def _ensure_tokens_table(self):
        """Create the AITokens table if it doesn't exist."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'AITokens')
                    CREATE TABLE AITokens (
                        TokenID NVARCHAR(100) PRIMARY KEY,
                        DisplayName NVARCHAR(255) NOT NULL,
                        Provider NVARCHAR(50) NOT NULL,
                        APIKey NVARCHAR(500) NOT NULL,
                        Notes NVARCHAR(500) NULL,
                        SystemPrompt NVARCHAR(MAX) NULL,
                        CreatedAt DATETIME2 DEFAULT GETDATE(),
                        UpdatedAt DATETIME2 DEFAULT GETDATE()
                    )
                """)
                # Add SystemPrompt column to existing tables that pre-date this migration
                cursor.execute("""
                    IF NOT EXISTS (
                        SELECT * FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_NAME = 'AITokens' AND COLUMN_NAME = 'SystemPrompt'
                    )
                    ALTER TABLE AITokens ADD SystemPrompt NVARCHAR(MAX) NULL
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to ensure AITokens table: {e}")

    def list_tokens(self) -> List[Dict[str, Any]]:
        """List all AI tokens (with masked keys)."""
        self._ensure_tokens_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT TokenID, DisplayName, Provider, APIKey, Notes, SystemPrompt, CreatedAt, UpdatedAt
                    FROM AITokens ORDER BY DisplayName
                """)
                tokens = []
                for row in cursor.fetchall():
                    key = row.APIKey or ''
                    # Mask key: show first 7 and last 4 chars
                    if len(key) > 12:
                        key_preview = key[:7] + '...' + key[-4:]
                    elif len(key) > 4:
                        key_preview = key[:3] + '...' + key[-2:]
                    else:
                        key_preview = '••••••••'
                    tokens.append({
                        'id': row.TokenID,
                        'name': row.DisplayName,
                        'provider': row.Provider,
                        'key_preview': key_preview,
                        'notes': row.Notes or '',
                        'system_prompt': row.SystemPrompt or '',
                        'created_at': row.CreatedAt.isoformat() if row.CreatedAt else None,
                        'updated_at': row.UpdatedAt.isoformat() if row.UpdatedAt else None,
                    })
                return tokens
        except Exception as e:
            logger.error(f"Failed to list tokens: {e}")
            raise

    def get_token(self, token_id: str) -> Optional[Dict[str, Any]]:
        """Get a single token by ID (returns full key)."""
        self._ensure_tokens_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT TokenID, DisplayName, Provider, APIKey, Notes, SystemPrompt FROM AITokens WHERE TokenID = ?", token_id)
                row = cursor.fetchone()
                if not row:
                    return None
                return {
                    'id': row.TokenID,
                    'name': row.DisplayName,
                    'provider': row.Provider,
                    'key': row.APIKey,
                    'notes': row.Notes or '',
                    'system_prompt': row.SystemPrompt or '',
                }
        except Exception as e:
            logger.error(f"Failed to get token {token_id}: {e}")
            raise

    def save_token(self, token_data: Dict[str, Any]) -> str:
        """Create or update an AI token. Returns the token ID."""
        self._ensure_tokens_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                token_id = token_data.get('id')
                if not token_id:
                    import uuid
                    token_id = f"token_{uuid.uuid4().hex[:12]}"

                name = token_data.get('name', 'Unnamed Token')
                provider = token_data.get('provider', 'other')
                key = token_data.get('key')
                notes = token_data.get('notes', '')
                system_prompt = token_data.get('system_prompt', '') or ''

                cursor.execute("SELECT 1 FROM AITokens WHERE TokenID = ?", token_id)
                exists = cursor.fetchone()

                if exists:
                    if key:
                        cursor.execute("""
                            UPDATE AITokens SET DisplayName=?, Provider=?, APIKey=?, Notes=?, SystemPrompt=?, UpdatedAt=GETDATE()
                            WHERE TokenID=?
                        """, name, provider, key, notes, system_prompt or None, token_id)
                    else:
                        cursor.execute("""
                            UPDATE AITokens SET DisplayName=?, Provider=?, Notes=?, SystemPrompt=?, UpdatedAt=GETDATE()
                            WHERE TokenID=?
                        """, name, provider, notes, system_prompt or None, token_id)
                else:
                    if not key:
                        raise ValueError("API key is required for new tokens")
                    cursor.execute("""
                        INSERT INTO AITokens (TokenID, DisplayName, Provider, APIKey, Notes, SystemPrompt)
                        VALUES (?,?,?,?,?,?)
                    """, token_id, name, provider, key, notes, system_prompt or None)

                conn.commit()
                return token_id
        except Exception as e:
            logger.error(f"Failed to save token: {e}")
            raise

    def delete_token(self, token_id: str) -> bool:
        """Delete an AI token."""
        self._ensure_tokens_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM AITokens WHERE TokenID = ?", token_id)
                deleted = cursor.rowcount > 0
                conn.commit()
                return deleted
        except Exception as e:
            logger.error(f"Failed to delete token {token_id}: {e}")
            return False

    # ── ALLOWED MODELS ─────────────────────────────────────────────────

    def _ensure_allowed_models_table(self):
        """Create the AllowedModels table if it doesn't exist."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    IF NOT EXISTS (SELECT * FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'AllowedModels')
                    CREATE TABLE AllowedModels (
                        AllowedModelID INT IDENTITY(1,1) PRIMARY KEY,
                        TokenID NVARCHAR(100) NOT NULL,
                        ModelID NVARCHAR(200) NOT NULL,
                        DisplayName NVARCHAR(255) NOT NULL,
                        Provider NVARCHAR(50) NOT NULL,
                        ContextWindow INT NULL,
                        InputPrice DECIMAL(10,4) NULL,
                        OutputPrice DECIMAL(10,4) NULL,
                        Enabled BIT DEFAULT 1,
                        CreatedDate DATETIME2 DEFAULT GETDATE(),
                        CONSTRAINT UQ_AllowedModels_Token_Model UNIQUE (TokenID, ModelID)
                    )
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to ensure AllowedModels table: {e}")

    def list_allowed_models(self, token_id: str = None, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """List allowed models, optionally filtered by token or enabled status."""
        self._ensure_allowed_models_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                query = """
                    SELECT am.AllowedModelID, am.TokenID, am.ModelID, am.DisplayName,
                           am.Provider, am.ContextWindow, am.InputPrice, am.OutputPrice,
                           am.Enabled, am.CreatedDate, t.DisplayName AS TokenName
                    FROM AllowedModels am
                    LEFT JOIN AITokens t ON am.TokenID = t.TokenID
                """
                conditions = []
                params = []
                if token_id:
                    conditions.append("am.TokenID = ?")
                    params.append(token_id)
                if enabled_only:
                    conditions.append("am.Enabled = 1")
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                query += " ORDER BY am.Provider, am.DisplayName"
                cursor.execute(query, *params)
                models = []
                for row in cursor.fetchall():
                    models.append({
                        'id': row.AllowedModelID,
                        'token_id': row.TokenID,
                        'model_id': row.ModelID,
                        'display_name': row.DisplayName,
                        'provider': row.Provider,
                        'context_window': row.ContextWindow,
                        'input_price': float(row.InputPrice) if row.InputPrice else None,
                        'output_price': float(row.OutputPrice) if row.OutputPrice else None,
                        'enabled': bool(row.Enabled),
                        'token_name': row.TokenName or '',
                    })
                return models
        except Exception as e:
            logger.error(f"Failed to list allowed models: {e}")
            raise

    def save_allowed_models(self, token_id: str, models: List[Dict[str, Any]]) -> int:
        """Save allowed models for a token. Upserts by TokenID+ModelID."""
        self._ensure_allowed_models_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                saved = 0
                for m in models:
                    model_id = m.get('model_id', '')
                    display_name = m.get('display_name', model_id)
                    provider = m.get('provider', '')
                    context_window = m.get('context_window')
                    input_price = m.get('input_price')
                    output_price = m.get('output_price')
                    enabled = 1 if m.get('enabled', True) else 0

                    cursor.execute("""
                        IF EXISTS (SELECT 1 FROM AllowedModels WHERE TokenID = ? AND ModelID = ?)
                            UPDATE AllowedModels SET DisplayName=?, Provider=?, ContextWindow=?,
                                   InputPrice=?, OutputPrice=?, Enabled=?
                            WHERE TokenID=? AND ModelID=?
                        ELSE
                            INSERT INTO AllowedModels (TokenID, ModelID, DisplayName, Provider, ContextWindow, InputPrice, OutputPrice, Enabled)
                            VALUES (?,?,?,?,?,?,?,?)
                    """, token_id, model_id,
                        display_name, provider, context_window, input_price, output_price, enabled, token_id, model_id,
                        token_id, model_id, display_name, provider, context_window, input_price, output_price, enabled)
                    saved += 1
                conn.commit()
                return saved
        except Exception as e:
            logger.error(f"Failed to save allowed models: {e}")
            raise

    def toggle_allowed_model(self, allowed_model_id: int, enabled: bool) -> bool:
        """Toggle the enabled state of an allowed model."""
        self._ensure_allowed_models_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE AllowedModels SET Enabled = ? WHERE AllowedModelID = ?",
                               1 if enabled else 0, allowed_model_id)
                updated = cursor.rowcount > 0
                conn.commit()
                return updated
        except Exception as e:
            logger.error(f"Failed to toggle allowed model {allowed_model_id}: {e}")
            return False

    def delete_allowed_model(self, allowed_model_id: int) -> bool:
        """Delete an allowed model entry."""
        self._ensure_allowed_models_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM AllowedModels WHERE AllowedModelID = ?", allowed_model_id)
                deleted = cursor.rowcount > 0
                conn.commit()
                return deleted
        except Exception as e:
            logger.error(f"Failed to delete allowed model {allowed_model_id}: {e}")
            return False

    def delete_allowed_models_for_token(self, token_id: str) -> int:
        """Delete all allowed models for a token."""
        self._ensure_allowed_models_table()
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM AllowedModels WHERE TokenID = ?", token_id)
                count = cursor.rowcount
                conn.commit()
                return count
        except Exception as e:
            logger.error(f"Failed to delete allowed models for token {token_id}: {e}")
            return 0

    def update_model_cost(self, allowed_model_id: int, updates: dict) -> bool:
        """Update input/output pricing for an allowed model.
        updates dict may contain 'input_price' and/or 'output_price' keys."""
        self._ensure_allowed_models_table()
        col_map = {'input_price': 'InputPrice', 'output_price': 'OutputPrice'}
        parts = []
        vals = []
        for key, col in col_map.items():
            if key in updates:
                parts.append(f"{col} = ?")
                vals.append(updates[key])
        if not parts:
            return False
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()
                vals.append(allowed_model_id)
                sql = f"UPDATE AllowedModels SET {', '.join(parts)} WHERE AllowedModelID = ?"
                cursor.execute(sql, *vals)
                updated = cursor.rowcount > 0
                conn.commit()
                return updated
        except Exception as e:
            logger.error(f"Failed to update model cost {allowed_model_id}: {e}")
            return False

    # ── USAGE STATS ────────────────────────────────────────────────────

    def get_usage_stats(self, start_date: str = None, end_date: str = None,
                        token_id: str = None, model: str = None,
                        server_id: str = None) -> Dict[str, Any]:
        """Get usage statistics from SessionAPIRequests for charts."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Helper: optional SessionServers join fragment
                server_join = ""
                if server_id:
                    server_join = " JOIN SessionServers ss ON r.SessionID = ss.SessionID"

                # Daily usage
                daily_query = f"""
                    SELECT CAST(r.RequestTimestamp AS DATE) AS UsageDate,
                           COUNT(*) AS RequestCount,
                           SUM(r.InputTokens) AS TotalInput,
                           SUM(r.OutputTokens) AS TotalOutput,
                           SUM(r.CacheCreationInputTokens) AS TotalCacheCreation,
                           SUM(r.CacheReadInputTokens) AS TotalCacheRead
                    FROM SessionAPIRequests r
                    JOIN Sessions s ON r.SessionID = s.SessionID
                    {server_join}
                    WHERE 1=1
                """
                params = []
                if server_id:
                    daily_query += " AND ss.ServerID = ?"
                    params.append(server_id)
                if start_date:
                    daily_query += " AND CAST(r.RequestTimestamp AS DATE) >= ?"
                    params.append(start_date)
                if end_date:
                    daily_query += " AND CAST(r.RequestTimestamp AS DATE) <= ?"
                    params.append(end_date)
                if token_id:
                    daily_query += " AND s.TokenID = ?"
                    params.append(token_id)
                if model:
                    daily_query += " AND r.Model = ?"
                    params.append(model)
                daily_query += " GROUP BY CAST(r.RequestTimestamp AS DATE) ORDER BY UsageDate"
                cursor.execute(daily_query, *params)
                daily = []
                for row in cursor.fetchall():
                    daily.append({
                        'date': row.UsageDate.isoformat() if row.UsageDate else None,
                        'requests': row.RequestCount,
                        'input_tokens': row.TotalInput or 0,
                        'output_tokens': row.TotalOutput or 0,
                        'cache_creation': row.TotalCacheCreation or 0,
                        'cache_read': row.TotalCacheRead or 0,
                    })

                # By model
                model_query = f"""
                    SELECT r.Model,
                           COUNT(*) AS RequestCount,
                           SUM(r.InputTokens) AS TotalInput,
                           SUM(r.OutputTokens) AS TotalOutput,
                           SUM(r.CacheCreationInputTokens) AS TotalCacheCreation,
                           SUM(r.CacheReadInputTokens) AS TotalCacheRead
                    FROM SessionAPIRequests r
                    JOIN Sessions s ON r.SessionID = s.SessionID
                    {server_join}
                    WHERE r.Model IS NOT NULL
                """
                params2 = []
                if server_id:
                    model_query += " AND ss.ServerID = ?"
                    params2.append(server_id)
                if start_date:
                    model_query += " AND CAST(r.RequestTimestamp AS DATE) >= ?"
                    params2.append(start_date)
                if end_date:
                    model_query += " AND CAST(r.RequestTimestamp AS DATE) <= ?"
                    params2.append(end_date)
                if token_id:
                    model_query += " AND s.TokenID = ?"
                    params2.append(token_id)
                model_query += " GROUP BY r.Model ORDER BY TotalInput DESC"
                cursor.execute(model_query, *params2)
                by_model = []
                for row in cursor.fetchall():
                    by_model.append({
                        'model': row.Model,
                        'requests': row.RequestCount,
                        'input_tokens': row.TotalInput or 0,
                        'output_tokens': row.TotalOutput or 0,
                        'cache_creation': row.TotalCacheCreation or 0,
                        'cache_read': row.TotalCacheRead or 0,
                    })

                # Daily by model (for cost calculation)
                daily_model_query = f"""
                    SELECT CAST(r.RequestTimestamp AS DATE) AS UsageDate,
                           r.Model,
                           SUM(r.InputTokens) AS TotalInput,
                           SUM(r.OutputTokens) AS TotalOutput,
                           SUM(r.CacheCreationInputTokens) AS TotalCacheCreation,
                           SUM(r.CacheReadInputTokens) AS TotalCacheRead
                    FROM SessionAPIRequests r
                    JOIN Sessions s ON r.SessionID = s.SessionID
                    {server_join}
                    WHERE r.Model IS NOT NULL
                """
                params4 = []
                if server_id:
                    daily_model_query += " AND ss.ServerID = ?"
                    params4.append(server_id)
                if start_date:
                    daily_model_query += " AND CAST(r.RequestTimestamp AS DATE) >= ?"
                    params4.append(start_date)
                if end_date:
                    daily_model_query += " AND CAST(r.RequestTimestamp AS DATE) <= ?"
                    params4.append(end_date)
                if token_id:
                    daily_model_query += " AND s.TokenID = ?"
                    params4.append(token_id)
                if model:
                    daily_model_query += " AND r.Model = ?"
                    params4.append(model)
                daily_model_query += " GROUP BY CAST(r.RequestTimestamp AS DATE), r.Model ORDER BY UsageDate"
                cursor.execute(daily_model_query, *params4)
                daily_by_model = []
                for row in cursor.fetchall():
                    daily_by_model.append({
                        'date': row.UsageDate.isoformat() if row.UsageDate else None,
                        'model': row.Model,
                        'input_tokens': row.TotalInput or 0,
                        'output_tokens': row.TotalOutput or 0,
                        'cache_creation': row.TotalCacheCreation or 0,
                        'cache_read': row.TotalCacheRead or 0,
                    })

                # Totals
                totals_query = f"""
                    SELECT COUNT(*) AS TotalRequests,
                           COUNT(DISTINCT r.SessionID) AS TotalSessions,
                           SUM(r.InputTokens) AS TotalInput,
                           SUM(r.OutputTokens) AS TotalOutput,
                           SUM(r.CacheCreationInputTokens) AS TotalCacheCreation,
                           SUM(r.CacheReadInputTokens) AS TotalCacheRead
                    FROM SessionAPIRequests r
                    JOIN Sessions s ON r.SessionID = s.SessionID
                    {server_join}
                    WHERE 1=1
                """
                params3 = []
                if server_id:
                    totals_query += " AND ss.ServerID = ?"
                    params3.append(server_id)
                if start_date:
                    totals_query += " AND CAST(r.RequestTimestamp AS DATE) >= ?"
                    params3.append(start_date)
                if end_date:
                    totals_query += " AND CAST(r.RequestTimestamp AS DATE) <= ?"
                    params3.append(end_date)
                if token_id:
                    totals_query += " AND s.TokenID = ?"
                    params3.append(token_id)
                if model:
                    totals_query += " AND r.Model = ?"
                    params3.append(model)
                cursor.execute(totals_query, *params3)
                row = cursor.fetchone()
                totals = {
                    'total_requests': row.TotalRequests or 0,
                    'total_sessions': row.TotalSessions or 0,
                    'total_input': row.TotalInput or 0,
                    'total_output': row.TotalOutput or 0,
                    'total_cache_creation': row.TotalCacheCreation or 0,
                    'total_cache_read': row.TotalCacheRead or 0,
                }

                return {
                    'daily': daily,
                    'by_model': by_model,
                    'daily_by_model': daily_by_model,
                    'totals': totals,
                }
        except Exception as e:
            logger.error(f"Failed to get usage stats: {e}")
            raise


_db_manager = None


def get_db_manager(config_path: str = "config.json") -> DatabaseManager:
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager(config_path)
    return _db_manager
