import os
from datetime import datetime

from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI") or os.getenv("MONGODB_URI")

mongo_client = MongoClient(MONGO_URI) if MONGO_URI else None
mongo_db = mongo_client["event_command_center"] if mongo_client is not None else None
feedback_collection = mongo_db["feedback"] if mongo_db is not None else None


def init_db():
    """Initialize indexes for the shared MongoDB feedback collection."""
    if feedback_collection is None:
        return

    feedback_collection.create_index("timestamp")
    feedback_collection.create_index("anon_id")


def save_feedback(anon_id, channel, raw_text, category="GENERAL", urgency="LOW", sentiment="NEUTRAL"):
    """Insert a new anonymous feedback document into MongoDB."""
    if feedback_collection is None:
        return None

    document = {
        "anon_id": anon_id,
        "channel": channel,
        "raw_text": raw_text,
        "category": category,
        "urgency": urgency,
        "sentiment": sentiment,
        "timestamp": datetime.utcnow(),
    }
    return feedback_collection.insert_one(document).inserted_id


def get_all_feedback():
    """Return all feedback records ordered newest first."""
    if feedback_collection is None:
        return []

    feedback = list(feedback_collection.find().sort("timestamp", -1))
    for item in feedback:
        item["_id"] = str(item.get("_id"))
    return feedback