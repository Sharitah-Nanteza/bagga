from dotenv import load_dotenv
from flask import Flask, jsonify, render_template
from pymongo.errors import PyMongoError

from database import get_all_feedback, init_db, mongo_client
from backend.routes import feedback_bp, guests_collection

load_dotenv()

app = Flask(__name__)
app.register_blueprint(feedback_bp)

try:
    init_db()
except PyMongoError:
    app.logger.warning("MongoDB unavailable; check Atlas network access and backend/.env.")


@app.errorhandler(PyMongoError)
def database_error(error):
    return jsonify({"error": "MongoDB is unavailable. Check Atlas network access and backend/.env."}), 503


@app.route("/health")
def health():
    if mongo_client is None:
        return jsonify({"status": "degraded", "database": "not configured"}), 503
    try:
        mongo_client.admin.command("ping")
    except PyMongoError:
        return jsonify({"status": "degraded", "database": "unavailable"}), 503
    return jsonify({"status": "ok", "database": "connected"})


def render_feedback_page(template):
    try:
        feedbacks = get_all_feedback()
        error = None if mongo_client is not None else "Database is not configured. Set MONGO_URI in backend/.env."
    except PyMongoError:
        feedbacks = []
        error = "Database is unavailable. Saved feedback cannot be loaded and changes cannot be saved. Check MongoDB Atlas network access."
    attendees = []
    if template == "dashboard.html" and guests_collection is not None:
        try:
            attendees = list(guests_collection.find({}, {"_id": 0, "name": 1, "phone": 1}))
        except PyMongoError:
            error = "Database is unavailable. Feedback or registered contacts could not be loaded."
    stats = {"total_feedback": len(feedbacks), "high_urgency": sum(item.get("urgency") == "HIGH" for item in feedbacks)}
    return render_template(template, feedbacks=feedbacks, database_error=error, attendees=attendees, stats=stats)


# --- 1. HOME / LANDING PAGE ROUTE ---
@app.route("/")
def home():
    return render_feedback_page("home.html")

# --- 2. FEEDBACK DASHBOARD ROUTE ---
@app.route("/dashboard")
def dashboard():
    return render_feedback_page("dashboard.html")

@app.route("/attendee")
def attendee():
    return render_template("attendee.html")

@app.route("/feedback")
def feedback():
    return dashboard()

if __name__ == "__main__":
    app.run(port=5000, debug=True)
