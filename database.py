import sqlite3

DB_NAME = "bagga.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            anon_id TEXT,
            channel TEXT,
            raw_text TEXT,
            category TEXT,
            urgency TEXT,
            phone_number TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS organizer_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient_phone TEXT,
            message_text TEXT,
            msg_type TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_feedback(anon_id, channel, raw_text, category, urgency, phone_number=""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO feedback (anon_id, channel, raw_text, category, urgency, phone_number)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (anon_id, channel, raw_text, category, urgency, phone_number))
    conn.commit()
    conn.close()

def save_organizer_message(recipient_phone, message_text, msg_type="REPLY"):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO organizer_messages (recipient_phone, message_text, msg_type)
        VALUES (?, ?, ?)
    """, (recipient_phone, message_text, msg_type))
    conn.commit()
    conn.close()

def get_all_feedback():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM feedback ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    
    return [dict(row) for row in rows]

def get_dashboard_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM feedback")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM feedback WHERE urgency = 'HIGH'")
    high_urgency = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(DISTINCT phone_number) FROM feedback WHERE phone_number != ''")
    attendees = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM organizer_messages")
    messages_sent = cursor.fetchone()[0]
    
    conn.close()
    return {
        "total": total,
        "high_urgency": high_urgency,
        "attendees": attendees,
        "messages_sent": messages_sent
    }

def get_all_phone_numbers():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT phone_number FROM feedback WHERE phone_number IS NOT NULL AND phone_number != ''")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def get_attendee_list():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            phone_number, 
            anon_id, 
            COUNT(*) as total_feedback,
            MAX(created_at) as last_seen
        FROM feedback 
        WHERE phone_number IS NOT NULL AND phone_number != ''
        GROUP BY phone_number
        ORDER BY last_seen DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]