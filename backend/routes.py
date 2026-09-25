import datetime
import hashlib
import os
import random
import secrets
import string

import africastalking
import requests
from dotenv import load_dotenv
from flask import Blueprint, jsonify, request, session
from pymongo import MongoClient
from werkzeug.security import generate_password_hash

from ai_engine import analyze_feedback
from database import get_all_feedback, save_feedback

# Load environment variables
load_dotenv()

username = os.getenv("AT_USERNAME")
api_key = os.getenv("AT_API_KEY")
mongo_uri = os.getenv("MONGO_URI")

# Initialize Africa's Talking
if username and api_key:
    africastalking.initialize(username, api_key)
sms = africastalking.SMS
airtime = africastalking.Airtime

# Initialize MongoDB
if mongo_uri:
    mongo_client = MongoClient(mongo_uri)
    db = mongo_client["event_command_center"]
    guests_collection = db["guests"]
    event_collection = db["event_config"]
    ushers_collection = db["ushers"]
    tasks_collection = db["tasks"]
    contributions_collection = db["contributions"]
    users_collection = db["users"]
    organisers_collection = db["organisers"]
    bookings_collection = db["bookings"]
else:
    mongo_client = None
    db = None
    guests_collection = None
    event_collection = None
    ushers_collection = None
    tasks_collection = None
    contributions_collection = None
    users_collection = None
    organisers_collection = None
    bookings_collection = None

PAYMENT_PRODUCT_NAME = "EventContributions"
PAYMENTS_SANDBOX_URL = "https://payments.sandbox.africastalking.com/mobile/checkout/request"

feedback_bp = Blueprint("feedback_bp", __name__)

EVENT_TYPES = ["wedding", "corporate", "concert", "religious", "community", "conference", "other"]


def _public_user(user):
    return {key: user.get(key) for key in ("user_id", "role", "name", "phone", "organiser_id")}


def _public_organiser(organiser):
    return {
        "organiser_id": organiser.get("organiser_id"),
        "organiser_code": organiser.get("organiser_code"),
        "organisation_name": organiser.get("organisation_name"),
        "event_types": organiser.get("event_types", []),
        "bio": organiser.get("bio", ""),
        "phone": organiser.get("phone", ""),
    }


def _current_user():
    if users_collection is None or not session.get("user_id"):
        return None
    return users_collection.find_one({"user_id": session["user_id"]})


def _error(message, status=400):
    return jsonify({"status": "error", "message": message}), status


def _operation_scope():
    user = _current_user()
    organiser_id = user.get('organiser_id') if user and user.get('role') == 'organiser' else None
    event_id = session.get('event_id')
    if not organiser_id or not event_id:
        return None
    return {'organiser_id': organiser_id, 'event_id': event_id}


def get_event_config():
    """Fetch the signed-in organiser's selected event configuration."""
    if event_collection is None:
        return None
    user = _current_user()
    if not user or not user.get('organiser_id'):
        return None
    config = event_collection.find_one({'organiser_id': user['organiser_id'], 'event_id': session.get('event_id')})
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


@feedback_bp.route('/event', methods=['POST'])
def set_event():
    """
    Set (or update) the event's location and date.
    Expects JSON: { "location": "Kampala, Uganda", "date": "2026-09-26" }
    """
    data = request.get_json()

    user = _current_user()
    if not user or user.get('role') != 'organiser':
        return _error('An organiser account is required.', 401)

    if not data or 'location' not in data or 'date' not in data:
        return jsonify({"error": "Missing 'location' or 'date' in request"}), 400

    location_name_input = data['location']
    date = data['date']

    lat, lon, resolved_name = geocode_location(location_name_input)

    if lat is None:
        return jsonify({"error": f"Could not find coordinates for '{location_name_input}'"}), 404

    event_id = session.get('event_id') or f"event_{secrets.token_urlsafe(8)}"
    session['event_id'] = event_id
    event_collection.update_one(
        {'organiser_id': user['organiser_id'], 'event_id': event_id},
        {"$set": {
            "event_id": event_id,
            "organiser_id": user['organiser_id'],
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
    if not _operation_scope():
        return _error('Sign in as an organiser and configure an event first.', 401)
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
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)

    if not data or 'name' not in data or 'phone' not in data:
        return jsonify({"error": "Missing 'name' or 'phone' in request"}), 400

    name = data['name']
    phone = data['phone']

    code = generate_code()
    while guests_collection.find_one({**scope, "code": code}):
        code = generate_code()

    guest = {
        **scope,
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
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)
    all_guests = list(guests_collection.find(scope, {"_id": 0}))
    return jsonify(all_guests)


@feedback_bp.route('/guests/upload', methods=['POST'])
def upload_guests():
    """Add multiple guests and send each one a unique-code SMS invitation."""
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)

    data = request.get_json(silent=True) or {}
    guests = data.get('guests')
    if not isinstance(guests, list) or not guests:
        return _error("Provide a non-empty 'guests' list.")

    results = []
    for item in guests:
        name = str(item.get('name', '')).strip()
        phone = str(item.get('phone', '')).strip()
        if not name or not phone:
            results.append({'status': 'failed', 'name': name, 'phone': phone, 'error': 'Name and phone are required.'})
            continue
        if guests_collection.find_one({**scope, 'phone': phone}):
            results.append({'status': 'duplicate', 'name': name, 'phone': phone})
            continue

        code = generate_code()
        while guests_collection.find_one({**scope, 'code': code}):
            code = generate_code()
        guest = {
            **scope,
            'name': name,
            'phone': phone,
            'code': code,
            'checked_in': False,
            'checked_in_at': None,
            'checked_in_by': None,
        }
        guests_collection.insert_one(guest)
        try:
            sms_response = sms.send(f"Hi {name}, you're invited! Your check-in code is: {code}", [phone])
            results.append({'status': 'sent', 'name': name, 'phone': phone, 'code': code, 'sms_response': sms_response})
        except Exception as error:
            results.append({'status': 'saved_sms_failed', 'name': name, 'phone': phone, 'code': code, 'error': str(error)})

    return jsonify({'message': 'Guest list processed.', 'results': results}), 201


@feedback_bp.route('/api/summary', methods=['GET'])
def dashboard_summary():
    """Return live organiser metrics for the existing dashboard UI."""
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)

    guests = list(guests_collection.find(scope, {'_id': 0}))
    tasks = list(tasks_collection.find(scope, {'_id': 0}))
    contributions = list(contributions_collection.find(scope, {'_id': 0}))
    total = sum(float(item.get('amount', 0) or 0) for item in contributions)
    return jsonify({
        'guests': len(guests),
        'checked_in': sum(1 for guest in guests if guest.get('checked_in')),
        'tasks': len(tasks),
        'tasks_done': sum(1 for task in tasks if task.get('status') == 'done'),
        'contributions_total': total,
    }), 200


@feedback_bp.route('/api/feedback', methods=['GET'])
def feedback_feed():
    """Return recent feedback for the organizer command center."""
    return jsonify({'feedback': get_all_feedback()[:10]}), 200


@feedback_bp.route('/reminders', methods=['POST'])
def send_reminders():
    """
    Send a reminder SMS (with current weather forecast) to all registered guests.
    """
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)
    all_guests = list(guests_collection.find(scope, {"_id": 0}))

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
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)

    if not data or 'name' not in data or 'phone' not in data or 'post' not in data:
        return jsonify({"error": "Missing 'name', 'phone', or 'post' in request"}), 400

    name = data['name']
    phone = data['phone']
    post = data['post']

    usher = {
        **scope,
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
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)
    all_ushers = list(ushers_collection.find(scope, {"_id": 0}))
    return jsonify(all_ushers)


@feedback_bp.route('/tasks', methods=['POST'])
def assign_task():
    """
    Assign a task to an usher by phone number. Sends an SMS notification
    with a task code.
    Expects JSON: { "title": "Set up registration desk", "usher_phone": "+254712345678", "due_time": "9:00 AM" }
    """
    data = request.get_json()
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)

    if not data or 'title' not in data or 'usher_phone' not in data:
        return jsonify({"error": "Missing 'title' or 'usher_phone' in request"}), 400

    title = data['title']
    usher_phone = data['usher_phone']
    due_time = data.get('due_time', 'ASAP')

    usher = ushers_collection.find_one({**scope, "phone": usher_phone})
    usher_name = usher['name'] if usher else 'Unknown'

    task_code = generate_code(4)
    while tasks_collection.find_one({**scope, "code": task_code}):
        task_code = generate_code(4)

    task = {
        **scope,
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
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)
    all_tasks = list(tasks_collection.find(scope, {"_id": 0}))
    return jsonify(all_tasks)


@feedback_bp.route('/tasks/complete', methods=['POST'])
def complete_task():
    """
    Mark a task as done using its task code.
    Expects JSON: { "code": "A1B2" }
    """
    data = request.get_json()
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)

    if not data or 'code' not in data:
        return jsonify({"error": "Missing 'code' in request"}), 400

    code = data['code'].upper()
    task = tasks_collection.find_one({**scope, "code": code})

    if not task:
        return jsonify({"status": "not_found", "message": "No task found with this code."}), 404

    if task['status'] == 'done':
        return jsonify({"status": "already_done", "message": "This task was already marked done."}), 200

    tasks_collection.update_one({**scope, "code": code}, {"$set": {"status": "done"}})
    updated_task = tasks_collection.find_one({**scope, "code": code}, {"_id": 0})

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
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)

    if not data or 'name' not in data or 'phone' not in data or 'amount' not in data:
        return jsonify({"error": "Missing 'name', 'phone', or 'amount' in request"}), 400

    name = data['name']
    phone = data['phone']
    amount = data['amount']
    currency = data.get('currency', 'UGX')

    contribution = {
        **scope,
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
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)
    all_contributions = list(contributions_collection.find(scope, {"_id": 0}))
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
    scope = _operation_scope()
    if not scope:
        return _error('Sign in as an organiser and configure an event first.', 401)

    if not data or 'code' not in data:
        return jsonify({"error": "Missing 'code' in request"}), 400

    code = data['code'].upper()
    usher = data.get('usher', 'Unknown')

    guest = guests_collection.find_one({**scope, "code": code})

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
        {**scope, "code": code},
        {"$set": {
            "checked_in": True,
            "checked_in_at": checked_in_at,
            "checked_in_by": usher
        }}
    )

    updated_guest = guests_collection.find_one({**scope, "code": code}, {"_id": 0})

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


@feedback_bp.route('/api/auth/register', methods=['POST'])
def register_account():
    data = request.get_json(silent=True) or {}
    role = data.get('role', '').strip().lower()
    phone = data.get('phone', '').strip()
    password = data.get('password', '')

    if role not in {'organiser', 'client', 'usher'}:
        return _error('Choose organiser, client, or usher.')
    if not phone or not password:
        return _error('Phone and password are required.')
    if users_collection is None:
        return _error('Database is not configured.', 503)
    if users_collection.find_one({'phone': phone}):
        return _error('An account with this phone number already exists.', 409)

    name = data.get('name', '').strip()
    if role == 'organiser':
        organisation_name = data.get('organisation_name', '').strip()
        event_types = [item for item in data.get('event_types', []) if item in EVENT_TYPES]
        if not organisation_name or not event_types or not data.get('bio', '').strip():
            return _error('Organisation name, event type, and bio are required.')
        name = name or organisation_name
    elif role == 'client' and not name:
        return _error('Name is required.')

    organiser = None
    organiser_id = None
    if role == 'usher':
        code = data.get('organiser_code', '').strip().upper()
        organiser = organisers_collection.find_one({'organiser_code': code})
        if not organiser:
            return _error('That organiser code is unknown.', 404)
        organiser_id = organiser['organiser_id']
        if not name:
            return _error('Name is required.')

    user_id = f'user_{secrets.token_urlsafe(8)}'
    user = {
        'user_id': user_id,
        'role': role,
        'name': name,
        'phone': phone,
        'password_hash': generate_password_hash(password),
        'organiser_id': organiser_id,
    }
    users_collection.insert_one(user)

    if role == 'organiser':
        organiser_id = f'org_{secrets.token_urlsafe(8)}'
        organiser_code = secrets.token_hex(3).upper()
        while organisers_collection.find_one({'organiser_code': organiser_code}):
            organiser_code = secrets.token_hex(3).upper()
        organiser = {
            'organiser_id': organiser_id,
            'organiser_code': organiser_code,
            'user_id': user_id,
            'organisation_name': data['organisation_name'].strip(),
            'event_types': event_types,
            'bio': data['bio'].strip(),
            'phone': phone,
        }
        organisers_collection.insert_one(organiser)
        users_collection.update_one({'user_id': user_id}, {'$set': {'organiser_id': organiser_id}})
        user['organiser_id'] = organiser_id
    elif role == 'usher':
        ushers_collection.update_one(
            {'phone': phone, 'organiser_id': organiser_id},
            {'$set': {'name': name, 'phone': phone, 'organiser_id': organiser_id, 'status': 'registered'}},
            upsert=True
        )

    session['user_id'] = user_id
    return jsonify({
        'status': 'success',
        'message': 'Account created successfully.',
        'user': _public_user(user),
        'organiser': _public_organiser(organiser) if role == 'organiser' else None,
    }), 201


@feedback_bp.route('/api/auth/login', methods=['POST'])
def login_account():
    from werkzeug.security import check_password_hash

    data = request.get_json(silent=True) or {}
    user = users_collection.find_one({'phone': data.get('phone', '').strip()}) if users_collection is not None else None
    if not user or not check_password_hash(user.get('password_hash', ''), data.get('password', '')):
        return _error('Invalid phone or password.', 401)
    session['user_id'] = user['user_id']
    return jsonify({'status': 'success', 'user': _public_user(user)}), 200


@feedback_bp.route('/api/auth/me', methods=['GET'])
def current_account():
    user = _current_user()
    if not user:
        return _error('Sign in to continue.', 401)
    return jsonify({'status': 'success', 'user': _public_user(user)}), 200


@feedback_bp.route('/api/organisers', methods=['GET'])
def list_organisers():
    category = request.args.get('type', '').strip().lower()
    query = {'event_types': category} if category in EVENT_TYPES else {}
    organisers = [_public_organiser(item) for item in organisers_collection.find(query).sort('organisation_name', 1)] if organisers_collection is not None else []
    return jsonify({'status': 'success', 'event_types': EVENT_TYPES, 'organisers': organisers}), 200


@feedback_bp.route('/api/organisers/<organiser_id>', methods=['GET'])
def organiser_details(organiser_id):
    organiser = organisers_collection.find_one({'organiser_id': organiser_id}) if organisers_collection is not None else None
    if not organiser:
        return _error('Organiser not found.', 404)
    event = event_collection.find_one({'organiser_id': organiser_id}, {'_id': 0}) if event_collection is not None else None
    weather = ''
    if event:
        try:
            response = requests.get('https://api.open-meteo.com/v1/forecast', params={
                'latitude': event['lat'], 'longitude': event['lon'], 'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max',
                'timezone': 'auto', 'start_date': event['date'], 'end_date': event['date']
            }, timeout=5)
            daily = response.json().get('daily', {})
            maximum = daily.get('temperature_2m_max', [None])[0]
            minimum = daily.get('temperature_2m_min', [None])[0]
            rain = daily.get('precipitation_probability_max', [None])[0]
            if maximum is not None:
                weather = f"{minimum}-{maximum}°C"
                if rain is not None:
                    weather += f", {rain}% chance of rain"
        except requests.RequestException:
            weather = ''
    return jsonify({'status': 'success', 'organiser': _public_organiser(organiser), 'event': event, 'weather': weather}), 200


@feedback_bp.route('/api/bookings', methods=['POST'])
def create_booking():
    user = _current_user()
    data = request.get_json(silent=True) or {}
    organiser_id = data.get('organiser_id', '').strip()
    required = ('event_date', 'location', 'event_type')
    if not user or user.get('role') != 'client':
        return _error('A client account is required to send an invitation.', 401)
    if not organiser_id or any(not data.get(field, '').strip() for field in required):
        return _error('Event date, location, and event type are required.')
    organiser = organisers_collection.find_one({'organiser_id': organiser_id})
    if not organiser:
        return _error('Organiser not found.', 404)
    booking = {
        'booking_id': f'booking_{secrets.token_urlsafe(8)}',
        'client_id': user['user_id'],
        'client_name': user['name'],
        'client_phone': user['phone'],
        'organiser_id': organiser_id,
        'event_date': data['event_date'].strip(),
        'location': data['location'].strip(),
        'event_type': data['event_type'].strip().lower(),
        'notes': data.get('notes', '').strip(),
        'status': 'pending',
        'created_at': datetime.datetime.utcnow(),
    }
    bookings_collection.insert_one(booking)
    sms_message = f"New Bagga invitation from {user['name']} for {booking['event_date']} in {booking['location']}. Review it in your dashboard."
    try:
        sms_result = sms.send(sms_message, [organiser['phone']])
        notification = 'sent'
    except Exception as error:
        sms_result = str(error)
        notification = 'failed'
    return jsonify({'status': 'success', 'message': 'Invitation sent — organiser notified by SMS.', 'booking': {key: value for key, value in booking.items() if key != 'created_at'}, 'sms_status': notification, 'sms_response': sms_result}), 201


@feedback_bp.route('/api/bookings', methods=['GET'])
def list_bookings():
    user = _current_user()
    if not user:
        return _error('Sign in to continue.', 401)
    query = {'organiser_id': user.get('organiser_id')} if user.get('role') == 'organiser' else {'client_id': user['user_id']}
    bookings = list(bookings_collection.find(query, {'_id': 0}).sort('created_at', -1)) if bookings_collection is not None else []
    return jsonify({'status': 'success', 'bookings': bookings}), 200


@feedback_bp.route('/api/bookings/<booking_id>', methods=['PATCH'])
def update_booking(booking_id):
    user = _current_user()
    status = (request.get_json(silent=True) or {}).get('status', '').strip().lower()
    if not user or user.get('role') != 'organiser' or status not in {'accepted', 'declined'}:
        return _error('Only an organiser can accept or decline an invitation.', 403)
    result = bookings_collection.update_one({'booking_id': booking_id, 'organiser_id': user.get('organiser_id')}, {'$set': {'status': status}})
    if not result.matched_count:
        return _error('Invitation not found.', 404)
    return jsonify({'status': 'success', 'message': f'Invitation {status}.', 'booking_id': booking_id, 'booking_status': status}), 200


# NOTE: This module is mounted by the main app; it intentionally does not start a separate server here.