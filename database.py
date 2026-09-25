import sqlite3

DB_NAME = "bagga.db"

def init_db():
    """Initializes the SQLite database and creates the feedback table."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anon_id TEXT NOT NULL,
            channel TEXT NOT NULL,         -- USSD, SMS, or VOICE
            raw_text TEXT,
            category TEXT DEFAULT 'GENERAL',
            urgency TEXT DEFAULT 'LOW',
            sentiment TEXT DEFAULT 'NEUTRAL',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def save_feedback(anon_id, channel, raw_text, category="GENERAL", urgency="LOW", sentiment="NEUTRAL"):
    """Inserts a new feedback entry into the database."""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO feedback (anon_id, channel, raw_text, category, urgency, sentiment)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (anon_id, channel, raw_text, category, urgency, sentiment))
    conn.commit()
    conn.close()

def get_all_feedback():
    """Retrieves all feedback entries as dictionaries for the dashboard."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM feedback ORDER BY timestamp DESC')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
