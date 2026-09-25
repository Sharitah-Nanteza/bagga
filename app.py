from dotenv import load_dotenv
from flask import Flask, render_template

from backend.routes import feedback_bp
from database import get_all_feedback, init_db

load_dotenv()
init_db()

app = Flask(__name__)
app.register_blueprint(feedback_bp)

# --- 1. ORGANIZER DASHBOARD ROUTE ---
@app.route("/")
def dashboard():
    feedbacks = get_all_feedback()
    return render_template("dashboard.html", feedbacks=feedbacks)

if __name__ == "__main__":
    app.run(port=5000, debug=True)
