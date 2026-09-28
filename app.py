import os
import sqlite3
from flask import Flask, request, Response, render_template, redirect, url_for

app = Flask(__name__)
DB_NAME = "bagga.db"

# ==========================================
# DATABASE INITIALIZATION
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Table for storing feedback entries
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            anon_id TEXT,
            channel TEXT DEFAULT 'USSD',
            category TEXT,
            raw_text TEXT,
            language TEXT,
            urgency TEXT DEFAULT 'NORMAL',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table for tracking unique attendees
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendees (
            phone_number TEXT PRIMARY KEY,
            anon_id TEXT,
            language TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# ==========================================
# MULTILINGUAL DICTIONARY FOR USSD
# ==========================================
USSD_TEXTS = {
    'en': {
        'select_category': "CON Select category:\n1. Praise\n2. Sound/Audio\n3. Facilities\n4. General Note",
        'type_message': "CON Type your message or feedback:",
        'thank_you': "END Thank you for your feedback! Bagga has recorded your note."
    },
    'lg': {
        'select_category': "CON Londa kategoria:\n1. Okusiima\n2. Edoboozi/Sound\n3. Eby'omukutu\n4. Ekirowoozo Eky'abulijjo",
        'type_message': "CON Wandiika ekyomukutu gwo oba ekyrowoozo kyolina:",
        'thank_you': "END Weebale nnyo okutuwa ekyrowoozo kyo! Bagga ekikutte."
    },
    'sw': {
        'select_category': "CON Chagua aina:\n1. Sifa\n2. Sauti/Mfumo\n3. Vifaa/Majengo\n4. Wazo la Kawaida",
        'type_message': "CON Andika ujumbe au maoni yako:",
        'thank_you': "END Asante kwa kutoa maoni yako! Bagga imerekodi ujumbe wako."
    }
}

CATEGORIES = {
    '1': 'PRAISE',
    '2': 'SOUND/AUDIO',
    '3': 'AC/FACILITIES',
    '4': 'GENERAL'
}

# Comprehensive list of urgent keywords (English, Luganda, Kiswahili)
URGENT_KEYWORDS = [
    # English - Sound & Audio
    'mic', 'microphone', 'sound', 'audio', 'speaker', 'loud', 'silent', 'volume', 'hear', 'echo', 'noise',
    # English - Facilities / Temperature / Emergency
    'ac', 'aircon', 'fan', 'hot', 'heat', 'warm', 'stuffy', 'fire', 'help', 'emergency', 'broken', 'bad', 'dark', 'light', 'power',
    # Luganda
    'edoboozi', 'sikyawulira', 'ebugumu', 'omuliro', 'akazindaalo', 'obuzibu', 'ebikwata',
    # Kiswahili
    'sauti', 'joto', 'mbovu', 'msaidie', 'moto', 'kipaza', 'haisikiki', 'fani'
]

def check_urgency(text):
    """Checks input string for high-urgency keywords across supported languages."""
    if not text:
        return 'NORMAL'
    
    cleaned = text.lower()
    # Strip common punctuation for accurate token evaluation
    words = [w.strip(".,!?:;\"'()[]{}") for w in cleaned.split()]
    
    for kw in URGENT_KEYWORDS:
        if kw in words or kw in cleaned:
            return 'HIGH'
            
    return 'NORMAL'

# ==========================================
# ATTENDEE USSD ROUTE (HANDLES BOTH ENDPOINTS)
# ==========================================
@app.route('/ussd', methods=['POST', 'GET'])
@app.route('/api/ussd', methods=['POST', 'GET'])
def ussd_callback():
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "").strip()

    # Split user menu selections
    user_inputs = text.split('*') if text else []

    # LEVEL 0: Initial Dial -> Ask for Language
    if text == "":
        response = "CON Welcome to Bagga!\nChoose Language / Londa Lulimi:\n1. English\n2. Luganda\n3. Swahili"
        return Response(response, mimetype='text/plain')

    # Map language choice
    lang_choice = user_inputs[0]
    lang_map = {'1': 'en', '2': 'lg', '3': 'sw'}
    selected_lang = lang_map.get(lang_choice, 'en')

    # LEVEL 1: Language Chosen -> Ask for Category
    if len(user_inputs) == 1:
        if lang_choice not in lang_map:
            return Response("END Invalid option. Please dial again.", mimetype='text/plain')
        response = USSD_TEXTS[selected_lang]['select_category']
        return Response(response, mimetype='text/plain')

    # LEVEL 2: Category Chosen -> Prompt for Text Input
    if len(user_inputs) == 2:
        response = USSD_TEXTS[selected_lang]['type_message']
        return Response(response, mimetype='text/plain')

    # LEVEL 3: Text Entered -> Save Data & Send Thanks
    if len(user_inputs) == 3:
        category_code = user_inputs[1]
        category_name = CATEGORIES.get(category_code, 'GENERAL')
        raw_text = user_inputs[2]

        # Determine Urgency
        urgency = check_urgency(raw_text)
        anon_id = f"Attendee#{phone_number[-4:]}" if len(phone_number) >= 4 else "Attendee#0000"

        # Database Insertion
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        # Insert/Update Attendee
        cursor.execute('''
            INSERT INTO attendees (phone_number, anon_id, language)
            VALUES (?, ?, ?)
            ON CONFLICT(phone_number) DO UPDATE SET language=excluded.language
        ''', (phone_number, anon_id, selected_lang))

        # Insert Feedback
        cursor.execute('''
            INSERT INTO feedback (phone_number, anon_id, channel, category, raw_text, language, urgency)
            VALUES (?, ?, 'USSD', ?, ?, ?, ?)
        ''', (phone_number, anon_id, category_name, raw_text, selected_lang, urgency))

        conn.commit()
        conn.close()

        response = USSD_TEXTS[selected_lang]['thank_you']
        return Response(response, mimetype='text/plain')

    return Response("END Invalid interaction. Please try again.", mimetype='text/plain')


# ==========================================
# ORGANIZER DASHBOARD ROUTES
# ==========================================
@app.route('/', methods=['GET'])
@app.route('/dashboard', methods=['GET'])
def dashboard():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Total submissions count across all time
    cursor.execute('SELECT COUNT(*) FROM feedback')
    total_feedback_count = cursor.fetchone()[0]

    # Fetch ALL feedback entries sorted newest first
    cursor.execute('SELECT * FROM feedback ORDER BY id DESC')
    feedbacks = [dict(row) for row in cursor.fetchall()]

    # Fetch all attendees with their submission count
    cursor.execute('''
        SELECT a.phone_number, a.anon_id, a.language, COUNT(f.id) as feedback_count
        FROM attendees a
        LEFT JOIN feedback f ON a.phone_number = f.phone_number
        GROUP BY a.phone_number
        ORDER BY a.created_at DESC
    ''')
    attendees = [dict(row) for row in cursor.fetchall()]

    # High urgency stats
    cursor.execute("SELECT COUNT(*) FROM feedback WHERE urgency = 'HIGH'")
    high_urgency_result = cursor.fetchone()
    high_urgency = high_urgency_result[0] if high_urgency_result else 0

    stats = {
        'total_feedback': total_feedback_count,
        'high_urgency': high_urgency
    }

    conn.close()
    return render_template('dashboard.html', feedbacks=feedbacks, attendees=attendees, stats=stats)


@app.route('/api/organizer/delete/<int:feedback_id>', methods=['POST'])
def delete_feedback(feedback_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM feedback WHERE id = ?', (feedback_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard'))


@app.route('/api/organizer/reply', methods=['POST'])
def reply_sms():
    phone_number = request.form.get('phone_number')
    message = request.form.get('message')
    
    print(f"[SMS REPLY SENT] To: {phone_number} | Message: {message}")
    
    return redirect(url_for('dashboard'))


@app.route('/api/organizer/thankyou', methods=['POST'])
def broadcast_sms():
    thank_you_message = request.form.get('thank_you_message')
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT phone_number FROM attendees')
    numbers = cursor.fetchall()
    conn.close()

    for row in numbers:
        phone = row[0]
        print(f"[BROADCAST SMS] To: {phone} | Message: {thank_you_message}")

    return redirect(url_for('dashboard'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)