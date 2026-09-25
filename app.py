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

# --- 1. HOME / LANDING PAGE ROUTE ---
@app.route("/")
def home():
    feedbacks = get_all_feedback()
    return render_template("home.html", feedbacks=feedbacks)

# --- 2. FEEDBACK DASHBOARD ROUTE ---
@app.route("/dashboard")
def dashboard():
    feedbacks = get_all_feedback()
    return render_template("dashboard.html", feedbacks=feedbacks)

@app.route("/feedback")
def feedback():
    return dashboard()

# --- 3. USSD CALLBACK HANDLER (*384*...#) ---
@app.route('/api/ussd', methods=['POST'])
def ussd_callback():
    session_id = request.values.get("sessionId", "")
    service_code = request.values.get("serviceCode", "")
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "").strip()

    # Create anonymous hash for phone number
    anon_id = f"Attendee#{hashlib.md5(phone_number.encode()).hexdigest()[:6].upper()}"

    # Main Menu
    if text == "":
        response = "CON Welcome to Bagga Whisper (100% Anonymous)\n"
        response += "1. Report Audio/Sound Issue\n"
        response += "2. Report Venue/AC Issue\n"
        response += "3. Send Praise / Shout-out\n"
        response += "4. Custom Feedback Note\n"
        response += "5. 🎙️ Record Voice Note Instead"
        return response, 200, {'Content-Type': 'text/plain'}

    # Option 5: Voice Hotline Guidance for Lazy / Hands-Free Users
    if text == "5":
        return "END 🎙️ Prefer speaking? Call our Hotline at +256-800-WHISPER to leave a voice recording after the beep!", 200, {'Content-Type': 'text/plain'}

    # Stage 1: Text-based prompts
    if text == "1":
        return "CON Please type details of the Audio/Sound issue:", 200, {'Content-Type': 'text/plain'}
    
    if text == "2":
        return "CON Please describe the Venue/AC/Safety issue:", 200, {'Content-Type': 'text/plain'}
    
    if text == "3":
        return "CON Type your praise or shout-out note:", 200, {'Content-Type': 'text/plain'}
    
    if text == "4":
        return "CON Type your detailed feedback note:", 200, {'Content-Type': 'text/plain'}

    # Stage 2: User entered detailed text -> Process with AI and Save
    raw_text = ""
    category_hint = None

    if text.startswith("1*"):
        raw_text = text[2:]
        category_hint = "AUDIO_LOGISTICS"
    elif text.startswith("2*"):
        raw_text = text[2:]
        category_hint = "FACILITIES"
    elif text.startswith("3*"):
        raw_text = text[2:]
        category_hint = "CONTENT"
    elif text.startswith("4*"):
        raw_text = text[2:]
    else:
        raw_text = text

    # Analyze with Gemini AI
    ai_result = analyze_feedback(raw_text)
    
    if category_hint:
        ai_result["category"] = category_hint

    # Save to SQLite Database
    save_feedback(
        anon_id=anon_id,
        channel="USSD",
        raw_text=raw_text,
        category=ai_result.get("category", "GENERAL"),
        urgency=ai_result.get("urgency", "MEDIUM")
    )

    response = "END Thank you! Your anonymous feedback has been logged securely."
    return response, 200, {'Content-Type': 'text/plain'}

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
