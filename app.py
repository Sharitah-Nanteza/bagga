import os

from dotenv import load_dotenv
from flask import Flask, render_template

from backend.routes import feedback_bp
from database import get_all_feedback, init_db

load_dotenv()
init_db()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "bagga-development-key")
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

@app.route("/register")
def register():
    return render_template("register.html")

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/marketplace")
def marketplace():
    return render_template("marketplace.html")

@app.route("/organiser/<organiser_id>")
def organiser_profile(organiser_id):
    return render_template("organiser_profile.html", organiser_id=organiser_id)

@app.route("/organiser-dashboard")
def organiser_dashboard():
    return render_template("organiser_dashboard.html")

@app.route("/client-dashboard")
def client_dashboard():
    return render_template("client_dashboard.html")

@app.route("/feedback")
def feedback():
    return dashboard()

if __name__ == "__main__":
    app.run(port=5000, debug=True)
