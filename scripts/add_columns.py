"""Add Notes column to MCPServers, TokenID and Model columns to Sessions."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.db import get_db_manager

db = get_db_manager()
with db.get_connection() as conn:
    cursor = conn.cursor()

    # Add Notes column to MCPServers if not exists
    cursor.execute("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='MCPServers' AND COLUMN_NAME='Notes')
        ALTER TABLE MCPServers ADD Notes NVARCHAR(500) NULL
    """)
    print("Checked MCPServers.Notes column")

    # Add TokenID column to Sessions if not exists
    cursor.execute("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='Sessions' AND COLUMN_NAME='TokenID')
        ALTER TABLE Sessions ADD TokenID NVARCHAR(100) NULL
    """)
    print("Checked Sessions.TokenID column")

    # Add Model column to Sessions if not exists
    cursor.execute("""
        IF NOT EXISTS (SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='Sessions' AND COLUMN_NAME='Model')
        ALTER TABLE Sessions ADD Model NVARCHAR(100) NULL
    """)
    print("Checked Sessions.Model column")

    conn.commit()
    print("Migration complete!")
