"""
MCP and Session Data Migration Tool
Migrates data from JSON files to SQL Server database
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

import pyodbc

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('migration.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def load_config(config_path: str = "config.json") -> Dict[str, Any]:
    """Load configuration from config.json"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"ERROR: Config file not found: {config_path}")
        print("Please create config.json with sql_server settings.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in config file: {e}")
        sys.exit(1)


def build_connection_string(config: Dict[str, Any]) -> str:
    """Build SQL Server connection string from config"""
    sql_config = config.get('sql_server', {})

    server = sql_config.get('server', 'localhost')
    database = sql_config.get('database', 'MCPTokenUsage')
    driver = sql_config.get('driver', 'ODBC Driver 17 for SQL Server')
    use_windows_auth = sql_config.get('use_windows_auth', True)

    if use_windows_auth:
        return f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"
    else:
        username = sql_config.get('username', '')
        password = sql_config.get('password', '')
        if not username or not password:
            print("ERROR: SQL Server username and password required when use_windows_auth is false")
            sys.exit(1)
        return f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};UID={username};PWD={password}"


class SQLServerMigration:
    """Handles migration of JSON data to SQL Server"""

    def __init__(self, connection_string: str):
        """
        Initialize migration tool

        Args:
            connection_string: SQL Server connection string
        """
        self.connection_string = connection_string
        self.conn = None
        self.cursor = None

    def connect(self):
        """Establish database connection"""
        try:
            self.conn = pyodbc.connect(self.connection_string)
            self.cursor = self.conn.cursor()
            logger.info("Connected to SQL Server successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to SQL Server: {e}")
            return False

    def disconnect(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Disconnected from SQL Server")

    def migrate_mcp_credentials(self, credentials_file: str) -> bool:
        """
        Migrate MCP server credentials from JSON file

        Args:
            credentials_file: Path to mcp_credentials.json.backup

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Loading credentials from {credentials_file}")
            with open(credentials_file, 'r', encoding='utf-8') as f:
                credentials = json.load(f)

            server_count = 0
            for server_id, server_data in credentials.items():
                try:
                    self._migrate_server(server_id, server_data)
                    server_count += 1
                except Exception as e:
                    logger.error(f"Failed to migrate server {server_id}: {e}")
                    # Continue with other servers

            self.conn.commit()
            logger.info(f"Successfully migrated {server_count} MCP servers")
            return True

        except Exception as e:
            logger.error(f"Failed to migrate credentials: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def _migrate_server(self, server_id: str, server_data: Dict[str, Any]):
        """Migrate a single MCP server configuration"""
        logger.info(f"Migrating server: {server_id} ({server_data.get('name', 'Unknown')})")

        # Insert server record
        auth_method = server_data.get('auth_method') or server_data.get('auth_type', 'bearer_token')
        last_validated = server_data.get('lastValidated')
        if last_validated:
            last_validated = datetime.fromisoformat(last_validated.replace('Z', '+00:00'))

        self.cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM MCPServers WHERE ServerID = ?)
            INSERT INTO MCPServers (ServerID, ServerName, URL, AuthMethod, Enabled, Collapsed, LastValidated)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ELSE
            UPDATE MCPServers
            SET ServerName = ?, URL = ?, AuthMethod = ?, Enabled = ?, Collapsed = ?, LastValidated = ?, ModifiedDate = GETDATE()
            WHERE ServerID = ?
        """, server_id, server_id, server_data.get('name', 'Unknown'),
            server_data.get('url', ''), auth_method,
            server_data.get('enabled', True), server_data.get('collapsed', False),
            last_validated,
            server_data.get('name', 'Unknown'), server_data.get('url', ''),
            auth_method, server_data.get('enabled', True), server_data.get('collapsed', False),
            last_validated, server_id)

        # Insert auth record
        self._migrate_server_auth(server_id, server_data)

        # Insert headers
        headers = server_data.get('headers', {})
        if headers:
            self._migrate_server_headers(server_id, headers)

        # Insert prompts
        prompts = server_data.get('prompts', [])
        if prompts:
            self._migrate_server_prompts(server_id, prompts)

        # Insert tools
        tools = server_data.get('tools', [])
        if tools:
            self._migrate_server_tools(server_id, tools)

        logger.info(f"  - Migrated {len(headers)} headers, {len(prompts)} prompts, {len(tools)} tools")

    def _migrate_server_auth(self, server_id: str, server_data: Dict[str, Any]):
        """Migrate server authentication data"""
        auth_method = server_data.get('auth_method') or server_data.get('auth_type', 'bearer_token')

        # Delete existing auth records
        self.cursor.execute("DELETE FROM MCPServerAuth WHERE ServerID = ?", server_id)

        self.cursor.execute("""
            INSERT INTO MCPServerAuth (
                ServerID, AuthType, Token, TokenParamName,
                ClientID, ClientSecret, AuthorizationEndpoint, TokenEndpoint,
                RedirectURI, RefreshToken, AccessToken, TokenExpiresAt, TokenObtainedAt,
                Scopes, Resource, PKCECodeVerifier
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            server_id,
            auth_method,
            server_data.get('token') or server_data.get('auth_token'),
            server_data.get('token_param_name'),
            server_data.get('client_id'),
            server_data.get('client_secret'),
            server_data.get('authorization_endpoint'),
            server_data.get('token_endpoint'),
            server_data.get('redirect_uri'),
            server_data.get('refresh_token'),
            server_data.get('access_token'),
            server_data.get('token_expires_at'),
            server_data.get('token_obtained_at'),
            server_data.get('scopes'),
            server_data.get('resource'),
            server_data.get('pkce_code_verifier')
        )

    def _migrate_server_headers(self, server_id: str, headers: Dict[str, str]):
        """Migrate server custom headers"""
        # Delete existing headers
        self.cursor.execute("DELETE FROM MCPServerHeaders WHERE ServerID = ?", server_id)

        for header_name, header_value in headers.items():
            self.cursor.execute("""
                INSERT INTO MCPServerHeaders (ServerID, HeaderName, HeaderValue)
                VALUES (?, ?, ?)
            """, server_id, header_name, header_value)

    def _migrate_server_prompts(self, server_id: str, prompts: List[Dict[str, Any]]):
        """Migrate server prompts and their arguments"""
        # Delete existing prompts (cascade will delete arguments)
        self.cursor.execute("DELETE FROM MCPServerPrompts WHERE ServerID = ?", server_id)

        for prompt in prompts:
            self.cursor.execute("""
                INSERT INTO MCPServerPrompts (ServerID, PromptName, PromptTitle, Description)
                OUTPUT INSERTED.PromptID
                VALUES (?, ?, ?, ?)
            """, server_id, prompt.get('name'), prompt.get('title'), prompt.get('description'))

            prompt_id = self.cursor.fetchone()[0]

            # Insert prompt arguments
            arguments = prompt.get('arguments', [])
            for arg in arguments:
                self.cursor.execute("""
                    INSERT INTO MCPServerPromptArguments (
                        PromptID, ArgumentName, ArgumentTitle, Description, Required
                    ) VALUES (?, ?, ?, ?, ?)
                """, prompt_id, arg.get('name'), arg.get('title'),
                    arg.get('description'), arg.get('required', False))

    def _migrate_server_tools(self, server_id: str, tools: List[Dict[str, Any]]):
        """Migrate server tools and their annotations"""
        # Delete existing tools (cascade will delete annotations)
        self.cursor.execute("DELETE FROM MCPServerTools WHERE ServerID = ?", server_id)

        for tool in tools:
            # Convert schema dicts to JSON strings
            input_schema = json.dumps(tool.get('inputSchema')) if tool.get('inputSchema') else None
            output_schema = json.dumps(tool.get('outputSchema')) if tool.get('outputSchema') else None

            self.cursor.execute("""
                INSERT INTO MCPServerTools (
                    ServerID, ToolName, ToolTitle, Description, InputSchema, OutputSchema
                )
                OUTPUT INSERTED.ToolID
                VALUES (?, ?, ?, ?, ?, ?)
            """, server_id, tool.get('name'), tool.get('title'),
                tool.get('description'), input_schema, output_schema)

            tool_id = self.cursor.fetchone()[0]

            # Insert tool annotations
            annotations = tool.get('annotations', {})
            for key, value in annotations.items():
                self.cursor.execute("""
                    INSERT INTO MCPServerToolAnnotations (ToolID, AnnotationKey, AnnotationValue)
                    VALUES (?, ?, ?)
                """, tool_id, key, str(value))

    def migrate_sessions(self, sessions_dir: str) -> bool:
        """
        Migrate all session files from directory

        Args:
            sessions_dir: Path to sessions directory

        Returns:
            True if successful, False otherwise
        """
        try:
            sessions_path = Path(sessions_dir)
            session_files = list(sessions_path.glob('session_*.json'))

            logger.info(f"Found {len(session_files)} session files to migrate")

            success_count = 0
            for session_file in session_files:
                try:
                    self._migrate_session(str(session_file))
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to migrate {session_file.name}: {e}")
                    # Continue with other sessions

            self.conn.commit()
            logger.info(f"Successfully migrated {success_count}/{len(session_files)} sessions")
            return True

        except Exception as e:
            logger.error(f"Failed to migrate sessions: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def _migrate_session(self, session_file: str):
        """Migrate a single session file"""
        with open(session_file, 'r', encoding='utf-8') as f:
            session_data = json.load(f)

        session_id = session_data.get('session_id')
        logger.info(f"Migrating session: {session_id}")

        # Parse timestamp
        timestamp_str = session_data.get('timestamp')
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')) if timestamp_str else datetime.now()

        # Insert session record
        self.cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM Sessions WHERE SessionID = ?)
            INSERT INTO Sessions (SessionID, SessionTimestamp, TotalInputTokens, TotalOutputTokens)
            VALUES (?, ?, ?, ?)
            ELSE
            UPDATE Sessions
            SET SessionTimestamp = ?, TotalInputTokens = ?, TotalOutputTokens = ?
            WHERE SessionID = ?
        """, session_id, session_id, timestamp,
            session_data.get('total_input_tokens', 0),
            session_data.get('total_output_tokens', 0),
            timestamp, session_data.get('total_input_tokens', 0),
            session_data.get('total_output_tokens', 0), session_id)

        # Delete existing related records
        self.cursor.execute("DELETE FROM SessionMessages WHERE SessionID = ?", session_id)
        self.cursor.execute("DELETE FROM SessionServers WHERE SessionID = ?", session_id)
        self.cursor.execute("DELETE FROM SessionAPIRequests WHERE SessionID = ?", session_id)

        # Insert conversation messages
        conversation_history = session_data.get('conversation_history', [])
        for idx, message in enumerate(conversation_history):
            content_json = json.dumps(message.get('content'))
            self.cursor.execute("""
                INSERT INTO SessionMessages (SessionID, MessageIndex, Role, Content)
                OUTPUT INSERTED.MessageID
                VALUES (?, ?, ?, ?)
            """, session_id, idx, message.get('role'), content_json)

        # Insert API request/response records
        messages = session_data.get('messages', [])
        for message in messages:
            request = message.get('request', {})
            response = message.get('response', {})

            msg_timestamp_str = message.get('timestamp')
            msg_timestamp = datetime.fromisoformat(msg_timestamp_str.replace('Z', '+00:00')) if msg_timestamp_str else timestamp

            usage = response.get('usage', {})

            self.cursor.execute("""
                INSERT INTO SessionAPIRequests (
                    SessionID, RequestTimestamp, APIKey, Model, MaxTokens,
                    RequestPayload, ResponsePayload,
                    InputTokens, OutputTokens, CacheCreationInputTokens, CacheReadInputTokens,
                    StopReason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                session_id, msg_timestamp,
                request.get('api_key'), request.get('model'), request.get('max_tokens'),
                json.dumps(request), json.dumps(response),
                usage.get('input_tokens', 0), usage.get('output_tokens', 0),
                usage.get('cache_creation_input_tokens', 0), usage.get('cache_read_input_tokens', 0),
                response.get('stop_reason')
            )

            # Insert servers used in this request
            servers = request.get('servers', [])
            for server in servers:
                self.cursor.execute("""
                    INSERT INTO SessionServers (SessionID, ServerID, ServerName, ServerURL, AuthType)
                    VALUES (?, ?, ?, ?, ?)
                """, session_id, server.get('id'), server.get('name'),
                    server.get('url'), server.get('auth_type'))

    def migrate_comparisons(self, sessions_dir: str) -> bool:
        """
        Migrate all comparison files from directory

        Args:
            sessions_dir: Path to sessions directory

        Returns:
            True if successful, False otherwise
        """
        try:
            sessions_path = Path(sessions_dir)
            comparison_files = [f for f in sessions_path.glob('comparison_*.json')
                              if not ('_left' in f.name or '_right' in f.name)]

            logger.info(f"Found {len(comparison_files)} comparison files to migrate")

            success_count = 0
            for comparison_file in comparison_files:
                try:
                    self._migrate_comparison(str(comparison_file), str(sessions_path))
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to migrate {comparison_file.name}: {e}")
                    # Continue with other comparisons

            self.conn.commit()
            logger.info(f"Successfully migrated {success_count}/{len(comparison_files)} comparisons")
            return True

        except Exception as e:
            logger.error(f"Failed to migrate comparisons: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    def _migrate_comparison(self, comparison_file: str, sessions_dir: str):
        """Migrate a single comparison and its left/right sessions"""
        with open(comparison_file, 'r', encoding='utf-8') as f:
            comparison_data = json.load(f)

        comparison_id = comparison_data.get('session_id')
        logger.info(f"Migrating comparison: {comparison_id}")

        # Parse timestamp
        timestamp_str = comparison_data.get('timestamp')
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')) if timestamp_str else datetime.now()

        left_session_id = comparison_data.get('left_session_id')
        right_session_id = comparison_data.get('right_session_id')

        # Migrate left and right sessions first
        left_file = os.path.join(sessions_dir, f"{left_session_id}.json")
        right_file = os.path.join(sessions_dir, f"{right_session_id}.json")

        if os.path.exists(left_file):
            self._migrate_session(left_file)
        else:
            logger.warning(f"Left session file not found: {left_file}")

        if os.path.exists(right_file):
            self._migrate_session(right_file)
        else:
            logger.warning(f"Right session file not found: {right_file}")

        # Insert comparison record
        self.cursor.execute("""
            IF NOT EXISTS (SELECT 1 FROM Comparisons WHERE ComparisonID = ?)
            INSERT INTO Comparisons (ComparisonID, ComparisonTimestamp, Note, LeftSessionID, RightSessionID)
            VALUES (?, ?, ?, ?, ?)
            ELSE
            UPDATE Comparisons
            SET ComparisonTimestamp = ?, Note = ?, LeftSessionID = ?, RightSessionID = ?
            WHERE ComparisonID = ?
        """, comparison_id, comparison_id, timestamp, comparison_data.get('note', ''),
            left_session_id, right_session_id,
            timestamp, comparison_data.get('note', ''),
            left_session_id, right_session_id, comparison_id)

        # Delete existing configs
        self.cursor.execute("DELETE FROM ComparisonConfigs WHERE ComparisonID = ?", comparison_id)

        # Insert left config
        left_config = comparison_data.get('left_config', {})
        if left_config:
            self.cursor.execute("""
                INSERT INTO ComparisonConfigs (ComparisonID, Side, ConfigJSON)
                VALUES (?, 'left', ?)
            """, comparison_id, json.dumps(left_config))

        # Insert right config
        right_config = comparison_data.get('right_config', {})
        if right_config:
            self.cursor.execute("""
                INSERT INTO ComparisonConfigs (ComparisonID, Side, ConfigJSON)
                VALUES (?, 'right', ?)
            """, comparison_id, json.dumps(right_config))


def main():
    """Main migration script"""
    print("=" * 70)
    print("MCP and Session Data Migration Tool")
    print("=" * 70)
    print()

    # Load configuration from config.json
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.json')

    logger.info(f"Loading configuration from {config_path}")
    config = load_config(config_path)
    connection_string = build_connection_string(config)

    sql_config = config.get('sql_server', {})
    logger.info(f"SQL Server: {sql_config.get('server', 'localhost')}")
    logger.info(f"Database: {sql_config.get('database', 'MCPTokenUsage')}")
    logger.info(f"Authentication: {'Windows Auth' if sql_config.get('use_windows_auth', True) else 'SQL Auth'}")

    # Get file paths
    credentials_file = os.path.join(script_dir, 'mcp_credentials.json.backup')
    sessions_dir = os.path.join(script_dir, 'sessions')

    print()
    print(f"Credentials file: {credentials_file}")
    print(f"Sessions directory: {sessions_dir}")
    print()

    # Verify files exist
    if not os.path.exists(credentials_file):
        logger.error(f"Credentials file not found: {credentials_file}")
        return 1

    if not os.path.exists(sessions_dir):
        logger.error(f"Sessions directory not found: {sessions_dir}")
        return 1

    # Confirm before proceeding
    response = input("Proceed with migration? (y/n): ").strip().lower()
    if response != 'y':
        print("Migration cancelled.")
        return 0

    print()
    logger.info("Starting migration...")

    # Create migration instance
    migration = SQLServerMigration(connection_string)

    try:
        # Connect to database
        if not migration.connect():
            logger.error("Failed to connect to database. Exiting.")
            return 1

        # Migrate MCP credentials
        logger.info("=" * 50)
        logger.info("Step 1: Migrating MCP server credentials")
        logger.info("=" * 50)
        if not migration.migrate_mcp_credentials(credentials_file):
            logger.error("Failed to migrate credentials")
            return 1

        # Migrate sessions
        logger.info("")
        logger.info("=" * 50)
        logger.info("Step 2: Migrating sessions")
        logger.info("=" * 50)
        if not migration.migrate_sessions(sessions_dir):
            logger.error("Failed to migrate sessions")
            return 1

        # Migrate comparisons
        logger.info("")
        logger.info("=" * 50)
        logger.info("Step 3: Migrating comparisons")
        logger.info("=" * 50)
        if not migration.migrate_comparisons(sessions_dir):
            logger.error("Failed to migrate comparisons")
            return 1

        logger.info("")
        logger.info("=" * 50)
        logger.info("Migration completed successfully!")
        logger.info("=" * 50)

        return 0

    except Exception as e:
        logger.error(f"Migration failed with error: {e}")
        return 1

    finally:
        migration.disconnect()


if __name__ == "__main__":
    sys.exit(main())
