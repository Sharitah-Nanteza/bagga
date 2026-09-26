# Event Command Center API

Flask backend for event setup, guest registration, check-in, usher coordination, task tracking, weather updates, and contribution tracking.

## Setup

1. Create a local environment file:

   ```bash
   cp .env.example .env
   ```

2. Fill in the Africa's Talking credentials and MongoDB connection string in `.env`.

3. Install dependencies and start the API:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/python ../app.py
   ```

The API runs at `http://127.0.0.1:5000`.

All request bodies are JSON. Phone numbers should use international format, for example `+254712345678`.

## Endpoints

### Health check

#### `GET /`

Returns:

```json
{"message": "Event Command Center backend is running."}
```

### Event and weather

#### `POST /event`

Geocodes and saves the current event name, location, date, and optional schedule. When the schedule, date, event name, or venue changes, registered speaker contacts (`kind: "speaker"`) receive an SMS update.

Request:

```json
{
  "event_name": "Bagga Summit",
  "location": "Kampala, Uganda",
  "date": "2026-09-26",
  "schedule": "Keynote at 10:00; lunch at 13:00"
}
```

Returns `200` with resolved event details and speaker notification counts. Returns `400` for invalid input, `404` when the location cannot be found, or `503` when MongoDB is not configured.

#### `GET /event`

Returns the saved event configuration, or `404` when no event has been configured.

#### `GET /weather`

Returns the configured event-day forecast and the recommended reminder date (one day before the event).

#### `GET /communications/status`

Returns SMS credentials, inbound SMS number, USSD service code, and MongoDB configuration status for the organizer interface.

### SMS and USSD feedback

#### `POST /api/sms`

Africa's Talking inbound SMS callback. Accepts `from` and `text` fields, anonymizes the sender, classifies the feedback, and saves it to the dashboard feed.

#### `POST /api/ussd`

Africa's Talking USSD callback. Menu option 6 returns the saved event name, date, venue, and schedule. Feedback options are anonymized and saved to the same dashboard feed.

### Guests and reminders

#### `POST /guests`

Registers a guest, generates a six-character check-in code, and sends an SMS invite. The invite includes the event-day weather when an event is configured.

Request:

```json
{"name": "Jane Doe", "phone": "+254712345678"}
```

Returns `201` with `guest` and `sms_response`. Returns `400` for missing fields or `500` if saving succeeds but SMS sending fails.

#### `GET /guests`

Returns all registered guests, including their check-in state and code.

#### `POST /reminders`

Sends a weather-aware reminder SMS to every registered guest. Returns per-recipient results, counts, and the forecast. Includes weather when available; reminders still send if the weather service is unavailable. Use **Remind attendees** on the home page to send manually.

### Ushers

#### `POST /ushers`

Registers an event-team or speaker contact, assigns a post/session, and sends an SMS notification. Pass `"kind": "speaker"` to enable automatic schedule alerts; `kind` defaults to `team`.

Request:

```json
{"name": "Grace", "phone": "+254712345678", "post": "Opening keynote", "kind": "speaker"}
```

Returns `201` with `usher` and `sms_response`.

#### `GET /ushers`

Returns all registered ushers.

### Tasks

#### `POST /tasks`

Assigns a task to an usher phone number, generates a four-character task code, and sends an SMS. `due_time` is optional and defaults to `ASAP`.

Request:

```json
{
  "title": "Set up registration desk",
  "usher_phone": "+254712345678",
  "due_time": "9:00 AM"
}
```

Returns `201` with `task` and `sms_response`.

#### `GET /tasks`

Returns all tasks and their current status (`pending` or `done`).

#### `POST /tasks/complete`

Marks a task as complete using its code.

Request:

```json
{"code": "A1B2"}
```

Returns `200` on success or when the task is already complete, and `404` when the code is unknown.

### Contributions

#### `POST /contributions`

Records a contribution in MongoDB and sends an SMS receipt. No mobile-money prompt is initiated.

Request:

```json
{
  "name": "Jane Doe",
  "phone": "+254760322433",
  "amount": 5000,
  "currency": "UGX"
}
```

`currency` defaults to `UGX`. Returns `201` with the saved `contribution` and `sms_response`. If the contribution is saved but SMS fails, it still returns `201` with `sms_error`.

#### `GET /contributions`

Returns every contribution and the sum of their `amount` values:

```json
{
  "contributions": [],
  "total": 0
}
```

### Check-in

#### `POST /checkin`

Checks in a guest using the code from their invite. `usher` is optional and defaults to `Unknown`.

Request:

```json
{"code": "A1B2C3", "usher": "Grace"}
```

Returns `200` on success, `404` when the code is not found, and `409` when the guest has already checked in.

## External services

- MongoDB stores event configuration, guests, ushers, tasks, and contributions.
- Africa's Talking sends invite, reminder, usher, task, and contribution receipt SMS messages.
- Open-Meteo geocoding and forecast APIs provide location and weather data without an API key.
## Database troubleshooting

Configuration is loaded from `backend/.env` regardless of the working directory. Exported environment variables take precedence. All records use the `event_command_center` MongoDB database.

Visit `/health` to check the live database connection. If it returns 503, verify that the Atlas cluster is active, your current IP is in its Network Access list, and the database user credentials in `MONGO_URI` are correct. The interface remains available during an outage and displays a warning; failed writes are not reported as successful.

## Invitation SMS with Africa's Talking sandbox

The existing `POST /guests` invitation flow uses the sandbox when `backend/.env` has:

```env
AT_USERNAME=sandbox
AT_API_KEY=your_sandbox_api_key
AT_SMS_SIMULATOR=false
```

`AT_SMS_SIMULATOR` is the app's local fake-response fallback; it is not Africa's Talking's sandbox. Keep it false when testing provider integration. Restart Flask after changing environment variables.

1. Open https://account.africastalking.com/apps/sandbox and launch its simulator.
2. Sign into the simulator with a test phone number including the country code and keep it open.
3. In the app, open **Invite an attendee** and register that same number.
4. Read the invitation and check-in code in the simulator's SMS inbox. Sandbox messages do not arrive on a physical handset.

The app checks recipient acceptance before reporting success. Acceptance is not a delivery receipt. A failed SMS leaves the guest saved with `sms_status: failed`.

## Feedback interface

`/dashboard` and `/feedback` use the supplied blue/indigo control-center design. Counts come from MongoDB feedback; the contact directory lists registered guests separately from anonymous feedback. The language selector and show-more control come from the supplied HTML. Home links open the existing reminder and customer-update tools. The supplied SQLite database, permanent-delete action, and placeholder SMS handlers were not installed.

`/attendee` uses the matching palette and submits typed feedback to the existing API. Save errors retain the entered note. The old mock audio control was removed because it submitted a fixed sample complaint rather than the recording.

Run interface regression checks from the project directory with `python -m unittest discover -s tests -v`. These checks mock database access and do not send messages.
