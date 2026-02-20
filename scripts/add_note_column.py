"""Add Note column to Sessions table if it doesn't exist."""
import json
import pyodbc

cfg = json.load(open('config.json'))
sql = cfg.get('sql_server', {})
driver = sql.get('driver', 'ODBC Driver 17 for SQL Server')
server = sql.get('server', 'localhost')
database = sql.get('database', 'MCPTokenUsage')
cs = f"DRIVER={{{driver}}};SERVER={server};DATABASE={database};Trusted_Connection=yes;"

conn = pyodbc.connect(cs)
cursor = conn.cursor()

cursor.execute(
    "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
    "WHERE TABLE_NAME='Sessions' AND COLUMN_NAME='Note'"
)
if cursor.fetchone():
    print('Note column already exists')
else:
    cursor.execute('ALTER TABLE Sessions ADD Note NVARCHAR(MAX) NULL')
    conn.commit()
    print('Note column added successfully')

conn.close()
