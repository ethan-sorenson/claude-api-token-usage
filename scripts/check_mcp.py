"""Debug: check MCP server configs stored in DB."""
import sys
sys.path.insert(0, '.')
from server.db import get_db_manager

db = get_db_manager()
with db.get_connection() as conn:
    cursor = conn.cursor()
    
    # List all MCP servers
    cursor.execute("SELECT ServerID, ServerName, URL, AuthMethod, Enabled FROM MCPServers ORDER BY ServerName")
    print("=== MCPServers ===")
    for r in cursor.fetchall():
        print(f"  ID={r.ServerID}  Name={r.ServerName}  AuthMethod={r.AuthMethod}  Enabled={r.Enabled}")
    
    # List auth for each server  
    cursor.execute("""
        SELECT s.ServerID, s.ServerName, a.AuthType,
               CASE WHEN a.Token IS NOT NULL THEN 'YES (' + LEFT(a.Token, 8) + '...)' ELSE 'NULL' END as HasToken,
               CASE WHEN a.AccessToken IS NOT NULL THEN 'YES' ELSE 'NULL' END as HasAccessToken
        FROM MCPServers s LEFT JOIN MCPServerAuth a ON s.ServerID = a.ServerID
    """)
    print("\n=== Auth Status ===")
    for r in cursor.fetchall():
        print(f"  {r.ServerName}: AuthType={r.AuthType}  Token={r.HasToken}  AccessToken={r.HasAccessToken}")
