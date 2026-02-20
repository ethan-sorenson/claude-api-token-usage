-- =====================================================
-- SQL Server Schema for MCP Credentials and Sessions
-- =====================================================

-- Database creation (optional - comment out if database exists)
CREATE DATABASE MCPTokenUsage;
GO
USE MCPTokenUsage;
GO

-- Set required options for computed columns and indexed views
SET ANSI_NULLS ON;
GO
SET QUOTED_IDENTIFIER ON;
GO

-- =====================================================
-- Table: MCPServers
-- Stores MCP server configurations
-- =====================================================
CREATE TABLE MCPServers (
    ServerID NVARCHAR(50) PRIMARY KEY,
    ServerName NVARCHAR(255) NOT NULL,
    URL NVARCHAR(2000) NOT NULL,
    AuthMethod NVARCHAR(50) NOT NULL, -- bearer_token, bearer, api_key, oauth2, url_token
    Enabled BIT NOT NULL DEFAULT 1,
    Collapsed BIT DEFAULT 0,
    Notes NVARCHAR(500) NULL,
    LastValidated DATETIME2,
    CreatedDate DATETIME2 DEFAULT GETDATE(),
    ModifiedDate DATETIME2 DEFAULT GETDATE()
);

-- Index for quick lookups
CREATE INDEX IX_MCPServers_Enabled ON MCPServers(Enabled);
CREATE INDEX IX_MCPServers_AuthMethod ON MCPServers(AuthMethod);

-- =====================================================
-- Table: MCPServerAuth
-- Stores authentication details for MCP servers
-- Supports multiple auth types with different fields
-- =====================================================
CREATE TABLE MCPServerAuth (
    AuthID INT IDENTITY(1,1) PRIMARY KEY,
    ServerID NVARCHAR(50) NOT NULL,
    AuthType NVARCHAR(50) NOT NULL, -- bearer_token, bearer, api_key, oauth2, url_token

    -- Common auth fields
    Token NVARCHAR(MAX), -- Encrypted in production
    TokenParamName NVARCHAR(100),

    -- OAuth2 specific fields
    ClientID NVARCHAR(500),
    ClientSecret NVARCHAR(MAX), -- Encrypted in production
    AuthorizationEndpoint NVARCHAR(2000),
    TokenEndpoint NVARCHAR(2000),
    RedirectURI NVARCHAR(2000),
    RefreshToken NVARCHAR(MAX), -- Encrypted in production
    AccessToken NVARCHAR(MAX), -- Encrypted in production
    TokenExpiresAt BIGINT, -- Unix timestamp
    TokenObtainedAt BIGINT, -- Unix timestamp
    Scopes NVARCHAR(500),
    Resource NVARCHAR(500),
    PKCECodeVerifier NVARCHAR(500),

    CreatedDate DATETIME2 DEFAULT GETDATE(),
    ModifiedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_MCPServerAuth_Server FOREIGN KEY (ServerID) REFERENCES MCPServers(ServerID) ON DELETE CASCADE
);

-- Index for server lookups
CREATE INDEX IX_MCPServerAuth_ServerID ON MCPServerAuth(ServerID);

-- =====================================================
-- Table: MCPServerHeaders
-- Stores custom HTTP headers for MCP servers
-- =====================================================
CREATE TABLE MCPServerHeaders (
    HeaderID INT IDENTITY(1,1) PRIMARY KEY,
    ServerID NVARCHAR(50) NOT NULL,
    HeaderName NVARCHAR(255) NOT NULL,
    HeaderValue NVARCHAR(MAX) NOT NULL,
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_MCPServerHeaders_Server FOREIGN KEY (ServerID) REFERENCES MCPServers(ServerID) ON DELETE CASCADE
);

-- Index for server lookups
CREATE INDEX IX_MCPServerHeaders_ServerID ON MCPServerHeaders(ServerID);

-- =====================================================
-- Table: MCPServerPrompts
-- Stores prompts associated with MCP servers
-- =====================================================
CREATE TABLE MCPServerPrompts (
    PromptID INT IDENTITY(1,1) PRIMARY KEY,
    ServerID NVARCHAR(50) NOT NULL,
    PromptName NVARCHAR(255) NOT NULL,
    PromptTitle NVARCHAR(500),
    Description NVARCHAR(MAX),
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_MCPServerPrompts_Server FOREIGN KEY (ServerID) REFERENCES MCPServers(ServerID) ON DELETE CASCADE
);

-- Index for server lookups
CREATE INDEX IX_MCPServerPrompts_ServerID ON MCPServerPrompts(ServerID);

-- =====================================================
-- Table: MCPServerPromptArguments
-- Stores arguments for prompts
-- =====================================================
CREATE TABLE MCPServerPromptArguments (
    ArgumentID INT IDENTITY(1,1) PRIMARY KEY,
    PromptID INT NOT NULL,
    ArgumentName NVARCHAR(255) NOT NULL,
    ArgumentTitle NVARCHAR(500),
    Description NVARCHAR(MAX),
    Required BIT DEFAULT 0,
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_MCPServerPromptArgs_Prompt FOREIGN KEY (PromptID) REFERENCES MCPServerPrompts(PromptID) ON DELETE CASCADE
);

-- Index for prompt lookups
CREATE INDEX IX_MCPServerPromptArgs_PromptID ON MCPServerPromptArguments(PromptID);

-- =====================================================
-- Table: MCPServerTools
-- Stores tools/functions available on MCP servers
-- =====================================================
CREATE TABLE MCPServerTools (
    ToolID INT IDENTITY(1,1) PRIMARY KEY,
    ServerID NVARCHAR(50) NOT NULL,
    ToolName NVARCHAR(255) NOT NULL,
    ToolTitle NVARCHAR(500),
    Description NVARCHAR(MAX),
    InputSchema NVARCHAR(MAX), -- JSON
    OutputSchema NVARCHAR(MAX), -- JSON
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_MCPServerTools_Server FOREIGN KEY (ServerID) REFERENCES MCPServers(ServerID) ON DELETE CASCADE
);

-- Index for server and tool lookups
CREATE INDEX IX_MCPServerTools_ServerID ON MCPServerTools(ServerID);
CREATE INDEX IX_MCPServerTools_ToolName ON MCPServerTools(ToolName);

-- =====================================================
-- Table: MCPServerToolAnnotations
-- Stores annotations for tools (destructive, readOnly hints, etc.)
-- =====================================================
CREATE TABLE MCPServerToolAnnotations (
    AnnotationID INT IDENTITY(1,1) PRIMARY KEY,
    ToolID INT NOT NULL,
    AnnotationKey NVARCHAR(255) NOT NULL,
    AnnotationValue NVARCHAR(MAX),
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_MCPServerToolAnnotations_Tool FOREIGN KEY (ToolID) REFERENCES MCPServerTools(ToolID) ON DELETE CASCADE
);

-- Index for tool lookups
CREATE INDEX IX_MCPServerToolAnnotations_ToolID ON MCPServerToolAnnotations(ToolID);

-- =====================================================
-- Table: Sessions
-- Stores Claude API conversation sessions
-- =====================================================
CREATE TABLE Sessions (
    SessionID NVARCHAR(100) PRIMARY KEY,
    SessionTimestamp DATETIME2 NOT NULL,
    TotalInputTokens INT DEFAULT 0,
    TotalOutputTokens INT DEFAULT 0,
    TotalTokens AS (TotalInputTokens + TotalOutputTokens) PERSISTED,
    TokenID NVARCHAR(100) NULL,
    Model NVARCHAR(100) NULL,
    Note NVARCHAR(MAX) NULL,
    ProviderState NVARCHAR(MAX) NULL, -- JSON blob for mid-conversation state (total_cost, mistral_conversation_id, openai_history, etc.)
    CreatedDate DATETIME2 DEFAULT GETDATE()
);

-- Index for timestamp queries
CREATE INDEX IX_Sessions_Timestamp ON Sessions(SessionTimestamp);

-- =====================================================
-- Table: SessionMessages
-- Stores individual messages within a session
-- =====================================================
CREATE TABLE SessionMessages (
    MessageID INT IDENTITY(1,1) PRIMARY KEY,
    SessionID NVARCHAR(100) NOT NULL,
    MessageIndex INT NOT NULL, -- Order within session
    Role NVARCHAR(20) NOT NULL, -- user, assistant
    Content NVARCHAR(MAX), -- JSON array of content blocks
    MessageTimestamp DATETIME2,
    InputTokens INT DEFAULT 0,
    OutputTokens INT DEFAULT 0,
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_SessionMessages_Session FOREIGN KEY (SessionID) REFERENCES Sessions(SessionID) ON DELETE CASCADE,
    CONSTRAINT UQ_SessionMessages_Order UNIQUE (SessionID, MessageIndex)
);

-- Index for session lookups
CREATE INDEX IX_SessionMessages_SessionID ON SessionMessages(SessionID);

-- =====================================================
-- Table: SessionAPIRequests
-- Stores detailed API request/response data
-- =====================================================
CREATE TABLE SessionAPIRequests (
    RequestID INT IDENTITY(1,1) PRIMARY KEY,
    SessionID NVARCHAR(100) NOT NULL,
    MessageID INT,
    RequestTimestamp DATETIME2 NOT NULL,
    APIKey NVARCHAR(500), -- Encrypted in production
    Model NVARCHAR(100),
    MaxTokens INT,
    RequestPayload NVARCHAR(MAX), -- Full JSON request
    ResponsePayload NVARCHAR(MAX), -- Full JSON response
    InputTokens INT,
    OutputTokens INT,
    CacheCreationInputTokens INT DEFAULT 0,
    CacheReadInputTokens INT DEFAULT 0,
    StopReason NVARCHAR(50),
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_SessionAPIRequests_Session FOREIGN KEY (SessionID) REFERENCES Sessions(SessionID) ON DELETE CASCADE,
    CONSTRAINT FK_SessionAPIRequests_Message FOREIGN KEY (MessageID) REFERENCES SessionMessages(MessageID) ON DELETE NO ACTION
);

-- Index for session lookups
CREATE INDEX IX_SessionAPIRequests_SessionID ON SessionAPIRequests(SessionID);
CREATE INDEX IX_SessionAPIRequests_Timestamp ON SessionAPIRequests(RequestTimestamp);

-- =====================================================
-- Table: SessionServers
-- Tracks which MCP servers were used in each session
-- =====================================================
CREATE TABLE SessionServers (
    SessionServerID INT IDENTITY(1,1) PRIMARY KEY,
    SessionID NVARCHAR(100) NOT NULL,
    ServerID NVARCHAR(50) NOT NULL,
    ServerName NVARCHAR(255),
    ServerURL NVARCHAR(2000),
    AuthType NVARCHAR(50),
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_SessionServers_Session FOREIGN KEY (SessionID) REFERENCES Sessions(SessionID) ON DELETE CASCADE
);

-- Index for session lookups
CREATE INDEX IX_SessionServers_SessionID ON SessionServers(SessionID);

-- =====================================================
-- Table: Comparisons
-- Stores session comparison metadata
-- =====================================================
CREATE TABLE Comparisons (
    ComparisonID NVARCHAR(100) PRIMARY KEY,
    ComparisonTimestamp DATETIME2 NOT NULL,
    Note NVARCHAR(MAX),
    LeftSessionID NVARCHAR(100) NOT NULL,
    RightSessionID NVARCHAR(100) NOT NULL,
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_Comparisons_LeftSession FOREIGN KEY (LeftSessionID) REFERENCES Sessions(SessionID) ON DELETE NO ACTION,
    CONSTRAINT FK_Comparisons_RightSession FOREIGN KEY (RightSessionID) REFERENCES Sessions(SessionID) ON DELETE NO ACTION
);

-- Index for timestamp queries
CREATE INDEX IX_Comparisons_Timestamp ON Comparisons(ComparisonTimestamp);

-- =====================================================
-- Table: ComparisonConfigs
-- Stores configuration for each side of a comparison
-- =====================================================
CREATE TABLE ComparisonConfigs (
    ConfigID INT IDENTITY(1,1) PRIMARY KEY,
    ComparisonID NVARCHAR(100) NOT NULL,
    Side NVARCHAR(10) NOT NULL, -- 'left' or 'right'
    ConfigJSON NVARCHAR(MAX) NOT NULL, -- Full config as JSON
    CreatedDate DATETIME2 DEFAULT GETDATE(),

    CONSTRAINT FK_ComparisonConfigs_Comparison FOREIGN KEY (ComparisonID) REFERENCES Comparisons(ComparisonID) ON DELETE CASCADE,
    CONSTRAINT CHK_ComparisonConfigs_Side CHECK (Side IN ('left', 'right'))
);

-- Index for comparison lookups
CREATE INDEX IX_ComparisonConfigs_ComparisonID ON ComparisonConfigs(ComparisonID);

-- =====================================================
-- Views for easier querying
-- =====================================================

-- View: Session summary with token usage
GO
CREATE VIEW vw_SessionSummary AS
SELECT
    s.SessionID,
    s.SessionTimestamp,
    s.TotalInputTokens,
    s.TotalOutputTokens,
    s.TotalTokens,
    COUNT(DISTINCT m.MessageID) AS MessageCount,
    COUNT(DISTINCT r.RequestID) AS APIRequestCount,
    COUNT(DISTINCT ss.ServerID) AS ServerCount
FROM Sessions s
LEFT JOIN SessionMessages m ON s.SessionID = m.SessionID
LEFT JOIN SessionAPIRequests r ON s.SessionID = r.SessionID
LEFT JOIN SessionServers ss ON s.SessionID = ss.SessionID
GROUP BY s.SessionID, s.SessionTimestamp, s.TotalInputTokens, s.TotalOutputTokens, s.TotalTokens;

GO

-- View: Server summary with tool counts
CREATE VIEW vw_ServerSummary AS
SELECT
    s.ServerID,
    s.ServerName,
    s.URL,
    s.AuthMethod,
    s.Enabled,
    COUNT(DISTINCT t.ToolID) AS ToolCount,
    COUNT(DISTINCT p.PromptID) AS PromptCount,
    COUNT(DISTINCT h.HeaderID) AS HeaderCount
FROM MCPServers s
LEFT JOIN MCPServerTools t ON s.ServerID = t.ServerID
LEFT JOIN MCPServerPrompts p ON s.ServerID = p.ServerID
LEFT JOIN MCPServerHeaders h ON s.ServerID = h.ServerID
GROUP BY s.ServerID, s.ServerName, s.URL, s.AuthMethod, s.Enabled;

GO

-- View: Token usage by date
CREATE VIEW vw_TokenUsageByDate AS
SELECT
    CAST(SessionTimestamp AS DATE) AS SessionDate,
    COUNT(*) AS SessionCount,
    SUM(TotalInputTokens) AS TotalInputTokens,
    SUM(TotalOutputTokens) AS TotalOutputTokens,
    SUM(TotalTokens) AS TotalTokens,
    AVG(TotalInputTokens) AS AvgInputTokens,
    AVG(TotalOutputTokens) AS AvgOutputTokens
FROM Sessions
GROUP BY CAST(SessionTimestamp AS DATE);

GO

-- View: Comparison summary
CREATE VIEW vw_ComparisonSummary AS
SELECT
    c.ComparisonID,
    c.ComparisonTimestamp,
    c.Note,
    c.LeftSessionID,
    ls.SessionTimestamp AS LeftSessionTimestamp,
    ls.TotalTokens AS LeftTotalTokens,
    c.RightSessionID,
    rs.SessionTimestamp AS RightSessionTimestamp,
    rs.TotalTokens AS RightTotalTokens,
    ABS(ls.TotalTokens - rs.TotalTokens) AS TokenDifference
FROM Comparisons c
LEFT JOIN Sessions ls ON c.LeftSessionID = ls.SessionID
LEFT JOIN Sessions rs ON c.RightSessionID = rs.SessionID;

GO

-- =====================================================
-- Stored Procedures
-- =====================================================

-- Get server configuration with all related data
CREATE PROCEDURE sp_GetServerConfig
    @ServerID NVARCHAR(50)
AS
BEGIN
    SET NOCOUNT ON;

    -- Server info
    SELECT * FROM MCPServers WHERE ServerID = @ServerID;

    -- Auth info
    SELECT * FROM MCPServerAuth WHERE ServerID = @ServerID;

    -- Headers
    SELECT * FROM MCPServerHeaders WHERE ServerID = @ServerID;

    -- Prompts and arguments
    SELECT
        p.*,
        a.ArgumentID,
        a.ArgumentName,
        a.ArgumentTitle,
        a.Description AS ArgumentDescription,
        a.Required
    FROM MCPServerPrompts p
    LEFT JOIN MCPServerPromptArguments a ON p.PromptID = a.PromptID
    WHERE p.ServerID = @ServerID;

    -- Tools
    SELECT * FROM MCPServerTools WHERE ServerID = @ServerID;
END;

GO

-- Get session details
CREATE PROCEDURE sp_GetSessionDetails
    @SessionID NVARCHAR(100)
AS
BEGIN
    SET NOCOUNT ON;

    -- Session summary
    SELECT * FROM vw_SessionSummary WHERE SessionID = @SessionID;

    -- Messages
    SELECT * FROM SessionMessages WHERE SessionID = @SessionID ORDER BY MessageIndex;

    -- API Requests
    SELECT * FROM SessionAPIRequests WHERE SessionID = @SessionID ORDER BY RequestTimestamp;

    -- Servers used
    SELECT * FROM SessionServers WHERE SessionID = @SessionID;
END;

GO

-- Get token usage statistics
CREATE PROCEDURE sp_GetTokenUsageStats
    @StartDate DATE = NULL,
    @EndDate DATE = NULL
AS
BEGIN
    SET NOCOUNT ON;

    IF @StartDate IS NULL SET @StartDate = DATEADD(MONTH, -1, GETDATE());
    IF @EndDate IS NULL SET @EndDate = GETDATE();

    SELECT
        SessionDate,
        SessionCount,
        TotalInputTokens,
        TotalOutputTokens,
        TotalTokens,
        AvgInputTokens,
        AvgOutputTokens
    FROM vw_TokenUsageByDate
    WHERE SessionDate BETWEEN @StartDate AND @EndDate
    ORDER BY SessionDate;
END;

GO

PRINT 'Schema created successfully!';
