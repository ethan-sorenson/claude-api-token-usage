# Code Migration to SQL Server - Complete Guide

## Overview

Your application has been migrated from JSON file storage to SQL Server database storage. This provides better performance, data integrity, and scalability.

## What Changed

### 1. New Files Created

#### **db_manager.py**
- Centralized database manager module
- Handles all SQL Server operations
- Provides functions for:
  - MCP credentials management
  - Session management
  - OAuth token updates
- Uses connection pooling and context managers for safe database access

### 2. Modified Files

#### **app.py**
Updated to use database instead of JSON files:

**Imports:**
```python
from db_manager import get_db_manager
```

**Initialization:**
```python
# Initialize database manager
db = get_db_manager()
```

**Functions Changed:**
- `load_mcp_credentials()` - Now reads from database
- `save_mcp_credentials()` - Now writes to database
- `_save_mcp_credentials_locked()` - Now uses database
- `list_sessions()` - Reads from Sessions table
- `get_session()` - Reads session with all details from database
- `save_session()` - Saves to database
- `delete_session()` - Deletes from database

#### **config.json**
Added SQL Server configuration section:
```json
"sql_server": {
  "server": "localhost",
  "database": "MCPTokenUsage",
  "use_windows_auth": true,
  "username": null,
  "password": null,
  "driver": "ODBC Driver 17 for SQL Server"
}
```

### 3. Deprecated Files (No Longer Used)

These files are no longer read or written by the application:
- `mcp_credentials.json` (replaced by MCPServers table)
- `sessions/*.json` (replaced by Sessions table)

**Important:** Keep these files as backups until you verify the migration worked correctly!

## Migration Steps

### Step 1: Ensure Database is Created

Run the schema creation if you haven't already:

```powershell
sqlcmd -S localhost -i schema.sql
```

### Step 2: Migrate Existing Data

Migrate your existing JSON data to SQL Server:

```powershell
python migrate_to_sql.py
```

This will:
- Read from `mcp_credentials.json.backup`
- Read all session files from `sessions/` directory
- Insert everything into SQL Server
- Display summary of migrated records

### Step 3: Verify Migration

Run the verification script:

```powershell
python verify_migration.py
```

This will show:
- Record counts for all tables
- Token usage statistics
- Recent activity
- Data integrity checks

### Step 4: Test the Application

Start the Flask application:

```powershell
python app.py
```

Test key functionality:
1. ✅ List MCP servers (GET `/api/mcp/credentials`)
2. ✅ Add/update MCP server (POST `/api/mcp/credentials`)
3. ✅ List sessions (GET `/api/sessions`)
4. ✅ Get specific session (GET `/api/sessions/<id>`)
5. ✅ Save new session (POST `/api/sessions`)
6. ✅ Delete session (DELETE `/api/sessions/<id>`)

### Step 5: Backup Old Files (Optional)

Once you've verified everything works, backup the old files:

```powershell
# Create backups directory
mkdir backups

# Move old files
move mcp_credentials.json backups\
move mcp_credentials.json.backup backups\
xcopy sessions\*.json backups\sessions\ /s /i
```

## Configuration

### SQL Server Connection

Edit `config.json` to configure your SQL Server connection:

**Windows Authentication (default):**
```json
"sql_server": {
  "server": "localhost",
  "database": "MCPTokenUsage",
  "use_windows_auth": true
}
```

**SQL Server Authentication:**
```json
"sql_server": {
  "server": "localhost",
  "database": "MCPTokenUsage",
  "use_windows_auth": false,
  "username": "your_username",
  "password": "your_password"
}
```

**Named Instance:**
```json
"sql_server": {
  "server": "localhost\\SQLEXPRESS",
  "database": "MCPTokenUsage",
  "use_windows_auth": true
}
```

## Database Schema

### MCP Server Tables

1. **MCPServers** - Server configurations
2. **MCPServerAuth** - Authentication details (OAuth2, bearer tokens, etc.)
3. **MCPServerHeaders** - Custom HTTP headers
4. **MCPServerPrompts** - Available prompts
5. **MCPServerPromptArguments** - Prompt parameters
6. **MCPServerTools** - Tools/functions
7. **MCPServerToolAnnotations** - Tool metadata

### Session Tables

1. **Sessions** - Session metadata and token totals
2. **SessionMessages** - Conversation messages
3. **SessionAPIRequests** - API request/response data
4. **SessionServers** - MCP servers used per session

### Comparison Tables

1. **Comparisons** - Comparison metadata
2. **ComparisonConfigs** - Left/right configuration data

## API Changes

### Behavior Changes

#### Session Listing
- **Before:** Listed all JSON files from `sessions/` directory
- **After:** Returns most recent 100 sessions from database (configurable)
- Performance: Much faster with large numbers of sessions

#### Session Storage
- **Before:** Each session was a separate JSON file
- **After:** Sessions stored in relational tables with proper relationships
- Benefit: Better data integrity and querying capabilities

#### MCP Credentials
- **Before:** Single JSON file with all server configs
- **After:** Normalized tables with proper relationships
- Benefit: Supports complex OAuth2 flows, easier to query specific servers

### No API Contract Changes

All existing API endpoints maintain the same request/response format:
- Same URLs
- Same HTTP methods
- Same JSON structures
- Same error responses

Your frontend code should work without modifications!

## Error Handling

### Connection Errors

If the application can't connect to SQL Server:

```
ERROR: Failed to connect to database
```

**Solutions:**
1. Verify SQL Server is running
2. Check firewall allows port 1433
3. Verify authentication settings in config.json
4. Test connection with SQL Server Management Studio

### Migration Errors

If migration fails:

```
ERROR: Failed to migrate [table/file]
```

**Solutions:**
1. Check migration.log for details
2. Verify JSON files are valid
3. Ensure database schema exists
4. Check disk space

## Performance Benefits

### Query Performance
- **Before:** O(n) - read all files, parse JSON
- **After:** O(log n) - indexed database queries

### Concurrent Access
- **Before:** File locking, potential conflicts
- **After:** Database transactions, proper concurrency

### Data Integrity
- **Before:** No validation, potential corruption
- **After:** Foreign keys, constraints, transactions

## Rollback Procedure

If you need to roll back to JSON files:

1. Stop the application
2. Restore the old app.py from git or backup
3. Restore JSON files from backups
4. Restart the application

```powershell
# Restore from git
git checkout HEAD app.py

# Or restore from backup
copy backups\mcp_credentials.json .
xcopy backups\sessions\*.json sessions\ /s /i
```

## Troubleshooting

### Issue: "Database manager not initialized"

**Solution:** Check that config.json has sql_server section and connection details are correct.

### Issue: "Session not found" after migration

**Solution:** Ensure migration completed successfully. Check Sessions table:

```sql
SELECT COUNT(*) FROM Sessions;
SELECT TOP 10 * FROM Sessions ORDER BY SessionTimestamp DESC;
```

### Issue: OAuth tokens not refreshing

**Solution:** Check MCPServerAuth table has correct token_expires_at values:

```sql
SELECT ServerID, TokenExpiresAt,
       DATEADD(SECOND, TokenExpiresAt, '1970-01-01') AS ExpirationDateTime
FROM MCPServerAuth
WHERE AuthType = 'oauth2';
```

### Issue: Performance is slow

**Solution:** Update statistics and rebuild indexes:

```sql
-- Update statistics
EXEC sp_updatestats;

-- Rebuild indexes
ALTER INDEX ALL ON Sessions REBUILD;
ALTER INDEX ALL ON SessionMessages REBUILD;
ALTER INDEX ALL ON SessionAPIRequests REBUILD;
```

## Monitoring

### View Recent Sessions

```sql
SELECT TOP 10
    SessionID,
    SessionTimestamp,
    TotalInputTokens,
    TotalOutputTokens,
    TotalTokens
FROM Sessions
ORDER BY SessionTimestamp DESC;
```

### View Token Usage

```sql
SELECT
    CAST(SessionTimestamp AS DATE) AS Date,
    COUNT(*) AS SessionCount,
    SUM(TotalTokens) AS TotalTokens
FROM Sessions
WHERE SessionTimestamp >= DATEADD(DAY, -7, GETDATE())
GROUP BY CAST(SessionTimestamp AS DATE)
ORDER BY Date DESC;
```

### View MCP Server Usage

```sql
SELECT
    ss.ServerName,
    COUNT(DISTINCT s.SessionID) AS SessionCount,
    SUM(s.TotalTokens) AS TotalTokens
FROM Sessions s
INNER JOIN SessionServers ss ON s.SessionID = ss.SessionID
GROUP BY ss.ServerName
ORDER BY TotalTokens DESC;
```

## Next Steps

1. ✅ Verify migration completed successfully
2. ✅ Test all API endpoints
3. ✅ Monitor application logs
4. ✅ Set up database backups
5. ✅ Optimize queries if needed
6. ✅ Document any custom queries for your team

## Support

For issues:
1. Check migration.log for details
2. Check app.log for application errors
3. Run verify_migration.py to check data integrity
4. Review sample_queries.sql for troubleshooting queries

---

**Migration Date:** 2026-02-17
**Version:** 1.0
**Database:** SQL Server 2016+
