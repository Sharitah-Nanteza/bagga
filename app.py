import os
import sqlite3
import csv
import io
from flask import Flask, request, Response, render_template, redirect, url_for, make_response
from ai_engine import analyze_feedback

app = Flask(__name__)
DB_NAME = "bagga.db"

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

        cursor.execute('''
            INSERT INTO feedback (phone_number, anon_id, channel, category, raw_text, language, urgency, sentiment, translated_text, suggested_reply)
            VALUES (?, ?, 'USSD', ?, ?, ?, ?, ?, ?, ?)
        ''', (phone_number, anon_id, final_category, raw_text, selected_lang, urgency, sentiment, translated_text, suggested_reply))

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

    cursor.execute('SELECT COUNT(*) FROM feedback')
    total_feedback_count = cursor.fetchone()[0]

    cursor.execute('SELECT * FROM feedback ORDER BY id DESC')
    feedbacks = [dict(row) for row in cursor.fetchall()]

    cursor.execute('''
        SELECT a.phone_number, a.anon_id, a.language, COUNT(f.id) as feedback_count
        FROM attendees a
        LEFT JOIN feedback f ON a.phone_number = f.phone_number
        GROUP BY a.phone_number
        ORDER BY a.created_at DESC
    ''')
    attendees = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT COUNT(*) FROM feedback WHERE urgency = 'HIGH'")
    high_urgency = cursor.fetchone()[0] or 0

    cursor.execute("SELECT COUNT(*) FROM feedback WHERE sentiment = 'POSITIVE'")
    positive_sentiment = cursor.fetchone()[0] or 0

    uptime_rate = 100 if total_feedback_count == 0 else round(((total_feedback_count - high_urgency) / total_feedback_count) * 100, 1)

    stats = {
        'total_feedback': total_feedback_count,
        'high_urgency': high_urgency,
        'positive_sentiment': positive_sentiment,
        'uptime_rate': uptime_rate
    }

    conn.close()
    return render_template('dashboard.html', feedbacks=feedbacks, attendees=attendees, stats=stats)

# ==========================================
# B2B EXECUTIVE PDF REPORT ROUTE
# ==========================================
@app.route('/report/pdf', methods=['GET'])
def generate_pdf_report():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM feedback')
    total_notes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM feedback WHERE urgency = 'HIGH'")
    high_urgency = cursor.fetchone()[0] or 0

    cursor.execute('SELECT COUNT(*) FROM attendees')
    total_attendees = cursor.fetchone()[0]

    uptime_rate = 100 if total_notes == 0 else round(((total_notes - high_urgency) / total_notes) * 100, 1)

    cursor.execute('SELECT * FROM feedback ORDER BY urgency DESC, id DESC')
    feedbacks = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return render_template(
        'report_pdf.html',
        feedbacks=feedbacks,
        total_notes=total_notes,
        high_urgency=high_urgency,
        total_attendees=total_attendees,
        uptime_rate=uptime_rate
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
    cursor.execute('SELECT phone_number FROM attendees')
    numbers = cursor.fetchall()
    conn.close()

    for row in numbers:
        print(f"[BROADCAST SMS] To: {row[0]} | Message: {thank_you_message}")

    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)