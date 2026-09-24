import os
import hashlib
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv
import africastalking

from database import init_db, save_feedback, get_all_feedback
from ai_engine import analyze_feedback

load_dotenv()
init_db()

app = Flask(__name__)

# Initialize Africa's Talking SDK safely
AT_USERNAME = os.getenv("AT_USERNAME", "sandbox")
AT_API_KEY = os.getenv("AT_API_KEY", "")

airtime = None
if AT_API_KEY and AT_API_KEY != "your_africas_talking_api_key_here":
    try:
        africastalking.initialize(AT_USERNAME, AT_API_KEY)
        airtime = africastalking.Airtime
        print("[AT SDK] Initialized successfully.")
    except Exception as e:
        print(f"[AT SDK] Initialization error: {e}")
else:
    print("[AT SDK] Running in Offline Sandbox Mode (No API key set).")

def anonymize_phone(phone_number):
    """Hashes phone number to guarantee 100% attendee privacy."""
    if not phone_number:
        return "Attendee#00000"
    return "Attendee#" + hashlib.md5(phone_number.encode()).hexdigest()[:5].upper()

# --- 1. ORGANIZER DASHBOARD ROUTE ---
@app.route("/")
def dashboard():
    feedbacks = get_all_feedback()
    return render_template("dashboard.html", feedbacks=feedbacks)

# --- 2. USSD CALLBACK HANDLER (*384*...#) ---
@app.route("/api/ussd", methods=["POST"])
def ussd_callback():
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "")
    anon_id = anonymize_phone(phone_number)

    if text == "":
        response = "CON Welcome to Bagga Whisper (100% Anonymous)\n"
        response += "1. Report Audio/Sound Issue\n"
        response += "2. Report Venue/AC Issue\n"
        response += "3. Send Praise / Shout-out\n"
        response += "4. Custom Feedback Note"
    elif text == "1":
        save_feedback(anon_id, "USSD", "Audio/Mic Issue reported via USSD quick option", "AUDIO_LOGISTICS", "HIGH", "NEGATIVE")
        response = f"END Thank you {anon_id}. Your audio report has been flagged to organizers!"
    elif text == "2":
        save_feedback(anon_id, "USSD", "Venue Temperature Issue reported via USSD quick option", "VENUE_TEMPERATURE", "MEDIUM", "NEGATIVE")
        response = f"END Thank you {anon_id}. Your venue report has been flagged!"
    elif text == "3":
        save_feedback(anon_id, "USSD", "Praise/Shout-out sent via USSD quick option", "PRAISE", "LOW", "POSITIVE")
        response = f"END Thank you {anon_id}! Your praise was added to the Wall of Praise."
    elif text == "4":
        response = "CON Type your short feedback note:"
    elif text.startswith("4*"):
        custom_note = text.split("*", 1)[1]
        ai_res = analyze_feedback(custom_note)
        save_feedback(
            anon_id=anon_id,
            channel="USSD",
            raw_text=custom_note,
            category=ai_res.get("category", "GENERAL"),
            urgency=ai_res.get("urgency", "LOW"),
            sentiment=ai_res.get("sentiment", "NEUTRAL")
        )
        response = f"END Thank you {anon_id}. Your feedback was analyzed and logged!"
    else:
        response = "END Invalid selection."

    return response, 200, {"Content-Type": "text/plain"}

# --- 3. VOICE RECORDING CALLBACK ---
@app.route("/api/voice", methods=["POST"])
def voice_callback():
    phone_number = request.values.get("callerNumber", "")
    recording_url = request.values.get("recordingUrl", "")
    anon_id = anonymize_phone(phone_number)

    if recording_url:
        note_text = f"Voice Note Recording: {recording_url}"
        ai_res = analyze_feedback("Voice feedback left on hotline")
        save_feedback(anon_id, "VOICE", note_text, ai_res.get("category"), ai_res.get("urgency"), ai_res.get("sentiment"))

    xml_response = '<?xml version="1.0" encoding="UTF-8"?>'
    xml_response += '<Response>'
    xml_response += '<Say>Welcome to Bagga Whisper. Leave your anonymous feedback after the beep.</Say>'
    xml_response += '<Record finishOnKey="#" maxLength="10" trimSilence="true"/>'
    xml_response += '</Response>'

    return xml_response, 200, {"Content-Type": "application/xml"}

# --- 4. AIRTIME REWARD ENDPOINT ---
@app.route("/api/reward", methods=["POST"])
def send_airtime_reward():
    data = request.json or {}
    phone_number = data.get("phone_number")
    amount = data.get("amount", "500")

    if not phone_number:
        return jsonify({"status": "error", "message": "Phone number required"}), 400

    if not airtime:
        return jsonify({"status": "simulated", "message": f"Simulated {amount} UGX reward to {phone_number} (Add AT_API_KEY to .env for live transfer)."}), 200

    try:
        recipients = [{"phoneNumber": phone_number, "currencyCode": "UGX", "amount": amount}]
        res = airtime.send(recipients=recipients)
        return jsonify({"status": "success", "response": res})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(port=5000, debug=True)
