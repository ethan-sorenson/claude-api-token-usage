-- =====================================================
-- Drop and recreate MCPTokenUsage database
-- Run this if you need to start over
-- =====================================================

USE master;
GO

-- Drop database if it exists
IF EXISTS (SELECT name FROM sys.databases WHERE name = 'MCPTokenUsage')
BEGIN
    ALTER DATABASE MCPTokenUsage SET SINGLE_USER WITH ROLLBACK IMMEDIATE;
    DROP DATABASE MCPTokenUsage;
    PRINT 'Database MCPTokenUsage dropped successfully.';
END
ELSE
BEGIN
    PRINT 'Database MCPTokenUsage does not exist.';
END
GO
