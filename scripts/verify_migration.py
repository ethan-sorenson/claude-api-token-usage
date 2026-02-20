"""
Verification Script for SQL Migration
Tests the migration and generates summary reports
"""

import json
import os
import pyodbc
import sys
from datetime import datetime
from typing import Dict, Any


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


def connect_to_db(connection_string):
    """Connect to SQL Server"""
    try:
        conn = pyodbc.connect(connection_string)
        return conn
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}")
        return None


def run_verification(conn):
    """Run verification queries"""
    cursor = conn.cursor()

    print("\n" + "=" * 70)
    print("MIGRATION VERIFICATION REPORT")
    print("=" * 70)
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 1. Count migrated records
    print("-" * 70)
    print("1. RECORD COUNTS")
    print("-" * 70)

    queries = {
        "MCP Servers": "SELECT COUNT(*) FROM MCPServers",
        "Server Auth Records": "SELECT COUNT(*) FROM MCPServerAuth",
        "Server Headers": "SELECT COUNT(*) FROM MCPServerHeaders",
        "Server Prompts": "SELECT COUNT(*) FROM MCPServerPrompts",
        "Server Tools": "SELECT COUNT(*) FROM MCPServerTools",
        "Sessions": "SELECT COUNT(*) FROM Sessions",
        "Session Messages": "SELECT COUNT(*) FROM SessionMessages",
        "API Requests": "SELECT COUNT(*) FROM SessionAPIRequests",
        "Comparisons": "SELECT COUNT(*) FROM Comparisons",
    }

    for label, query in queries.items():
        cursor.execute(query)
        count = cursor.fetchone()[0]
        print(f"  {label:.<50} {count:>6}")

    # 2. Server summary
    print()
    print("-" * 70)
    print("2. MCP SERVER SUMMARY")
    print("-" * 70)

    cursor.execute("""
        SELECT ServerName, AuthMethod, Enabled,
               (SELECT COUNT(*) FROM MCPServerTools WHERE ServerID = s.ServerID) AS ToolCount
        FROM MCPServers s
        ORDER BY ServerName
    """)

    for row in cursor.fetchall():
        enabled = "✓" if row[2] else "✗"
        print(f"  [{enabled}] {row[0]:.<40} {row[1]:>15} ({row[3]} tools)")

    # 3. Token usage summary
    print()
    print("-" * 70)
    print("3. TOKEN USAGE SUMMARY")
    print("-" * 70)

    cursor.execute("""
        SELECT
            COUNT(*) AS SessionCount,
            SUM(TotalInputTokens) AS TotalInput,
            SUM(TotalOutputTokens) AS TotalOutput,
            SUM(TotalTokens) AS TotalTokens,
            AVG(TotalTokens) AS AvgTokens
        FROM Sessions
    """)

    row = cursor.fetchone()
    if row and row[0] > 0:
        print(f"  Total Sessions: {row[0]:,}")
        print(f"  Total Input Tokens: {row[1]:,}")
        print(f"  Total Output Tokens: {row[2]:,}")
        print(f"  Total Tokens: {row[3]:,}")
        print(f"  Average Tokens per Session: {int(row[4]):,}")

        # Calculate estimated cost (Claude 3.5 Sonnet pricing)
        input_cost = (row[1] * 3.0 / 1_000_000) if row[1] else 0
        output_cost = (row[2] * 15.0 / 1_000_000) if row[2] else 0
        total_cost = input_cost + output_cost
        print(f"  Estimated Total Cost (Sonnet 3.5): ${total_cost:.2f}")
    else:
        print("  No session data found")

    # 4. Recent activity
    print()
    print("-" * 70)
    print("4. RECENT ACTIVITY (Last 10 Sessions)")
    print("-" * 70)

    cursor.execute("""
        SELECT TOP 10
            SessionID,
            SessionTimestamp,
            TotalTokens
        FROM Sessions
        ORDER BY SessionTimestamp DESC
    """)

    for row in cursor.fetchall():
        timestamp = row[1].strftime('%Y-%m-%d %H:%M:%S') if row[1] else 'N/A'
        print(f"  {row[0]:.<35} {timestamp} ({row[2]:,} tokens)")

    # 5. Server usage in sessions
    print()
    print("-" * 70)
    print("5. SERVER USAGE IN SESSIONS")
    print("-" * 70)

    cursor.execute("""
        SELECT
            ss.ServerName,
            COUNT(DISTINCT s.SessionID) AS SessionCount,
            SUM(s.TotalTokens) AS TotalTokens
        FROM Sessions s
        INNER JOIN SessionServers ss ON s.SessionID = ss.SessionID
        GROUP BY ss.ServerName
        ORDER BY TotalTokens DESC
    """)

    rows = cursor.fetchall()
    if rows:
        for row in rows:
            print(f"  {row[0]:.<40} {row[1]:>6} sessions, {row[2]:>10,} tokens")
    else:
        print("  No server usage data found")

    # 6. Comparison summary
    print()
    print("-" * 70)
    print("6. COMPARISON SUMMARY")
    print("-" * 70)

    cursor.execute("""
        SELECT COUNT(*) FROM Comparisons
    """)

    comparison_count = cursor.fetchone()[0]
    print(f"  Total Comparisons: {comparison_count}")

    if comparison_count > 0:
        cursor.execute("""
            SELECT TOP 5
                c.ComparisonID,
                c.ComparisonTimestamp,
                ls.TotalTokens AS LeftTokens,
                rs.TotalTokens AS RightTokens,
                ABS(ls.TotalTokens - rs.TotalTokens) AS Difference
            FROM Comparisons c
            LEFT JOIN Sessions ls ON c.LeftSessionID = ls.SessionID
            LEFT JOIN Sessions rs ON c.RightSessionID = rs.SessionID
            ORDER BY c.ComparisonTimestamp DESC
        """)

        print("  Recent Comparisons:")
        for row in cursor.fetchall():
            timestamp = row[1].strftime('%Y-%m-%d %H:%M:%S') if row[1] else 'N/A'
            left = row[2] or 0
            right = row[3] or 0
            diff = row[4] or 0
            print(f"    {timestamp}: {left:,} vs {right:,} tokens (diff: {diff:,})")

    # 7. Data integrity checks
    print()
    print("-" * 70)
    print("7. DATA INTEGRITY CHECKS")
    print("-" * 70)

    checks = []

    # Check for sessions without messages
    cursor.execute("""
        SELECT COUNT(*) FROM Sessions s
        WHERE NOT EXISTS (SELECT 1 FROM SessionMessages m WHERE m.SessionID = s.SessionID)
    """)
    sessions_no_messages = cursor.fetchone()[0]
    checks.append(("Sessions without messages", sessions_no_messages, sessions_no_messages == 0))

    # Check for orphaned session messages
    cursor.execute("""
        SELECT COUNT(*) FROM SessionMessages m
        WHERE NOT EXISTS (SELECT 1 FROM Sessions s WHERE s.SessionID = m.SessionID)
    """)
    orphaned_messages = cursor.fetchone()[0]
    checks.append(("Orphaned session messages", orphaned_messages, orphaned_messages == 0))

    # Check for servers without tools
    cursor.execute("""
        SELECT COUNT(*) FROM MCPServers s
        WHERE NOT EXISTS (SELECT 1 FROM MCPServerTools t WHERE t.ServerID = s.ServerID)
    """)
    servers_no_tools = cursor.fetchone()[0]
    checks.append(("Servers without tools", servers_no_tools, True))  # This is acceptable

    for check_name, count, is_ok in checks:
        status = "✓ OK" if is_ok else "✗ ISSUE"
        print(f"  [{status}] {check_name}: {count}")

    print()
    print("=" * 70)
    print("VERIFICATION COMPLETE")
    print("=" * 70)
    print()


def main():
    """Main verification script"""
    print("SQL Migration Verification Tool")
    print()

    # Load configuration from config.json
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.json')

    print(f"Loading configuration from {config_path}")
    config = load_config(config_path)
    connection_string = build_connection_string(config)

    sql_config = config.get('sql_server', {})
    print(f"SQL Server: {sql_config.get('server', 'localhost')}")
    print(f"Database: {sql_config.get('database', 'MCPTokenUsage')}")
    print()

    # Connect and verify
    conn = connect_to_db(connection_string)
    if not conn:
        return 1

    try:
        run_verification(conn)
        return 0
    except Exception as e:
        print(f"ERROR: Verification failed: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
