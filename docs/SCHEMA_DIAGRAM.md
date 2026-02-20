# Database Schema Diagram

## Entity Relationship Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MCP SERVER CONFIGURATION                            │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │   MCPServers     │──────────┐
    │──────────────────│          │
    │ ServerID (PK)    │          │
    │ ServerName       │          │
    │ URL              │          │
    │ AuthMethod       │          │
    │ Enabled          │          │
    │ Collapsed        │          │
    │ LastValidated    │          │
    └────────┬─────────┘          │
             │                     │
             │ 1:N                 │ 1:N
             │                     │
    ┌────────▼─────────┐  ┌───────▼──────────┐
    │ MCPServerAuth    │  │ MCPServerHeaders │
    │──────────────────│  │──────────────────│
    │ AuthID (PK)      │  │ HeaderID (PK)    │
    │ ServerID (FK)    │  │ ServerID (FK)    │
    │ AuthType         │  │ HeaderName       │
    │ Token            │  │ HeaderValue      │
    │ ClientID         │  └──────────────────┘
    │ ClientSecret     │
    │ RefreshToken     │         │
    │ AccessToken      │         │ 1:N
    │ (OAuth2 fields)  │         │
    └──────────────────┘  ┌──────▼───────────┐
             │            │ MCPServerPrompts │
             │            │──────────────────│
             │            │ PromptID (PK)    │
             │            │ ServerID (FK)    │
             │ 1:N        │ PromptName       │
             │            │ Description      │
    ┌────────▼─────────┐ └────────┬─────────┘
    │ MCPServerTools   │          │
    │──────────────────│          │ 1:N
    │ ToolID (PK)      │          │
    │ ServerID (FK)    │  ┌───────▼──────────────────┐
    │ ToolName         │  │ MCPServerPromptArguments│
    │ Description      │  │──────────────────────────│
    │ InputSchema      │  │ ArgumentID (PK)         │
    │ OutputSchema     │  │ PromptID (FK)           │
    └────────┬─────────┘  │ ArgumentName            │
             │            │ Required                 │
             │ 1:N        └──────────────────────────┘
             │
    ┌────────▼──────────────────┐
    │ MCPServerToolAnnotations │
    │──────────────────────────│
    │ AnnotationID (PK)        │
    │ ToolID (FK)              │
    │ AnnotationKey            │
    │ AnnotationValue          │
    └──────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                        SESSION & MESSAGE TRACKING                            │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │   Sessions       │
    │──────────────────│
    │ SessionID (PK)   │──────────┐
    │ SessionTimestamp │          │
    │ TotalInputTokens │          │
    │ TotalOutputTokens│          │
    │ TotalTokens      │          │
    └────────┬─────────┘          │
             │                     │
             │ 1:N                 │ 1:N
             │                     │
    ┌────────▼─────────┐  ┌───────▼──────────────┐
    │ SessionMessages  │  │ SessionAPIRequests   │
    │──────────────────│  │──────────────────────│
    │ MessageID (PK)   │  │ RequestID (PK)       │
    │ SessionID (FK)   │  │ SessionID (FK)       │
    │ MessageIndex     │  │ MessageID (FK)       │
    │ Role             │  │ RequestTimestamp     │
    │ Content          │  │ APIKey               │
    │ MessageTimestamp │  │ Model                │
    │ InputTokens      │  │ RequestPayload       │
    │ OutputTokens     │  │ ResponsePayload      │
    └──────────────────┘  │ InputTokens          │
                          │ OutputTokens         │
             │            │ CacheCreationTokens  │
             │ 1:N        │ CacheReadTokens      │
             │            │ StopReason           │
    ┌────────▼─────────┐ └──────────────────────┘
    │ SessionServers   │
    │──────────────────│
    │ SessionServerID  │
    │ SessionID (FK)   │
    │ ServerID (FK)    │
    │ ServerName       │
    │ ServerURL        │
    │ AuthType         │
    └──────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                         COMPARISON TRACKING                                  │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────────┐
    │   Comparisons    │
    │──────────────────│
    │ ComparisonID (PK)│
    │ ComparisonTS     │
    │ Note             │
    │ LeftSessionID ───┼──┐ (FK to Sessions)
    │ RightSessionID ──┼──┘ (FK to Sessions)
    └────────┬─────────┘
             │
             │ 1:N
             │
    ┌────────▼─────────┐
    │ComparisonConfigs │
    │──────────────────│
    │ ConfigID (PK)    │
    │ ComparisonID (FK)│
    │ Side             │ ('left' or 'right')
    │ ConfigJSON       │
    └──────────────────┘
```

## Table Relationships Summary

### MCP Server Configuration Domain

| Parent Table        | Child Table                 | Relationship | Description                           |
|---------------------|-----------------------------|--------------|------------------------------------- |
| MCPServers          | MCPServerAuth               | 1:N          | One server, multiple auth records    |
| MCPServers          | MCPServerHeaders            | 1:N          | One server, multiple headers         |
| MCPServers          | MCPServerPrompts            | 1:N          | One server, multiple prompts         |
| MCPServers          | MCPServerTools              | 1:N          | One server, multiple tools           |
| MCPServerPrompts    | MCPServerPromptArguments    | 1:N          | One prompt, multiple arguments       |
| MCPServerTools      | MCPServerToolAnnotations    | 1:N          | One tool, multiple annotations       |

### Session Tracking Domain

| Parent Table        | Child Table                 | Relationship | Description                           |
|---------------------|-----------------------------|--------------|------------------------------------- |
| Sessions            | SessionMessages             | 1:N          | One session, multiple messages       |
| Sessions            | SessionAPIRequests          | 1:N          | One session, multiple API requests   |
| Sessions            | SessionServers              | 1:N          | One session, multiple servers used   |
| SessionMessages     | SessionAPIRequests          | 1:N          | One message can have multiple reqs   |

### Comparison Domain

| Parent Table        | Child Table                 | Relationship | Description                           |
|---------------------|-----------------------------|--------------|------------------------------------- |
| Sessions            | Comparisons                 | N:M          | Sessions can be in multiple comps    |
| Comparisons         | ComparisonConfigs           | 1:2          | Each comparison has left/right conf  |

## Key Fields by Table

### MCPServers
- **ServerID** (NVARCHAR(50)) - Unique identifier (e.g., "server-1")
- **AuthMethod** (NVARCHAR(50)) - bearer_token, bearer, api_key, oauth2, url_token
- **Enabled** (BIT) - Whether server is active

### MCPServerAuth
- **AuthType** (NVARCHAR(50)) - Same values as AuthMethod
- **Token** (NVARCHAR(MAX)) - Auth token (encrypted in production)
- **ClientID, ClientSecret** - OAuth2 credentials
- **TokenExpiresAt** (BIGINT) - Unix timestamp for token expiration

### MCPServerTools
- **ToolName** (NVARCHAR(255)) - Tool identifier
- **InputSchema, OutputSchema** (NVARCHAR(MAX)) - JSON schemas
- **Description** (NVARCHAR(MAX)) - Tool documentation

### Sessions
- **SessionID** (NVARCHAR(100)) - Unique identifier (e.g., "session_1768391825318")
- **TotalInputTokens, TotalOutputTokens** (INT) - Token counters
- **TotalTokens** (Computed) - Sum of input + output tokens

### SessionMessages
- **MessageIndex** (INT) - Order within session (starts at 0)
- **Role** (NVARCHAR(20)) - "user" or "assistant"
- **Content** (NVARCHAR(MAX)) - JSON array of content blocks

### SessionAPIRequests
- **RequestPayload, ResponsePayload** (NVARCHAR(MAX)) - Full JSON of request/response
- **CacheCreationInputTokens, CacheReadInputTokens** (INT) - Prompt caching metrics
- **Model** (NVARCHAR(100)) - e.g., "claude-sonnet-4-20250514"

### Comparisons
- **LeftSessionID, RightSessionID** (NVARCHAR(100)) - References to Sessions
- **Note** (NVARCHAR(MAX)) - User-provided comparison notes

### ComparisonConfigs
- **Side** (NVARCHAR(10)) - 'left' or 'right'
- **ConfigJSON** (NVARCHAR(MAX)) - Full server configuration as JSON

## Indexes

### Primary Indexes
All primary keys have clustered indexes by default.

### Performance Indexes
- **IX_Sessions_Timestamp** - Fast date range queries
- **IX_SessionMessages_SessionID** - Fast message lookups
- **IX_SessionAPIRequests_SessionID** - Fast API request lookups
- **IX_SessionServers_SessionID** - Fast server usage lookups
- **IX_MCPServers_Enabled** - Quick enabled/disabled filtering
- **IX_MCPServerTools_ServerID** - Fast tool lookups
- **IX_MCPServerTools_ToolName** - Fast tool name searches

## Views

### vw_SessionSummary
Aggregates session data with message, request, and server counts.

**Columns:**
- SessionID, SessionTimestamp
- TotalInputTokens, TotalOutputTokens, TotalTokens
- MessageCount, APIRequestCount, ServerCount

### vw_ServerSummary
Aggregates server configuration with tool, prompt, and header counts.

**Columns:**
- ServerID, ServerName, URL, AuthMethod, Enabled
- ToolCount, PromptCount, HeaderCount

### vw_TokenUsageByDate
Daily aggregation of token usage.

**Columns:**
- SessionDate (DATE)
- SessionCount, TotalInputTokens, TotalOutputTokens, TotalTokens
- AvgInputTokens, AvgOutputTokens

### vw_ComparisonSummary
Comparison overview with token differences.

**Columns:**
- ComparisonID, ComparisonTimestamp, Note
- LeftSessionID, LeftSessionTimestamp, LeftTotalTokens
- RightSessionID, RightSessionTimestamp, RightTotalTokens
- TokenDifference

## Data Flow

### Migration Process
```
JSON Files                       SQL Server Database
───────────                      ───────────────────

mcp_credentials.json.backup
    │
    ├─► MCPServers
    ├─► MCPServerAuth
    ├─► MCPServerHeaders
    ├─► MCPServerPrompts
    │   └─► MCPServerPromptArguments
    └─► MCPServerTools
        └─► MCPServerToolAnnotations

sessions/session_*.json
    │
    ├─► Sessions
    ├─► SessionMessages
    ├─► SessionAPIRequests
    └─► SessionServers

sessions/comparison_*.json
    │
    ├─► Comparisons
    └─► ComparisonConfigs
        ├─► (references left session)
        └─► (references right session)
```

### Query Flow Examples

**Get complete server configuration:**
```
MCPServers → MCPServerAuth
           → MCPServerHeaders
           → MCPServerPrompts → MCPServerPromptArguments
           → MCPServerTools → MCPServerToolAnnotations
```

**Get complete session details:**
```
Sessions → SessionMessages
        → SessionAPIRequests
        → SessionServers → MCPServers
```

**Analyze comparison:**
```
Comparisons → Sessions (left)
           → Sessions (right)
           → ComparisonConfigs
```

## Stored Procedures

### sp_GetServerConfig
**Input:** @ServerID
**Returns:** All server configuration data including auth, headers, prompts, and tools

### sp_GetSessionDetails
**Input:** @SessionID
**Returns:** Session summary, messages, API requests, and servers used

### sp_GetTokenUsageStats
**Input:** @StartDate, @EndDate (optional)
**Returns:** Token usage statistics for date range

## Migration Script Flow

```
migrate_to_sql.py execution flow:
──────────────────────────────────

1. User provides SQL Server connection details
   └─► Establish connection

2. Load mcp_credentials.json.backup
   ├─► For each server:
   │   ├─► Insert/Update MCPServers
   │   ├─► Insert MCPServerAuth
   │   ├─► Insert MCPServerHeaders
   │   ├─► Insert MCPServerPrompts + Arguments
   │   └─► Insert MCPServerTools + Annotations
   └─► Commit transaction

3. Load sessions/session_*.json files
   ├─► For each session:
   │   ├─► Insert/Update Sessions
   │   ├─► Insert SessionMessages
   │   ├─► Insert SessionAPIRequests
   │   └─► Insert SessionServers
   └─► Commit transaction

4. Load sessions/comparison_*.json files
   ├─► For each comparison:
   │   ├─► Load left/right session files
   │   ├─► Insert/Update Comparisons
   │   └─► Insert ComparisonConfigs
   └─► Commit transaction

5. Display migration summary
   └─► Count of records migrated per table
```

## Best Practices

### Security
1. Encrypt sensitive columns (tokens, secrets, API keys)
2. Use SQL Server Always Encrypted for column-level encryption
3. Restrict direct access to auth tables
4. Use stored procedures for data access
5. Enable auditing for sensitive table access

### Performance
1. Regular index maintenance (weekly rebuilds)
2. Update statistics after large data loads
3. Archive old sessions (>90 days) to separate table
4. Use covering indexes for frequent query patterns
5. Monitor query execution plans

### Data Integrity
1. All foreign keys have ON DELETE CASCADE or NO ACTION
2. Unique constraints prevent duplicate entries
3. Check constraints validate enum values
4. Default values ensure data completeness
5. Computed columns maintain consistency

### Maintenance
1. **Daily:** Transaction log backups
2. **Weekly:** Full database backups
3. **Monthly:** Index maintenance
4. **Quarterly:** Archive old data
5. **Yearly:** Review and optimize schema
