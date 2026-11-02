import os
import sqlite3
import csv
import io
from datetime import datetime, timezone
from flask import Flask, request, Response, render_template, redirect, url_for, make_response, jsonify
from ai_engine import analyze_feedback, translate_to_english

app = Flask(__name__)
DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bagga.db")

# ==========================================
# DATABASE INITIALIZATION
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
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
            sentiment TEXT DEFAULT 'NEUTRAL',
            translated_text TEXT,
            suggested_reply TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute("PRAGMA table_info(feedback)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'sentiment' not in columns:
        cursor.execute("ALTER TABLE feedback ADD COLUMN sentiment TEXT DEFAULT 'NEUTRAL'")
    if 'translated_text' not in columns:
        cursor.execute("ALTER TABLE feedback ADD COLUMN translated_text TEXT")
    if 'suggested_reply' not in columns:
        cursor.execute("ALTER TABLE feedback ADD COLUMN suggested_reply TEXT")
    if 'event_id' not in columns:
        cursor.execute("ALTER TABLE feedback ADD COLUMN event_id INTEGER")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendees (
            phone_number TEXT PRIMARY KEY,
            anon_id TEXT,
            language TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS event_details (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            event_name TEXT NOT NULL,
            event_date TEXT NOT NULL,
            venue TEXT NOT NULL,
            location TEXT NOT NULL,
            organizer TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_name TEXT NOT NULL,
            event_date TEXT NOT NULL,
            venue TEXT NOT NULL,
            location TEXT NOT NULL,
            organizer TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS active_event (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            event_id INTEGER NOT NULL REFERENCES events(id)
        )
    ''')

    cursor.execute('SELECT event_id FROM active_event WHERE id = 1')
    active_event = cursor.fetchone()
    if active_event is None:
        cursor.execute('SELECT event_name, event_date, venue, location, organizer FROM event_details WHERE id = 1')
        initial_details = cursor.fetchone()
        if initial_details is None:
            initial_details = (
                os.getenv('BAGGA_EVENT_NAME', '').strip(),
                os.getenv('BAGGA_EVENT_DATE', '').strip(),
                os.getenv('BAGGA_EVENT_VENUE', '').strip(),
                os.getenv('BAGGA_EVENT_LOCATION', '').strip(),
                os.getenv('BAGGA_EVENT_ORGANIZER', '').strip()
            )
        cursor.execute('''
            INSERT INTO events (event_name, event_date, venue, location, organizer)
            VALUES (?, ?, ?, ?, ?)
        ''', initial_details)
        active_event_id = cursor.lastrowid
        cursor.execute('INSERT INTO active_event (id, event_id) VALUES (1, ?)', (active_event_id,))
    else:
        active_event_id = active_event[0]

    cursor.execute('UPDATE feedback SET event_id = ? WHERE event_id IS NULL', (active_event_id,))
    conn.commit()
    conn.close()

init_db()


def get_event_details(cursor):
    cursor.execute('''
        SELECT e.id, e.event_name, e.event_date, e.venue, e.location, e.organizer
        FROM active_event a
        JOIN events e ON e.id = a.event_id
        WHERE a.id = 1
    ''')
    return dict(cursor.fetchone())


def format_event_date(event_date):
    try:
        return datetime.strptime(event_date, '%Y-%m-%d').strftime('%d %B %Y')
    except (TypeError, ValueError):
        return event_date

USSD_TEXTS = {
    'en': {
        'select_category': "CON Select category:\n1. Praise\n2. Sound/Audio\n3. Facilities\n4. General Note",
        'type_message': "CON Type your message or feedback:",
        'thank_you': "END Thank you for your feedback! Bagga AI has recorded your note."
    },
    'lg': {
        'select_category': "CON Londa kategoria:\n1. Okusiima\n2. Edoboozi/Sound\n3. Eby'omukutu\n4. Ekirowoozo Eky'abulijjo",
        'type_message': "CON Wandiika ekyomukutu gwo oba ekyrowoozo kyolina:",
        'thank_you': "END Weebale nnyo okutuwa ekyrowoozo kyo! Bagga AI ekikutte."
    },
    'sw': {
        'select_category': "CON Chagua aina:\n1. Sifa\n2. Sauti/Mfumo\n3. Vifaa/Majengo\n4. Wazo la Kawaida",
        'type_message': "CON Andika ujumbe au maoni yako:",
        'thank_you': "END Asante kwa kutoa maoni yako! Bagga AI imerekodi ujumbe wako."
    }
}

CATEGORIES = {
    '1': 'PRAISE',
    '2': 'SOUND/AUDIO',
    '3': 'AC/FACILITIES',
    '4': 'GENERAL'
}

@app.route('/ussd', methods=['POST', 'GET'])
@app.route('/api/ussd', methods=['POST', 'GET'])
def ussd_callback():
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "").strip()

    user_inputs = text.split('*') if text else []

    if text == "":
        response = "CON Welcome to Bagga AI!\nChoose Language / Londa Lulimi:\n1. English\n2. Luganda\n3. Swahili"
        return Response(response, mimetype='text/plain')

    lang_choice = user_inputs[0]
    lang_map = {'1': 'en', '2': 'lg', '3': 'sw'}
    selected_lang = lang_map.get(lang_choice, 'en')

    if len(user_inputs) == 1:
        if lang_choice not in lang_map:
            return Response("END Invalid option. Please dial again.", mimetype='text/plain')
        response = USSD_TEXTS[selected_lang]['select_category']
        return Response(response, mimetype='text/plain')

    if len(user_inputs) == 2:
        response = USSD_TEXTS[selected_lang]['type_message']
        return Response(response, mimetype='text/plain')

    if len(user_inputs) == 3:
        category_code = user_inputs[1]
        raw_category = CATEGORIES.get(category_code, 'GENERAL')
        raw_text = user_inputs[2]

        ai_res = analyze_feedback(raw_text, language=selected_lang)
        final_category = ai_res.get('category', raw_category)
        urgency = ai_res.get('urgency', 'NORMAL')
        sentiment = ai_res.get('sentiment', 'NEUTRAL')
        translated_text = ai_res.get('translated_text', raw_text)
        suggested_reply = ai_res.get('suggested_reply', 'Thank you for your feedback!')

        anon_id = f"Attendee#{phone_number[-4:]}" if len(phone_number) >= 4 else "Attendee#0000"

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO attendees (phone_number, anon_id, language)
            VALUES (?, ?, ?)
            ON CONFLICT(phone_number) DO UPDATE SET language=excluded.language
        ''', (phone_number, anon_id, selected_lang))

        cursor.execute('SELECT event_id FROM active_event WHERE id = 1')
        event_id = cursor.fetchone()[0]

        cursor.execute('''
            INSERT INTO feedback (event_id, phone_number, anon_id, channel, category, raw_text, language, urgency, sentiment, translated_text, suggested_reply)
            VALUES (?, ?, ?, 'USSD', ?, ?, ?, ?, ?, ?, ?)
        ''', (event_id, phone_number, anon_id, final_category, raw_text, selected_lang, urgency, sentiment, translated_text, suggested_reply))

        conn.commit()
        conn.close()

        response = USSD_TEXTS[selected_lang]['thank_you']
        return Response(response, mimetype='text/plain')

    return Response("END Invalid interaction. Please try again.", mimetype='text/plain')

@app.route('/', methods=['GET'])
@app.route('/dashboard', methods=['GET'])
def dashboard():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    event_details = get_event_details(cursor)
    event_id = event_details['id']

    cursor.execute('SELECT COUNT(*) FROM feedback WHERE event_id = ?', (event_id,))
    total_feedback_count = cursor.fetchone()[0]

    cursor.execute('SELECT * FROM feedback WHERE event_id = ? ORDER BY id DESC', (event_id,))
    feedbacks = [dict(row) for row in cursor.fetchall()]

    cursor.execute('''
        SELECT a.phone_number, a.anon_id, a.language, COUNT(f.id) as feedback_count
        FROM attendees a
        JOIN feedback f ON a.phone_number = f.phone_number
        WHERE f.event_id = ?
        GROUP BY a.phone_number
        ORDER BY MAX(f.id) DESC
    ''', (event_id,))
    attendees = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) FROM feedback WHERE event_id = ? AND urgency = 'HIGH'", (event_id,))
    high_urgency = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM feedback WHERE event_id = ? AND sentiment = 'POSITIVE'", (event_id,))
    positive_sentiment = cursor.fetchone()[0] or 0

    non_high_urgency_rate = 100 if total_feedback_count == 0 else round(((total_feedback_count - high_urgency) / total_feedback_count) * 100, 1)

    stats = {
        'total_feedback': total_feedback_count,
        'high_urgency': high_urgency,
        'positive_sentiment': positive_sentiment,
        'non_high_urgency_rate': non_high_urgency_rate
    }

    conn.close()
    return render_template(
        'dashboard.html',
        feedbacks=feedbacks,
        attendees=attendees,
        stats=stats,
        event_details=event_details
    )


@app.route('/api/organizer/event-details', methods=['POST'])
def save_event_details():
    event_details = {
        'event_name': request.form.get('event_name', '').strip(),
        'event_date': request.form.get('event_date', '').strip(),
        'venue': request.form.get('venue', '').strip(),
        'location': request.form.get('location', '').strip(),
        'organizer': request.form.get('organizer', '').strip()
    }
    if not all(event_details.values()):
        return redirect(url_for('dashboard', event_status='incomplete'))

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT event_id FROM active_event WHERE id = 1')
    event_id = cursor.fetchone()[0]
    cursor.execute('''
        UPDATE events
        SET event_name = ?, event_date = ?, venue = ?, location = ?, organizer = ?
        WHERE id = ?
    ''', (*event_details.values(), event_id))
    conn.commit()
    conn.close()

    return redirect(url_for('dashboard', event_status='saved'))


@app.route('/api/organizer/events/new', methods=['POST'])
def start_new_event():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO events (event_name, event_date, venue, location, organizer)
        VALUES ('', '', '', '', '')
    ''')
    event_id = cursor.lastrowid
    cursor.execute('UPDATE active_event SET event_id = ? WHERE id = 1', (event_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('dashboard', event_status='new'))


@app.route('/api/feedback/<int:feedback_id>/translate', methods=['POST'])
def translate_feedback(feedback_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        'SELECT raw_text, language, translated_text FROM feedback WHERE id = ?',
        (feedback_id,)
    )
    feedback = cursor.fetchone()

    if not feedback:
        conn.close()
        return jsonify(error='Feedback not found.'), 404

    raw_text, language, translated_text = feedback
    if language not in ('lg', 'sw'):
        conn.close()
        return jsonify(error='Only Luganda and Kiswahili feedback can be translated here.'), 400

    if translated_text and translated_text.strip() != raw_text.strip():
        conn.close()
        return jsonify(translated_text=translated_text)

    translated_text = translate_to_english(raw_text, language)
    if not translated_text:
        conn.close()
        return jsonify(error='Translation service is unavailable. Check the internet connection and try again.'), 503

    cursor.execute(
        'UPDATE feedback SET translated_text = ? WHERE id = ?',
        (translated_text, feedback_id)
    )
    conn.commit()
    conn.close()
    return jsonify(translated_text=translated_text)

# ==========================================
# B2B EXECUTIVE PDF REPORT ROUTE
# ==========================================
@app.route('/report/pdf', methods=['GET'])
def generate_pdf_report():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    event_details = get_event_details(cursor)
    event_id = event_details['id']

    cursor.execute('SELECT COUNT(*) FROM feedback WHERE event_id = ?', (event_id,))
    total_notes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM feedback WHERE event_id = ? AND urgency = 'HIGH'", (event_id,))
    high_urgency = cursor.fetchone()[0] or 0

    cursor.execute('SELECT COUNT(DISTINCT phone_number) FROM feedback WHERE event_id = ?', (event_id,))
    total_attendees = cursor.fetchone()[0]

    cursor.execute('SELECT * FROM feedback WHERE event_id = ? ORDER BY urgency DESC, id DESC', (event_id,))
    feedbacks = [dict(row) for row in cursor.fetchall()]

    conn.close()

    generated_at = datetime.now(timezone.utc).strftime('%B %d, %Y %H:%M UTC')
    high_urgency_rate = round((high_urgency / total_notes) * 100, 1) if total_notes else 0

    return render_template(
        'report_pdf.html',
        feedbacks=feedbacks,
        total_notes=total_notes,
        high_urgency=high_urgency,
        total_attendees=total_attendees,
        high_urgency_rate=high_urgency_rate,
        generated_at=generated_at,
        event_name=event_details['event_name'],
        event_date=format_event_date(event_details['event_date']),
        event_venue=event_details['venue'],
        event_location=event_details['location'],
        event_organizer=event_details['organizer']
    )

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
    cursor.execute('SELECT event_id FROM active_event WHERE id = 1')
    event_id = cursor.fetchone()[0]
    cursor.execute('SELECT DISTINCT phone_number FROM feedback WHERE event_id = ?', (event_id,))
    numbers = cursor.fetchall()
    conn.close()

    for row in numbers:
        print(f"[BROADCAST SMS] To: {row[0]} | Message: {thank_you_message}")

    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)