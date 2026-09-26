# 🎙️ Bagga Whisper

> **Offline-First, Anonymous Event Attendee Feedback & Real-Time Intelligence Platform**

Bagga Whisper enables conference and event organizers to collect real-time feedback from attendees without requiring an internet connection or smartphone apps. Powered by **Africa's Talking USSD/Voice APIs** and **Google Gemini AI**, it routes complaints, praises, and operational alerts straight to an organizer command dashboard while guaranteeing 100% attendee anonymity through cryptographic phone number hashing.

---

## 🚀 Key Features

* **Zero-Internet Accessibility:** Attendees participate via simple USSD codes (`*384*...#`) or Voice hotline calls.
* **Cryptographic Anonymity:** Phone numbers are hashed using MD5 (`Attendee#XXXXX`) at the gateway layer, preserving privacy while enabling airtime rewards.
* **Gemini AI Classification:** Raw feedback notes are analyzed instantly for operational category (Audio, Facilities, Schedule) and urgency level (High, Medium, Low).
* **Organizer Command Center:** Real-time web dashboard displaying live stream metrics, active channel status, and high-urgency alerts.
* **Airtime Reward System:** Incentive loop rewarding attendees for actionable feedback directly via Africa's Talking Airtime API.

---

## 🛠️ Tech Stack

* **Backend:** Python 3, Flask
* **Database:** MongoDB
* **Telephony Gateway:** Africa's Talking SDK (USSD, Voice, Airtime)
* **AI Intelligence:** Google Gemini API (`google-generativeai`)
* **Frontend:** HTML5, Bootstrap 5, Modern JavaScript

---

## ⚙️ Setup & Local Development

### 1. Clone & Activate Virtual Environment
```bash
git clone https://github.com/nanteza/bagga.git
cd bagga
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure Environment Variables
Create `backend/.env` (loaded automatically from any working directory):
```env
AT_USERNAME=sandbox
AT_API_KEY=your_africas_talking_api_key
GEMINI_API_KEY=your_google_gemini_api_key
MONGO_URI=your_mongodb_connection_string
AT_SMS_FEEDBACK_NUMBER=your_inbound_sms_number
AT_USSD_CODE=*384*your_service_code#
```

Configure Africa's Talking to send incoming SMS to `https://your-public-host/api/sms` and USSD sessions to `https://your-public-host/api/ussd`. The public host must be reachable by Africa's Talking. USSD option 6 returns the saved event details and schedule; incoming SMS feedback is anonymized and appears in the feedback dashboard.

### 3. Run Application
```bash
python3 app.py
```
Access the organizer dashboard at `http://127.0.0.1:5000`.

---

## 🧪 Simulation & Testing

Simulate an incoming USSD report:
```bash
curl -X POST http://127.0.0.1:5000/api/ussd \
  -d "sessionId=ATQid_101" \
  -d "serviceCode=*384*55#" \
  -d "phoneNumber=+256701123456" \
  -d "text=4*The room temperature is way too hot"
```

