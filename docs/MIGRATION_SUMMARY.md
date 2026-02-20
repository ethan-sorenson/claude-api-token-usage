# MCP and Session Data SQL Server Migration - Summary

## Overview

This project provides a complete solution for migrating MCP (Model Context Protocol) server credentials and Claude API session data from JSON files to a SQL Server database. The solution includes:

✅ **Comprehensive SQL Schema** - Supports all authentication types and session data structures
✅ **Automated Migration Tool** - Python script to migrate all data from JSON to SQL Server
✅ **Verification Script** - Validates migration and generates reports
✅ **Sample Queries** - 50+ ready-to-use SQL queries for analysis
✅ **Documentation** - Complete schema diagrams, usage guides, and best practices

## Quick Start

### Prerequisites
1. SQL Server 2016 or later
2. Python 3.7+
3. ODBC Driver 17 for SQL Server
4. pyodbc Python package

### Installation Steps

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Create database and schema
# Open SQL Server Management Studio and run:
sqlcmd -S localhost -i schema.sql

# 3. Run migration
python migrate_to_sql.py

# 4. Verify migration
python verify_migration.py
```

## Project Files

### Core Files

| File                           | Purpose                                              |
|--------------------------------|-----------------------------------------------------|
| **schema.sql**                 | Complete database schema with tables, views, SPs    |
| **migrate_to_sql.py**          | Migration script from JSON to SQL Server            |
| **verify_migration.py**        | Verification and reporting script                   |
| **sample_queries.sql**         | 50+ example queries for analysis                    |
| **SQL_MIGRATION_README.md**    | Comprehensive usage documentation                   |
| **SCHEMA_DIAGRAM.md**          | Visual schema diagrams and relationships            |
| **requirements.txt**           | Python dependencies                                 |

### Data Files (Input)

| File                           | Purpose                                              |
|--------------------------------|-----------------------------------------------------|
| **mcp_credentials.json.backup**| MCP server credentials and configurations           |
| **sessions/session_*.json**    | Individual Claude API conversation sessions         |
| **sessions/comparison_*.json** | Session comparison metadata and configurations      |

## Database Schema Overview

### Tables Created

#### MCP Server Configuration (7 tables)
- **MCPServers** - Server metadata
- **MCPServerAuth** - Authentication details (all types)
- **MCPServerHeaders** - Custom HTTP headers
- **MCPServerPrompts** - Available prompts
- **MCPServerPromptArguments** - Prompt parameters
- **MCPServerTools** - Tools/functions with schemas
- **MCPServerToolAnnotations** - Tool metadata

#### Session Tracking (4 tables)
- **Sessions** - Session metadata and token totals
- **SessionMessages** - Conversation messages
- **SessionAPIRequests** - Detailed API request/response data
- **SessionServers** - MCP servers used per session

#### Comparison Tracking (2 tables)
- **Comparisons** - Comparison metadata
- **ComparisonConfigs** - Left/right configuration data

### Views Created (4)
- **vw_SessionSummary** - Session overview with counts
- **vw_ServerSummary** - Server overview with tool counts
- **vw_TokenUsageByDate** - Daily token usage statistics
- **vw_ComparisonSummary** - Comparison analysis with token differences

### Stored Procedures (3)
- **sp_GetServerConfig** - Retrieve complete server configuration
- **sp_GetSessionDetails** - Get all session data
- **sp_GetTokenUsageStats** - Token usage for date range

## Supported Authentication Methods

The schema fully supports all MCP authentication types:

| Auth Method    | Description                                          | Supported |
|----------------|-----------------------------------------------------|-----------|
| **oauth2**     | Full OAuth2 flow with refresh tokens and expiration| ✅        |
| **url_token**  | Token passed as URL query parameter                 | ✅        |
| **bearer**     | Bearer token in Authorization header                | ✅        |
| **bearer_token** | Legacy bearer token format                        | ✅        |
| **api_key**    | API key authentication                              | ✅        |

### OAuth2 Support Includes:
- Client ID and Client Secret
- Authorization and Token endpoints
- Redirect URI
- Refresh tokens and access tokens
- Token expiration tracking (Unix timestamp)
- Token obtained timestamp
- Scopes and resource
- PKCE code verifier

## Migration Process

### Step 1: Prepare Database
```sql
-- Create database (optional)
CREATE DATABASE MCPTokenUsage;
GO

-- Run schema script
sqlcmd -S localhost -d MCPTokenUsage -i schema.sql
```

### Step 2: Run Migration
```bash
python migrate_to_sql.py
```

The migration script will:
1. Prompt for SQL Server connection details
2. Validate data files exist
3. Migrate MCP server credentials
4. Migrate all sessions
5. Migrate all comparisons
6. Display summary statistics

### Step 3: Verify Migration
```bash
python verify_migration.py
```

The verification script provides:
- Record counts for all tables
- Server configuration summary
- Token usage statistics
- Recent activity overview
- Data integrity checks

## Sample Queries

The **sample_queries.sql** file includes 10 categories of queries:

1. **Basic Data Exploration** - Simple queries to view data
2. **Token Usage Analysis** - Total usage, by month, by day
3. **Cost Analysis** - Estimated costs by session, month, cumulative
4. **Server Usage Analysis** - Which servers are used most
5. **Message Analysis** - Message patterns and distributions
6. **Comparison Analysis** - Token differences between comparisons
7. **Authentication & Security** - Token expiration, auth methods
8. **Data Quality & Integrity** - Find issues and duplicates
9. **Performance Queries** - Most expensive requests, cache efficiency
10. **Reporting Queries** - Executive summaries, trends

### Example Query: Monthly Cost Summary

```sql
SELECT
    YEAR(SessionTimestamp) AS Year,
    MONTH(SessionTimestamp) AS Month,
    COUNT(*) AS SessionCount,
    SUM(TotalTokens) AS TotalTokens,
    SUM((TotalInputTokens * 3.0 / 1000000) +
        (TotalOutputTokens * 15.0 / 1000000)) AS EstimatedCost
FROM Sessions
GROUP BY YEAR(SessionTimestamp), MONTH(SessionTimestamp)
ORDER BY Year DESC, Month DESC;
```

### Example Query: Server Usage Statistics

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

## Key Features

### 1. Complete Data Preservation
- All JSON data is migrated without loss
- Complex nested structures preserved (tools, prompts, headers)
- Full conversation history maintained
- API request/response payloads stored as JSON

### 2. Flexible Querying
- Views simplify common queries
- Stored procedures for complex operations
- Indexes optimize performance
- Computed columns for derived values

### 3. Data Integrity
- Foreign keys enforce relationships
- Unique constraints prevent duplicates
- Check constraints validate data
- CASCADE deletes maintain consistency

### 4. Security Ready
- Sensitive fields identified for encryption
- Support for column-level encryption
- Audit-ready structure
- Separation of credentials from usage data

### 5. Extensibility
- Easy to add custom fields
- Views can be extended
- Additional indexes can be added
- Custom stored procedures supported

## Use Cases

### 1. Token Usage Analysis
Track and analyze API token consumption:
- Daily, weekly, monthly trends
- Cost estimation and budgeting
- Identify expensive sessions
- Optimize token usage

### 2. MCP Server Management
Manage multiple MCP server configurations:
- Track server usage across sessions
- Monitor authentication status
- Identify unused servers
- Audit tool usage

### 3. Session Comparison
Analyze differences between sessions:
- Compare token usage
- Identify configuration impacts
- A/B testing analysis
- Performance optimization

### 4. Cost Management
Monitor and control API costs:
- Real-time cost tracking
- Budget alerts (via custom queries)
- Cost allocation by project/user
- ROI analysis

### 5. Compliance & Auditing
Maintain records for compliance:
- Complete audit trail
- Data retention policies
- Access logging (via SQL Server features)
- Compliance reporting

## Security Considerations

### Sensitive Data Fields

These fields contain sensitive information and should be encrypted in production:

| Table             | Field                | Type            |
|-------------------|----------------------|-----------------|
| MCPServerAuth     | Token                | Auth token      |
| MCPServerAuth     | ClientSecret         | OAuth2 secret   |
| MCPServerAuth     | RefreshToken         | OAuth2 token    |
| MCPServerAuth     | AccessToken          | OAuth2 token    |
| SessionAPIRequests| APIKey               | Claude API key  |

### Encryption Options

1. **Transparent Data Encryption (TDE)** - Encrypt entire database
2. **Always Encrypted** - Column-level encryption with client-side keys
3. **Symmetric Keys** - SQL Server built-in encryption functions

See **SQL_MIGRATION_README.md** for encryption examples.

## Performance Optimization

### Current Indexes
- Primary key indexes (clustered)
- Foreign key indexes
- Timestamp indexes for date queries
- Name/ID indexes for lookups

### Recommended Additional Indexes
Based on query patterns, consider adding:
- Covering indexes for frequent query combinations
- Filtered indexes for common WHERE clauses
- Columnstore indexes for large fact tables

### Maintenance Schedule
- **Daily:** Transaction log backups
- **Weekly:** Full backups, index defragmentation
- **Monthly:** Statistics updates
- **Quarterly:** Archive old data

## Troubleshooting

### Common Issues

#### 1. Connection Errors
**Problem:** Can't connect to SQL Server
**Solution:**
- Verify SQL Server is running
- Check firewall allows port 1433
- Verify authentication method (Windows vs SQL)
- Test connection with SQL Server Management Studio first

#### 2. Migration Errors
**Problem:** Migration script fails
**Solution:**
- Check `migration.log` for details
- Verify all JSON files are valid
- Ensure database schema exists
- Check disk space for large sessions

#### 3. Performance Issues
**Problem:** Queries are slow
**Solution:**
- Update statistics: `EXEC sp_updatestats;`
- Rebuild indexes: `ALTER INDEX ALL ON [table] REBUILD;`
- Review execution plans
- Consider additional indexes

#### 4. Data Inconsistencies
**Problem:** Token counts don't match
**Solution:**
- Run verification script
- Check for migration errors in log
- Re-migrate specific sessions if needed
- Verify JSON source data

## Next Steps

After successful migration:

1. **Explore the data**
   ```sql
   -- Run the executive summary
   SELECT * FROM vw_SessionSummary ORDER BY SessionTimestamp DESC;
   SELECT * FROM vw_TokenUsageByDate ORDER BY SessionDate DESC;
   ```

2. **Set up security**
   - Implement encryption for sensitive fields
   - Create database users with appropriate permissions
   - Enable SQL Server auditing

3. **Create custom reports**
   - Build views for specific use cases
   - Create stored procedures for common operations
   - Set up automated reports

4. **Integrate with applications**
   - Update your application to read from SQL Server
   - Create APIs to access the data
   - Build dashboards and visualizations

5. **Establish maintenance**
   - Schedule regular backups
   - Set up index maintenance jobs
   - Configure archival policies
   - Monitor performance

## Support and Documentation

### Documentation Files
- **SQL_MIGRATION_README.md** - Comprehensive usage guide
- **SCHEMA_DIAGRAM.md** - Visual schema documentation
- **sample_queries.sql** - Query examples and templates
- **This file (MIGRATION_SUMMARY.md)** - Quick reference

### Getting Help
1. Check the documentation files for detailed information
2. Review `migration.log` for error details
3. Run `verify_migration.py` to check data integrity
4. Check SQL Server error logs for server-side issues

## Future Enhancements

Potential improvements to consider:

1. **Real-time sync** - Keep SQL Server updated as new sessions are created
2. **Web dashboard** - Visualize token usage and costs
3. **Alerting** - Notify when costs exceed thresholds
4. **Multi-tenancy** - Support multiple users/organizations
5. **Data warehouse** - Create dimensional model for advanced analytics
6. **Machine learning** - Predict usage patterns and optimize costs
7. **API integration** - REST API for programmatic access
8. **Scheduled reports** - Email reports on usage and costs

## Migration Statistics Example

After migration, you should see output similar to:

```
======================================================================
MIGRATION VERIFICATION REPORT
======================================================================
Generated: 2026-02-17 10:30:45

----------------------------------------------------------------------
1. RECORD COUNTS
----------------------------------------------------------------------
  MCP Servers............................................ 2
  Server Auth Records.................................... 2
  Server Headers......................................... 2
  Server Prompts......................................... 2
  Server Tools........................................... 45
  Sessions............................................... 27
  Session Messages....................................... 156
  API Requests........................................... 89
  Comparisons............................................ 6

----------------------------------------------------------------------
2. TOKEN USAGE SUMMARY
----------------------------------------------------------------------
  Total Sessions: 27
  Total Input Tokens: 1,234,567
  Total Output Tokens: 456,789
  Total Tokens: 1,691,356
  Average Tokens per Session: 62,643
  Estimated Total Cost (Sonnet 3.5): $10.54

======================================================================
VERIFICATION COMPLETE
======================================================================
```

## Conclusion

This migration solution provides:
- ✅ Complete data migration from JSON to SQL Server
- ✅ Comprehensive schema supporting all MCP auth types
- ✅ Ready-to-use queries for analysis
- ✅ Security-conscious design
- ✅ Performance-optimized structure
- ✅ Extensible and maintainable

You now have a robust SQL Server database for analyzing MCP server usage and Claude API token consumption.

## License

This migration tool and database schema are provided as-is for use with MCP and Claude API session data.

---

**Version:** 1.0
**Last Updated:** 2026-02-17
**Compatible with:** SQL Server 2016+, Python 3.7+
