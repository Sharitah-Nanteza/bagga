import datetime
import os
import random
import string

import africastalking
import requests
from dotenv import load_dotenv
from flask import Blueprint, jsonify, request
from pymongo import MongoClient

# Load environment variables
load_dotenv()

username = os.getenv("AT_USERNAME")
api_key = os.getenv("AT_API_KEY")
mongo_uri = os.getenv("MONGO_URI")

# Initialize Africa's Talking
if username and api_key:
    africastalking.initialize(username, api_key)
sms = africastalking.SMS

# Initialize MongoDB
if mongo_uri:
    mongo_client = MongoClient(mongo_uri)
    db = mongo_client["event_command_center"]
    guests_collection = db["guests"]
    event_collection = db["event_config"]
    ushers_collection = db["ushers"]
    tasks_collection = db["tasks"]
    contributions_collection = db["contributions"]
else:
    mongo_client = None
    db = None
    guests_collection = None
    event_collection = None
    ushers_collection = None
    tasks_collection = None
    contributions_collection = None

PAYMENT_PRODUCT_NAME = "EventContributions"
PAYMENTS_SANDBOX_URL = "https://payments.sandbox.africastalking.com/mobile/checkout/request"

feedback_bp = Blueprint("feedback_bp", __name__)


def get_event_config():
    """Fetch the current event's location and date settings from MongoDB."""
    if event_collection is None:
        return None
    config = event_collection.find_one({"_id": "current_event"})
    return config


def generate_code(length=6):
    """Generate a random alphanumeric code, e.g. 'A1B2C3'."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


def geocode_location(location_name):
    """
    Convert a place name (e.g. 'Kampala, Uganda') into latitude/longitude
    using Open-Meteo's free geocoding API (no API key needed).
    Returns (lat, lon, resolved_name) or (None, None, None) if not found.
    """
    try:
        url = "https://geocoding-api.open-meteo.com/v1/search"
        params = {"name": location_name, "count": 1}
        response = requests.get(url, params=params, timeout=5)
        data = response.json()

        results = data.get("results")
        if not results:
            return None, None, None

        result = results[0]
        lat = result["latitude"]
        lon = result["longitude"]
        resolved_name = f"{result.get('name')}, {result.get('country', '')}".strip(", ")
        return lat, lon, resolved_name

    except Exception as e:
        print("Geocoding failed:", e)
        return None, None, None


def get_weather_blurb():
    """
    Fetch the forecast for the currently configured event location/date
    from Open-Meteo and return a short SMS-friendly summary.
    Returns an empty string if no event is configured yet, or if the lookup fails.
    """
    config = get_event_config()
    if not config:
        return ""

    try:
        url = "https://api.open-meteo.com/v1/forecast"
        params = {
            "latitude": config["lat"],
            "longitude": config["lon"],
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
            "start_date": config["date"],
            "end_date": config["date"],
        }
        response = requests.get(url, params=params, timeout=5)
        data = response.json()

        daily = data.get("daily", {})
        max_temp = daily.get("temperature_2m_max", [None])[0]
        min_temp = daily.get("temperature_2m_min", [None])[0]
        rain_chance = daily.get("precipitation_probability_max", [None])[0]

        if max_temp is None:
            return ""

        blurb = f"Weather in {config['location_name']} on event day: {min_temp}-{max_temp}°C"
        if rain_chance is not None:
            blurb += f", {rain_chance}% chance of rain"
        return blurb

    except Exception as e:
        print("Weather lookup failed:", e)
        return ""


def request_mobile_checkout(phone_number, amount, currency_code="UGX"):
    """
    Trigger a mobile money payment prompt using Africa's Talking Payments REST API directly.
    """
    headers = {
        "apiKey": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    payload = {
        "username": username,
        "productName": PAYMENT_PRODUCT_NAME,
        "phoneNumber": phone_number,
        "currencyCode": currency_code,
        "amount": amount
    }
    response = requests.post(PAYMENTS_SANDBOX_URL, json=payload, headers=headers, timeout=10)
    return response.json()


@feedback_bp.route('/')
def home():
    return jsonify({"message": "Event Command Center backend is running."})


@feedback_bp.route('/event', methods=['POST'])
def set_event():
    """
    Set (or update) the event's location and date.
    Expects JSON: { "location": "Kampala, Uganda", "date": "2026-09-26" }
    """
    data = request.get_json()

    if not data or 'location' not in data or 'date' not in data:
        return jsonify({"error": "Missing 'location' or 'date' in request"}), 400

    location_name_input = data['location']
    date = data['date']

    lat, lon, resolved_name = geocode_location(location_name_input)

    if lat is None:
        return jsonify({"error": f"Could not find coordinates for '{location_name_input}'"}), 404

    event_collection.update_one(
        {"_id": "current_event"},
        {"$set": {
            "location_name": resolved_name,
            "lat": lat,
            "lon": lon,
            "date": date
        }},
        upsert=True
    )

    return jsonify({
        "message": "Event location and date saved.",
        "location_name": resolved_name,
        "lat": lat,
        "lon": lon,
        "date": date
    }), 200


@feedback_bp.route('/event', methods=['GET'])
def view_event():
    """View the currently configured event location and date."""
    config = get_event_config()
    if not config:
        return jsonify({"message": "No event configured yet. POST to /event first."}), 404
    config.pop("_id", None)
    return jsonify(config), 200


@feedback_bp.route('/guests', methods=['POST'])
def register_guest():
    """
    Register a new guest and send them an SMS invite with their unique code.
    Expects JSON: { "name": "Jane Doe", "phone": "+254712345678" }
    """
    data = request.get_json()

    if not data or 'name' not in data or 'phone' not in data:
        return jsonify({"error": "Missing 'name' or 'phone' in request"}), 400

    name = data['name']
    phone = data['phone']

    code = generate_code()
    while guests_collection.find_one({"code": code}):
        code = generate_code()

    guest = {
        "name": name,
        "phone": phone,
        "code": code,
        "checked_in": False,
        "checked_in_at": None,
        "checked_in_by": None
    }
    guests_collection.insert_one(guest)

    message = f"Hi {name}, you're invited! Your check-in code is: {code}"

    weather = get_weather_blurb()
    if weather:
        message += f". {weather}"

    try:
        sms_response = sms.send(message, [phone])
    except Exception as e:
        return jsonify({"error": f"Guest saved but SMS failed: {str(e)}"}), 500

    return jsonify({
        "message": "Guest registered and invite sent.",
        "guest": {k: v for k, v in guest.items() if k != "_id"},
        "sms_response": sms_response
    }), 201


@feedback_bp.route('/guests', methods=['GET'])
def list_guests():
    """Return all registered guests (for the organizer dashboard)."""
    all_guests = list(guests_collection.find({}, {"_id": 0}))
    return jsonify(all_guests)


@feedback_bp.route('/reminders', methods=['POST'])
def send_reminders():
    """
    Send a reminder SMS (with current weather forecast) to all registered guests.
    """
    all_guests = list(guests_collection.find({}, {"_id": 0}))

    if not all_guests:
        return jsonify({"message": "No guests to remind."}), 200

    weather = get_weather_blurb()
    results = []

    for guest in all_guests:
        code = guest['code']
        message = f"Reminder: don't forget the event! Your check-in code is {code}."
        if weather:
            message += f" {weather}"
        try:
            sms_response = sms.send(message, [guest['phone']])
            results.append({"guest": guest['name'], "status": "sent", "response": sms_response})
        except Exception as e:
            results.append({"guest": guest['name'], "status": "failed", "error": str(e)})

    return jsonify({"message": "Reminders processed.", "results": results}), 200


@feedback_bp.route('/ushers', methods=['POST'])
def register_usher():
    """
    Register an usher and assign them a duty post. Sends an SMS notification.
    Expects JSON: { "name": "Grace", "phone": "+254712345678", "post": "Main Entrance" }
    """
    data = request.get_json()

    if not data or 'name' not in data or 'phone' not in data or 'post' not in data:
        return jsonify({"error": "Missing 'name', 'phone', or 'post' in request"}), 400

    name = data['name']
    phone = data['phone']
    post = data['post']

    usher = {
        "name": name,
        "phone": phone,
        "post": post,
        "status": "assigned"
    }
    ushers_collection.insert_one(usher)

    message = f"Hi {name}, you're assigned to: {post} for the event. See you there!"
    try:
        sms_response = sms.send(message, [phone])
    except Exception as e:
        return jsonify({"error": f"Usher saved but SMS failed: {str(e)}"}), 500

    return jsonify({
        "message": "Usher registered and notified.",
        "usher": {k: v for k, v in usher.items() if k != "_id"},
        "sms_response": sms_response
    }), 201


@feedback_bp.route('/ushers', methods=['GET'])
def list_ushers():
    """Return all registered ushers (for the organizer dashboard)."""
    all_ushers = list(ushers_collection.find({}, {"_id": 0}))
    return jsonify(all_ushers)


@feedback_bp.route('/tasks', methods=['POST'])
def assign_task():
    """
    Assign a task to an usher by phone number. Sends an SMS notification
    with a task code.
    Expects JSON: { "title": "Set up registration desk", "usher_phone": "+254712345678", "due_time": "9:00 AM" }
    """
    data = request.get_json()

    if not data or 'title' not in data or 'usher_phone' not in data:
        return jsonify({"error": "Missing 'title' or 'usher_phone' in request"}), 400

    title = data['title']
    usher_phone = data['usher_phone']
    due_time = data.get('due_time', 'ASAP')

    usher = ushers_collection.find_one({"phone": usher_phone})
    usher_name = usher['name'] if usher else 'Unknown'

    task_code = generate_code(4)
    while tasks_collection.find_one({"code": task_code}):
        task_code = generate_code(4)

    task = {
        "code": task_code,
        "title": title,
        "usher_phone": usher_phone,
        "usher_name": usher_name,
        "due_time": due_time,
        "status": "pending"
    }
    tasks_collection.insert_one(task)

    message = f"Task assigned: {title} (due: {due_time}). Task code: {task_code}"
    try:
        sms_response = sms.send(message, [usher_phone])
    except Exception as e:
        return jsonify({"error": f"Task saved but SMS failed: {str(e)}"}), 500

    return jsonify({
        "message": "Task assigned and usher notified.",
        "task": {k: v for k, v in task.items() if k != "_id"},
        "sms_response": sms_response
    }), 201


@feedback_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """Return all tasks (for the organizer dashboard progress view)."""
    all_tasks = list(tasks_collection.find({}, {"_id": 0}))
    return jsonify(all_tasks)


@feedback_bp.route('/tasks/complete', methods=['POST'])
def complete_task():
    """
    Mark a task as done using its task code.
    Expects JSON: { "code": "A1B2" }
    """
    data = request.get_json()

    if not data or 'code' not in data:
        return jsonify({"error": "Missing 'code' in request"}), 400

    code = data['code'].upper()
    task = tasks_collection.find_one({"code": code})

    if not task:
        return jsonify({"status": "not_found", "message": "No task found with this code."}), 404

    if task['status'] == 'done':
        return jsonify({"status": "already_done", "message": "This task was already marked done."}), 200

    tasks_collection.update_one({"code": code}, {"$set": {"status": "done"}})
    updated_task = tasks_collection.find_one({"code": code}, {"_id": 0})

    return jsonify({
        "status": "success",
        "message": f"Task '{updated_task['title']}' marked as done.",
        "task": updated_task
    }), 200


@feedback_bp.route('/contributions', methods=['POST'])
def make_contribution():
    """
    Record a contribution and send an SMS receipt.
    Expects JSON: { "name": "Jane Doe", "phone": "+254712345678", "amount": 5000, "currency": "UGX" }
    """
    data = request.get_json()

    if not data or 'name' not in data or 'phone' not in data or 'amount' not in data:
        return jsonify({"error": "Missing 'name', 'phone', or 'amount' in request"}), 400

    name = data['name']
    phone = data['phone']
    amount = data['amount']
    currency = data.get('currency', 'UGX')

    contribution = {
        "name": name,
        "phone": phone,
        "amount": amount,
        "currency": currency
    }
    contributions_collection.insert_one(contribution)

    receipt = f"Hi {name}, your contribution of {amount} {currency} has been recorded. Thank you!"
    try:
        sms_response = sms.send(receipt, [phone])
    except Exception as e:
        return jsonify({
            "message": "Contribution recorded, but SMS receipt failed.",
            "contribution": {k: v for k, v in contribution.items() if k != "_id"},
            "sms_error": str(e)
        }), 201

    return jsonify({
        "message": "Contribution recorded and SMS receipt sent.",
        "contribution": {k: v for k, v in contribution.items() if k != "_id"},
        "sms_response": sms_response
    }), 201


@feedback_bp.route('/contributions', methods=['GET'])
def list_contributions():
    """Return all contributions and a running total, for the budget dashboard."""
    all_contributions = list(contributions_collection.find({}, {"_id": 0}))
    total = sum(c.get('amount', 0) for c in all_contributions)
    return jsonify({
        "contributions": all_contributions,
        "total": total
    })


@feedback_bp.route('/checkin', methods=['POST'])
def checkin():
    """
    Check in a guest using their code.
    Expects JSON: { "code": "A1B2C3", "usher": "Usher Name" }
    """
    data = request.get_json()

    if not data or 'code' not in data:
        return jsonify({"error": "Missing 'code' in request"}), 400

    code = data['code'].upper()
    usher = data.get('usher', 'Unknown')

    guest = guests_collection.find_one({"code": code})

    if not guest:
        return jsonify({"status": "not_found", "message": "No guest found with this code."}), 404

    if guest['checked_in']:
        return jsonify({
            "status": "duplicate",
            "message": f"Already checked in at {guest['checked_in_at']}.",
            "guest": {k: v for k, v in guest.items() if k != "_id"}
        }), 409

    checked_in_at = datetime.datetime.now().strftime("%H:%M:%S")

    guests_collection.update_one(
        {"code": code},
        {"$set": {
            "checked_in": True,
            "checked_in_at": checked_in_at,
            "checked_in_by": usher
        }}
    )

    updated_guest = guests_collection.find_one({"code": code}, {"_id": 0})

    return jsonify({
        "status": "success",
        "message": f"{updated_guest['name']} checked in successfully.",
        "guest": updated_guest
    }), 200


@feedback_bp.route('/api/ussd', methods=['POST'])
def ussd_callback():
    session_id = request.values.get("sessionId", "")
    service_code = request.values.get("serviceCode", "")
    phone_number = request.values.get("phoneNumber", "")
    text = request.values.get("text", "").strip()

    anon_id = f"Attendee#{hashlib.md5(phone_number.encode()).hexdigest()[:6].upper()}"

    if text == "":
        response = "CON Welcome to Bagga Whisper (100% Anonymous)\n"
        response += "1. Report Audio/Sound Issue\n"
        response += "2. Report Venue/AC Issue\n"
        response += "3. Send Praise / Shout-out\n"
        response += "4. Custom Feedback Note\n"
        response += "5. 🎙️ Record Voice Note Instead"
        return response, 200, {'Content-Type': 'text/plain'}

    if text == "5":
        return "END 🎙️ Prefer speaking? Call our Hotline at +256-800-WHISPER to leave a voice recording after the beep!", 200, {'Content-Type': 'text/plain'}

    if text == "1":
        return "CON Please type details of the Audio/Sound issue:", 200, {'Content-Type': 'text/plain'}

    if text == "2":
        return "CON Please describe the Venue/AC/Safety issue:", 200, {'Content-Type': 'text/plain'}

    if text == "3":
        return "CON Type your praise or shout-out note:", 200, {'Content-Type': 'text/plain'}

    if text == "4":
        return "CON Type your detailed feedback note:", 200, {'Content-Type': 'text/plain'}

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

    ai_result = analyze_feedback(raw_text)

    if category_hint:
        ai_result["category"] = category_hint

    save_feedback(
        anon_id=anon_id,
        channel="USSD",
        raw_text=raw_text,
        category=ai_result.get("category", "GENERAL"),
        urgency=ai_result.get("urgency", "MEDIUM")
    )

    response = "END Thank you! Your anonymous feedback has been logged securely."
    return response, 200, {'Content-Type': 'text/plain'}


@feedback_bp.route("/api/voice_web", methods=["POST"])
def voice_web_callback():
    data = request.get_json(silent=True) or {}
    note = data.get("note", "").strip()

    if not note:
        return jsonify({"status": "error", "message": "No note provided"}), 400

    anon_id = f"Attendee#{hashlib.md5('web-user'.encode()).hexdigest()[:6].upper()}"
    ai_res = analyze_feedback(note)
    save_feedback(
        anon_id=anon_id,
        channel="WEB",
        raw_text=note,
        category=ai_res.get("category", "GENERAL"),
        urgency=ai_res.get("urgency", "MEDIUM")
    )

    return jsonify({"status": "success", "message": "Feedback submitted anonymously."}), 200


@feedback_bp.route("/api/voice", methods=["POST"])
def voice_callback():
    phone_number = request.values.get("callerNumber", "")
    recording_url = request.values.get("recordingUrl", "")
    anon_id = f"Attendee#{hashlib.md5(phone_number.encode()).hexdigest()[:6].upper()}"

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


@feedback_bp.route('/api/feedback/reward', methods=['POST'])
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


# NOTE: This module is mounted by the main app; it intentionally does not start a separate server here.