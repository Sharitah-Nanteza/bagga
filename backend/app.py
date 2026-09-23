import os
import random
import string
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import africastalking

# Load environment variables
load_dotenv()

username = os.getenv("AT_USERNAME")
api_key = os.getenv("AT_API_KEY")

# Initialize Africa's Talking
africastalking.initialize(username, api_key)
sms = africastalking.SMS

app = Flask(__name__)

# Temporary in-memory storage (we'll move this to a real database next)
guests = {}


def generate_code(length=6):
    """Generate a random alphanumeric guest code, e.g. 'A1B2C3'."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))


@app.route('/')
def home():
    return jsonify({"message": "Event Command Center backend is running."})


@app.route('/guests', methods=['POST'])
def register_guest():
    data = request.get_json()

    if not data or 'name' not in data or 'phone' not in data:
        return jsonify({"error": "Missing 'name' or 'phone' in request"}), 400

    name = data['name']
    phone = data['phone']

    code = generate_code()
    while code in guests:
        code = generate_code()

    guests[code] = {
        "name": name,
        "phone": phone,
        "code": code,
        "checked_in": False,
        "checked_in_at": None
    }

    message = f"Hi {name}, you're invited! Your check-in code is: {code}"
    try:
        sms_response = sms.send(message, [phone])
    except Exception as e:
        return jsonify({"error": f"Guest saved but SMS failed: {str(e)}"}), 500

    return jsonify({
        "message": "Guest registered and invite sent.",
        "guest": guests[code],
        "sms_response": sms_response
    }), 201


@app.route('/guests', methods=['GET'])
def list_guests():
    return jsonify(list(guests.values()))


@app.route('/checkin', methods=['POST'])
def checkin():
    data = request.get_json()

    if not data or 'code' not in data:
        return jsonify({"error": "Missing 'code' in request"}), 400

    code = data['code'].upper()
    usher = data.get('usher', 'Unknown')

    guest = guests.get(code)

    if not guest:
        return jsonify({"status": "not_found", "message": "No guest found with this code."}), 404

    if guest['checked_in']:
        return jsonify({
            "status": "duplicate",
            "message": f"Already checked in at {guest['checked_in_at']}.",
            "guest": guest
        }), 409

    import datetime
    guest['checked_in'] = True
    guest['checked_in_at'] = datetime.datetime.now().strftime("%H:%M:%S")
    guest['checked_in_by'] = usher

    return jsonify({
        "status": "success",
        "message": f"{guest['name']} checked in successfully.",
        "guest": guest
    }), 200


if __name__ == '__main__':
    app.run(debug=True, port=5000)