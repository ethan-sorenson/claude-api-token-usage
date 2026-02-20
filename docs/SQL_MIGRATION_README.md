# MCP and Session Data SQL Server Migration

This project provides a complete solution for migrating MCP (Model Context Protocol) credentials and Claude API session data from JSON files to a SQL Server database.

## Overview

The migration includes:
- **MCP Server Credentials** - All authentication types (OAuth2, URL token, Bearer, API key)
- **Session Data** - Complete conversation history, token usage, and API requests
- **Comparison Data** - Session comparisons with configurations

## Database Schema

### Core Tables

#### MCP Server Configuration
- **MCPServers** - Server metadata (name, URL, auth method, status)
- **MCPServerAuth** - Authentication details (supports OAuth2, bearer tokens, API keys, URL tokens)
- **MCPServerHeaders** - Custom HTTP headers per server
- **MCPServerPrompts** - Available prompts and their arguments
- **MCPServerTools** - Tools/functions with input/output schemas
- **MCPServerToolAnnotations** - Tool metadata (destructive hints, etc.)

#### Session Tracking
- **Sessions** - Session metadata and total token usage
- **SessionMessages** - Individual messages in conversations
- **SessionAPIRequests** - Detailed API request/response data
- **SessionServers** - MCP servers used in each session

#### Comparison Tracking
- **Comparisons** - Comparison metadata
- **ComparisonConfigs** - Configuration for left/right comparison sides

### Views

- **vw_SessionSummary** - Session overview with message and request counts
- **vw_ServerSummary** - Server overview with tool and prompt counts
- **vw_TokenUsageByDate** - Daily token usage statistics
- **vw_ComparisonSummary** - Comparison overview with token differences

### Stored Procedures

- **sp_GetServerConfig** - Retrieve complete server configuration
- **sp_GetSessionDetails** - Get all session data including messages and API calls
- **sp_GetTokenUsageStats** - Token usage statistics for date range

## Prerequisites

1. **SQL Server** - SQL Server 2016 or later (supports JSON functions)
2. **Python 3.7+** - For running the migration script
3. **ODBC Driver** - ODBC Driver 17 for SQL Server or later

### Install Python Dependencies

```bash
pip install pyodbc
```

Or use the requirements file:
```bash
pip install -r requirements.txt
```

## Migration Steps

### Step 1: Create the Database Schema

1. Open SQL Server Management Studio (SSMS)
2. Create a new database (or use existing):
   ```sql
   CREATE DATABASE MCPTokenUsage;
   GO
   ```
3. Run the schema script:
   ```bash
   # In SSMS, open and execute schema.sql
   # Or via command line:
   sqlcmd -S localhost -d MCPTokenUsage -i schema.sql
   ```

### Step 2: Prepare Data Files

Ensure you have:
- `mcp_credentials.json.backup` - In the project root
- `sessions/` directory - Containing session and comparison JSON files

### Step 3: Run Migration Script

```bash
python migrate_to_sql.py
```

The script will prompt you for:
- SQL Server instance name (e.g., `localhost` or `localhost\SQLEXPRESS`)
- Database name (default: `MCPTokenUsage`)
- Authentication method (Windows or SQL Server authentication)
- Credentials (if using SQL Server authentication)

### Step 4: Verify Migration

Run verification queries:

```sql
-- Check migrated data counts
SELECT 'Servers' AS Entity, COUNT(*) AS Count FROM MCPServers
UNION ALL
SELECT 'Sessions', COUNT(*) FROM Sessions
UNION ALL
SELECT 'Comparisons', COUNT(*) FROM Comparisons
UNION ALL
SELECT 'Tools', COUNT(*) FROM MCPServerTools;

-- View token usage summary
SELECT * FROM vw_TokenUsageByDate ORDER BY SessionDate DESC;

-- View server summary
SELECT * FROM vw_ServerSummary;
```

## Schema Design Details

### Authentication Support

The schema supports multiple authentication methods:

1. **OAuth2** - Full OAuth2 flow with refresh tokens
   - Client ID/Secret
   - Authorization/Token endpoints
   - Refresh tokens and access tokens
   - Token expiration tracking
   - PKCE support

2. **URL Token** - Token passed as URL parameter
   - Token value
   - Parameter name (e.g., "token")

3. **Bearer Token / API Key** - Standard header-based auth
   - Token/key value

### Session Data Structure

Sessions contain:
- **Conversation History** - All user and assistant messages
- **API Requests** - Complete request/response payloads
- **Token Usage** - Input/output tokens, cache tokens
- **Server Usage** - Which MCP servers were used

### Comparison Structure

Comparisons track:
- Left and right session IDs (references to Sessions table)
- Configuration for each side (stored as JSON for flexibility)
- Timestamp and notes

## Querying Examples

### Find Sessions Using Specific Server

```sql
SELECT DISTINCT s.*
FROM Sessions s
INNER JOIN SessionServers ss ON s.SessionID = ss.SessionID
WHERE ss.ServerName = 'Popdock';
```

### Calculate Cost by Session

```sql
SELECT
    SessionID,
    SessionTimestamp,
    TotalInputTokens,
    TotalOutputTokens,
    TotalTokens,
    -- Example pricing: $3 per million input, $15 per million output
    (TotalInputTokens * 3.0 / 1000000) + (TotalOutputTokens * 15.0 / 1000000) AS EstimatedCost
FROM Sessions
ORDER BY SessionTimestamp DESC;
```

### Get Server Usage Statistics

```sql
SELECT
    ss.ServerName,
    COUNT(DISTINCT s.SessionID) AS SessionCount,
    SUM(s.TotalTokens) AS TotalTokens,
    AVG(s.TotalTokens) AS AvgTokensPerSession
FROM Sessions s
INNER JOIN SessionServers ss ON s.SessionID = ss.SessionID
GROUP BY ss.ServerName
ORDER BY TotalTokens DESC;
```

### Find Most Expensive Sessions

```sql
SELECT TOP 10
    SessionID,
    SessionTimestamp,
    TotalTokens,
    TotalInputTokens,
    TotalOutputTokens
FROM Sessions
ORDER BY TotalTokens DESC;
```

### Compare Token Usage Month-over-Month

```sql
SELECT
    YEAR(SessionDate) AS Year,
    MONTH(SessionDate) AS Month,
    SUM(TotalTokens) AS TotalTokens,
    AVG(TotalTokens) AS AvgTokensPerSession
FROM vw_TokenUsageByDate
GROUP BY YEAR(SessionDate), MONTH(SessionDate)
ORDER BY Year DESC, Month DESC;
```

## Security Considerations

### Sensitive Data

The following fields contain sensitive information and should be encrypted in production:

- **MCPServerAuth.Token**
- **MCPServerAuth.ClientSecret**
- **MCPServerAuth.RefreshToken**
- **MCPServerAuth.AccessToken**
- **SessionAPIRequests.APIKey**

### Encryption Options

1. **Transparent Data Encryption (TDE)** - Encrypt entire database
2. **Column-level Encryption** - Encrypt specific columns using:
   - SQL Server Always Encrypted
   - Custom encryption via symmetric keys

Example using symmetric keys:

```sql
-- Create master key
CREATE MASTER KEY ENCRYPTION BY PASSWORD = 'StrongPassword123!';

-- Create certificate
CREATE CERTIFICATE MCPCertificate WITH SUBJECT = 'MCP Sensitive Data';

-- Create symmetric key
CREATE SYMMETRIC KEY MCPKey
    WITH ALGORITHM = AES_256
    ENCRYPTION BY CERTIFICATE MCPCertificate;

-- Encrypt data example
OPEN SYMMETRIC KEY MCPKey DECRYPTION BY CERTIFICATE MCPCertificate;

INSERT INTO MCPServerAuth (ServerID, Token)
VALUES ('server-1', EncryptByKey(Key_GUID('MCPKey'), 'sensitive_token'));

CLOSE SYMMETRIC KEY MCPKey;
```

## Maintenance

### Regular Cleanup

Archive or delete old sessions periodically:

```sql
-- Delete sessions older than 90 days
DELETE FROM Sessions
WHERE SessionTimestamp < DATEADD(DAY, -90, GETDATE());
```

### Index Maintenance

Rebuild indexes monthly:

```sql
-- Rebuild all indexes
EXEC sp_MSforeachtable 'ALTER INDEX ALL ON ? REBUILD';
```

### Backup Strategy

1. **Full Backup** - Weekly
2. **Differential Backup** - Daily
3. **Transaction Log Backup** - Hourly (if in FULL recovery model)

```sql
-- Full backup
BACKUP DATABASE MCPTokenUsage
TO DISK = 'C:\Backups\MCPTokenUsage_Full.bak'
WITH COMPRESSION, INIT;

-- Differential backup
BACKUP DATABASE MCPTokenUsage
TO DISK = 'C:\Backups\MCPTokenUsage_Diff.bak'
WITH DIFFERENTIAL, COMPRESSION, INIT;
```

## Extending the Schema

### Adding Custom Fields

To track additional data, extend existing tables or create new ones:

```sql
-- Example: Add custom tags to sessions
CREATE TABLE SessionTags (
    TagID INT IDENTITY(1,1) PRIMARY KEY,
    SessionID NVARCHAR(100) NOT NULL,
    TagName NVARCHAR(100) NOT NULL,
    TagValue NVARCHAR(MAX),
    CONSTRAINT FK_SessionTags_Session FOREIGN KEY (SessionID)
        REFERENCES Sessions(SessionID) ON DELETE CASCADE
);
```

### Creating Custom Reports

```sql
-- Example: Create view for monthly cost analysis
CREATE VIEW vw_MonthlyCostAnalysis AS
SELECT
    YEAR(SessionTimestamp) AS Year,
    MONTH(SessionTimestamp) AS Month,
    COUNT(*) AS SessionCount,
    SUM(TotalInputTokens) AS TotalInputTokens,
    SUM(TotalOutputTokens) AS TotalOutputTokens,
    SUM(TotalTokens) AS TotalTokens,
    -- Claude 3.5 Sonnet pricing example
    SUM((TotalInputTokens * 3.0 / 1000000) + (TotalOutputTokens * 15.0 / 1000000)) AS EstimatedCost
FROM Sessions
GROUP BY YEAR(SessionTimestamp), MONTH(SessionTimestamp);
```

## Troubleshooting

### Connection Issues

If you can't connect to SQL Server:

1. Check SQL Server is running:
   ```bash
   # Windows
   sc query MSSQLSERVER
   ```

2. Verify TCP/IP is enabled:
   - Open SQL Server Configuration Manager
   - Enable TCP/IP under "SQL Server Network Configuration"

3. Check firewall rules allow port 1433

### Migration Errors

Check `migration.log` for detailed error messages.

Common issues:
- **Foreign key constraint errors** - Ensure parent records exist before child records
- **Data type mismatch** - Check JSON data types match SQL column types
- **Timeout errors** - Increase connection timeout in connection string

### Performance Issues

If queries are slow:

1. Update statistics:
   ```sql
   EXEC sp_updatestats;
   ```

2. Check missing indexes:
   ```sql
   SELECT
       migs.avg_user_impact * (migs.user_seeks + migs.user_scans) AS Impact,
       mid.*
   FROM sys.dm_db_missing_index_details AS mid
   CROSS APPLY sys.dm_db_missing_index_groups AS mig
   CROSS APPLY sys.dm_db_missing_index_group_stats AS migs
   WHERE mid.database_id = DB_ID()
   ORDER BY Impact DESC;
   ```

3. Consider adding covering indexes for frequent queries

## Support

For issues or questions:
1. Check the migration.log file
2. Review SQL Server error logs
3. Verify all prerequisites are installed
4. Ensure database permissions are correct

## License

This migration tool is provided as-is for use with MCP and Claude API session data.
