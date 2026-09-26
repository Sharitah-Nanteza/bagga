from dotenv import load_dotenv
from flask import Flask, render_template

from backend.routes import feedback_bp
from database import get_all_feedback, init_db

load_dotenv()
init_db()

app = Flask(__name__)
app.register_blueprint(feedback_bp)

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

@app.route("/attendee")
def attendee():
    return render_template("attendee.html")

@app.route("/sms-simulator")
def sms_simulator():
    return render_template("sms_simulator.html")

@app.route("/feedback")
def feedback():
    return dashboard()

if __name__ == "__main__":
    app.run(port=5000, debug=True)
