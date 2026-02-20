-- =====================================================
-- Sample Queries for MCP Token Usage Database
-- =====================================================

USE MCPTokenUsage;
GO

-- =====================================================
-- 1. BASIC DATA EXPLORATION
-- =====================================================

-- View all MCP servers
SELECT * FROM vw_ServerSummary ORDER BY ServerName;

-- View all sessions with summary
SELECT * FROM vw_SessionSummary ORDER BY SessionTimestamp DESC;

-- View token usage by date
SELECT * FROM vw_TokenUsageByDate ORDER BY SessionDate DESC;

-- View all comparisons
SELECT * FROM vw_ComparisonSummary ORDER BY ComparisonTimestamp DESC;

-- =====================================================
-- 2. TOKEN USAGE ANALYSIS
-- =====================================================

-- Total token usage across all sessions
SELECT
    COUNT(*) AS TotalSessions,
    SUM(TotalInputTokens) AS TotalInputTokens,
    SUM(TotalOutputTokens) AS TotalOutputTokens,
    SUM(TotalTokens) AS TotalTokens,
    AVG(TotalTokens) AS AvgTokensPerSession,
    MIN(TotalTokens) AS MinTokens,
    MAX(TotalTokens) AS MaxTokens
FROM Sessions;

-- Token usage by month
SELECT
    YEAR(SessionTimestamp) AS Year,
    MONTH(SessionTimestamp) AS Month,
    DATENAME(MONTH, SessionTimestamp) AS MonthName,
    COUNT(*) AS SessionCount,
    SUM(TotalTokens) AS TotalTokens,
    AVG(TotalTokens) AS AvgTokensPerSession
FROM Sessions
GROUP BY YEAR(SessionTimestamp), MONTH(SessionTimestamp), DATENAME(MONTH, SessionTimestamp)
ORDER BY Year DESC, Month DESC;

-- Token usage by day of week
SELECT
    DATENAME(WEEKDAY, SessionTimestamp) AS DayOfWeek,
    COUNT(*) AS SessionCount,
    SUM(TotalTokens) AS TotalTokens,
    AVG(TotalTokens) AS AvgTokensPerSession
FROM Sessions
GROUP BY DATENAME(WEEKDAY, SessionTimestamp), DATEPART(WEEKDAY, SessionTimestamp)
ORDER BY DATEPART(WEEKDAY, SessionTimestamp);

-- Top 20 sessions by token usage
SELECT TOP 20
    SessionID,
    SessionTimestamp,
    TotalInputTokens,
    TotalOutputTokens,
    TotalTokens
FROM Sessions
ORDER BY TotalTokens DESC;

-- Sessions with zero tokens (potential issues)
SELECT
    SessionID,
    SessionTimestamp,
    (SELECT COUNT(*) FROM SessionMessages WHERE SessionID = s.SessionID) AS MessageCount
FROM Sessions s
WHERE TotalTokens = 0;

-- =====================================================
-- 3. COST ANALYSIS
-- =====================================================

-- Estimated cost by session (Claude 3.5 Sonnet pricing: $3/M input, $15/M output)
SELECT TOP 20
    SessionID,
    SessionTimestamp,
    TotalInputTokens,
    TotalOutputTokens,
    TotalTokens,
    (TotalInputTokens * 3.0 / 1000000) AS InputCost,
    (TotalOutputTokens * 15.0 / 1000000) AS OutputCost,
    (TotalInputTokens * 3.0 / 1000000) + (TotalOutputTokens * 15.0 / 1000000) AS TotalCost
FROM Sessions
ORDER BY TotalTokens DESC;

-- Monthly cost summary
SELECT
    YEAR(SessionTimestamp) AS Year,
    MONTH(SessionTimestamp) AS Month,
    DATENAME(MONTH, SessionTimestamp) AS MonthName,
    COUNT(*) AS SessionCount,
    SUM(TotalInputTokens) AS TotalInputTokens,
    SUM(TotalOutputTokens) AS TotalOutputTokens,
    SUM(TotalTokens) AS TotalTokens,
    SUM((TotalInputTokens * 3.0 / 1000000) + (TotalOutputTokens * 15.0 / 1000000)) AS EstimatedMonthlyCost
FROM Sessions
GROUP BY YEAR(SessionTimestamp), MONTH(SessionTimestamp), DATENAME(MONTH, SessionTimestamp)
ORDER BY Year DESC, Month DESC;

-- Cumulative cost over time
SELECT
    CAST(SessionTimestamp AS DATE) AS SessionDate,
    COUNT(*) AS DailySessions,
    SUM((TotalInputTokens * 3.0 / 1000000) + (TotalOutputTokens * 15.0 / 1000000)) AS DailyCost,
    SUM(SUM((TotalInputTokens * 3.0 / 1000000) + (TotalOutputTokens * 15.0 / 1000000)))
        OVER (ORDER BY CAST(SessionTimestamp AS DATE)) AS CumulativeCost
FROM Sessions
GROUP BY CAST(SessionTimestamp AS DATE)
ORDER BY SessionDate;

-- =====================================================
-- 4. SERVER USAGE ANALYSIS
-- =====================================================

-- Server usage statistics
SELECT
    ss.ServerName,
    COUNT(DISTINCT s.SessionID) AS SessionCount,
    SUM(s.TotalInputTokens) AS TotalInputTokens,
    SUM(s.TotalOutputTokens) AS TotalOutputTokens,
    SUM(s.TotalTokens) AS TotalTokens,
    AVG(s.TotalTokens) AS AvgTokensPerSession,
    SUM((s.TotalInputTokens * 3.0 / 1000000) + (s.TotalOutputTokens * 15.0 / 1000000)) AS EstimatedCost
FROM Sessions s
INNER JOIN SessionServers ss ON s.SessionID = ss.SessionID
GROUP BY ss.ServerName
ORDER BY TotalTokens DESC;

-- Server usage over time
SELECT
    CAST(s.SessionTimestamp AS DATE) AS SessionDate,
    ss.ServerName,
    COUNT(*) AS SessionCount,
    SUM(s.TotalTokens) AS TotalTokens
FROM Sessions s
INNER JOIN SessionServers ss ON s.SessionID = ss.SessionID
GROUP BY CAST(s.SessionTimestamp AS DATE), ss.ServerName
ORDER BY SessionDate DESC, TotalTokens DESC;

-- Sessions by server combination
SELECT
    STUFF((
        SELECT ', ' + ServerName
        FROM SessionServers
        WHERE SessionID = s.SessionID
        ORDER BY ServerName
        FOR XML PATH('')
    ), 1, 2, '') AS ServerCombination,
    COUNT(*) AS SessionCount,
    SUM(TotalTokens) AS TotalTokens,
    AVG(TotalTokens) AS AvgTokensPerSession
FROM Sessions s
GROUP BY SessionID
ORDER BY SessionCount DESC;

-- Most used tools across all sessions
SELECT TOP 20
    t.ToolName,
    t.ToolTitle,
    s.ServerName,
    COUNT(*) AS UsageCount
FROM MCPServerTools t
INNER JOIN MCPServers s ON t.ServerID = s.ServerID
INNER JOIN SessionServers ss ON s.ServerID = ss.ServerID
GROUP BY t.ToolName, t.ToolTitle, s.ServerName
ORDER BY UsageCount DESC;

-- =====================================================
-- 5. MESSAGE ANALYSIS
-- =====================================================

-- Average messages per session
SELECT
    COUNT(DISTINCT SessionID) AS TotalSessions,
    COUNT(*) AS TotalMessages,
    COUNT(*) * 1.0 / COUNT(DISTINCT SessionID) AS AvgMessagesPerSession
FROM SessionMessages;

-- Message distribution by role
SELECT
    Role,
    COUNT(*) AS MessageCount,
    AVG(InputTokens) AS AvgInputTokens,
    AVG(OutputTokens) AS AvgOutputTokens
FROM SessionMessages
GROUP BY Role;

-- Sessions with most messages
SELECT TOP 10
    s.SessionID,
    s.SessionTimestamp,
    COUNT(m.MessageID) AS MessageCount,
    s.TotalTokens
FROM Sessions s
LEFT JOIN SessionMessages m ON s.SessionID = m.SessionID
GROUP BY s.SessionID, s.SessionTimestamp, s.TotalTokens
ORDER BY MessageCount DESC;

-- Find sessions with specific keywords in messages
-- (Note: This searches JSON content, may be slow on large datasets)
SELECT DISTINCT
    m.SessionID,
    s.SessionTimestamp
FROM SessionMessages m
INNER JOIN Sessions s ON m.SessionID = s.SessionID
WHERE m.Content LIKE '%specific_keyword%'
ORDER BY s.SessionTimestamp DESC;

-- =====================================================
-- 6. COMPARISON ANALYSIS
-- =====================================================

-- All comparisons with token differences
SELECT
    c.ComparisonID,
    c.ComparisonTimestamp,
    c.Note,
    ls.TotalTokens AS LeftTokens,
    rs.TotalTokens AS RightTokens,
    ABS(ls.TotalTokens - rs.TotalTokens) AS TokenDifference,
    CAST((ABS(ls.TotalTokens - rs.TotalTokens) * 100.0 / NULLIF(ls.TotalTokens, 0)) AS DECIMAL(10,2)) AS PercentDifference
FROM Comparisons c
LEFT JOIN Sessions ls ON c.LeftSessionID = ls.SessionID
LEFT JOIN Sessions rs ON c.RightSessionID = rs.SessionID
ORDER BY c.ComparisonTimestamp DESC;

-- Comparisons with significant token differences (>20%)
SELECT
    c.ComparisonID,
    c.ComparisonTimestamp,
    ls.TotalTokens AS LeftTokens,
    rs.TotalTokens AS RightTokens,
    ABS(ls.TotalTokens - rs.TotalTokens) AS TokenDifference,
    CAST((ABS(ls.TotalTokens - rs.TotalTokens) * 100.0 / NULLIF(ls.TotalTokens, 0)) AS DECIMAL(10,2)) AS PercentDifference
FROM Comparisons c
LEFT JOIN Sessions ls ON c.LeftSessionID = ls.SessionID
LEFT JOIN Sessions rs ON c.RightSessionID = rs.SessionID
WHERE ABS(ls.TotalTokens - rs.TotalTokens) * 100.0 / NULLIF(ls.TotalTokens, 0) > 20
ORDER BY PercentDifference DESC;

-- Average token difference in comparisons
SELECT
    COUNT(*) AS ComparisonCount,
    AVG(ABS(ls.TotalTokens - rs.TotalTokens)) AS AvgTokenDifference,
    MIN(ABS(ls.TotalTokens - rs.TotalTokens)) AS MinTokenDifference,
    MAX(ABS(ls.TotalTokens - rs.TotalTokens)) AS MaxTokenDifference
FROM Comparisons c
LEFT JOIN Sessions ls ON c.LeftSessionID = ls.SessionID
LEFT JOIN Sessions rs ON c.RightSessionID = rs.SessionID;

-- =====================================================
-- 7. AUTHENTICATION & SECURITY QUERIES
-- =====================================================

-- Servers by authentication method
SELECT
    AuthMethod,
    COUNT(*) AS ServerCount
FROM MCPServers
GROUP BY AuthMethod;

-- OAuth2 servers with token expiration
SELECT
    s.ServerName,
    s.URL,
    a.TokenExpiresAt,
    CASE
        WHEN a.TokenExpiresAt < DATEDIFF(SECOND, '1970-01-01', GETDATE())
        THEN 'Expired'
        ELSE 'Valid'
    END AS TokenStatus,
    DATEADD(SECOND, a.TokenExpiresAt, '1970-01-01') AS ExpirationDateTime
FROM MCPServers s
INNER JOIN MCPServerAuth a ON s.ServerID = a.ServerID
WHERE a.AuthType = 'oauth2' AND a.TokenExpiresAt IS NOT NULL
ORDER BY a.TokenExpiresAt;

-- Servers requiring token refresh soon (within 1 hour)
SELECT
    s.ServerName,
    s.URL,
    DATEADD(SECOND, a.TokenExpiresAt, '1970-01-01') AS ExpirationDateTime,
    DATEDIFF(MINUTE, GETDATE(), DATEADD(SECOND, a.TokenExpiresAt, '1970-01-01')) AS MinutesUntilExpiration
FROM MCPServers s
INNER JOIN MCPServerAuth a ON s.ServerID = a.ServerID
WHERE a.AuthType = 'oauth2'
    AND a.TokenExpiresAt IS NOT NULL
    AND DATEADD(SECOND, a.TokenExpiresAt, '1970-01-01') < DATEADD(HOUR, 1, GETDATE())
    AND DATEADD(SECOND, a.TokenExpiresAt, '1970-01-01') > GETDATE()
ORDER BY MinutesUntilExpiration;

-- =====================================================
-- 8. DATA QUALITY & INTEGRITY
-- =====================================================

-- Find duplicate sessions (same timestamp)
SELECT
    SessionTimestamp,
    COUNT(*) AS DuplicateCount
FROM Sessions
GROUP BY SessionTimestamp
HAVING COUNT(*) > 1;

-- Sessions with mismatched token counts
SELECT
    s.SessionID,
    s.TotalInputTokens AS SessionInputTokens,
    SUM(m.InputTokens) AS MessageInputTokensSum,
    s.TotalOutputTokens AS SessionOutputTokens,
    SUM(m.OutputTokens) AS MessageOutputTokensSum
FROM Sessions s
LEFT JOIN SessionMessages m ON s.SessionID = m.SessionID
GROUP BY s.SessionID, s.TotalInputTokens, s.TotalOutputTokens
HAVING s.TotalInputTokens <> ISNULL(SUM(m.InputTokens), 0)
    OR s.TotalOutputTokens <> ISNULL(SUM(m.OutputTokens), 0);

-- Servers with no recent activity (no sessions in last 30 days)
SELECT
    s.ServerID,
    s.ServerName,
    s.Enabled,
    MAX(sess.SessionTimestamp) AS LastUsedDate,
    DATEDIFF(DAY, MAX(sess.SessionTimestamp), GETDATE()) AS DaysSinceLastUse
FROM MCPServers s
LEFT JOIN SessionServers ss ON s.ServerID = ss.ServerID
LEFT JOIN Sessions sess ON ss.SessionID = sess.SessionID
GROUP BY s.ServerID, s.ServerName, s.Enabled
HAVING MAX(sess.SessionTimestamp) IS NULL
    OR MAX(sess.SessionTimestamp) < DATEADD(DAY, -30, GETDATE())
ORDER BY DaysSinceLastUse DESC;

-- =====================================================
-- 9. PERFORMANCE QUERIES
-- =====================================================

-- Longest sessions by duration (if we had duration data)
-- Note: This assumes you add a Duration column to Sessions table
-- ALTER TABLE Sessions ADD Duration INT; -- in milliseconds

-- Most expensive API requests
SELECT TOP 20
    r.RequestID,
    r.SessionID,
    r.RequestTimestamp,
    r.Model,
    r.InputTokens,
    r.OutputTokens,
    (r.InputTokens * 3.0 / 1000000) + (r.OutputTokens * 15.0 / 1000000) AS EstimatedCost
FROM SessionAPIRequests r
ORDER BY (r.InputTokens + r.OutputTokens) DESC;

-- Cache efficiency analysis
SELECT
    COUNT(*) AS RequestCount,
    SUM(InputTokens) AS TotalInputTokens,
    SUM(CacheReadInputTokens) AS TotalCacheReadTokens,
    SUM(CacheCreationInputTokens) AS TotalCacheCreationTokens,
    CAST(SUM(CacheReadInputTokens) * 100.0 / NULLIF(SUM(InputTokens), 0) AS DECIMAL(10,2)) AS CacheHitRate
FROM SessionAPIRequests
WHERE CacheReadInputTokens > 0 OR CacheCreationInputTokens > 0;

-- =====================================================
-- 10. REPORTING QUERIES
-- =====================================================

-- Executive summary
SELECT
    'Total Sessions' AS Metric,
    CAST(COUNT(*) AS NVARCHAR(50)) AS Value
FROM Sessions
UNION ALL
SELECT 'Total Tokens', CAST(SUM(TotalTokens) AS NVARCHAR(50))
FROM Sessions
UNION ALL
SELECT 'Total Input Tokens', CAST(SUM(TotalInputTokens) AS NVARCHAR(50))
FROM Sessions
UNION ALL
SELECT 'Total Output Tokens', CAST(SUM(TotalOutputTokens) AS NVARCHAR(50))
FROM Sessions
UNION ALL
SELECT 'Avg Tokens/Session', CAST(AVG(TotalTokens) AS NVARCHAR(50))
FROM Sessions
UNION ALL
SELECT 'Active MCP Servers', CAST(COUNT(*) AS NVARCHAR(50))
FROM MCPServers WHERE Enabled = 1
UNION ALL
SELECT 'Estimated Total Cost', '$' + CAST(
    CAST(SUM((TotalInputTokens * 3.0 / 1000000) + (TotalOutputTokens * 15.0 / 1000000)) AS DECIMAL(10,2))
    AS NVARCHAR(50))
FROM Sessions;

-- Growth trend (sessions per week)
SELECT
    YEAR(SessionTimestamp) AS Year,
    DATEPART(WEEK, SessionTimestamp) AS Week,
    COUNT(*) AS SessionCount,
    SUM(TotalTokens) AS TotalTokens
FROM Sessions
GROUP BY YEAR(SessionTimestamp), DATEPART(WEEK, SessionTimestamp)
ORDER BY Year DESC, Week DESC;

-- Peak usage hours
SELECT
    DATEPART(HOUR, SessionTimestamp) AS Hour,
    COUNT(*) AS SessionCount,
    SUM(TotalTokens) AS TotalTokens,
    AVG(TotalTokens) AS AvgTokensPerSession
FROM Sessions
GROUP BY DATEPART(HOUR, SessionTimestamp)
ORDER BY Hour;
