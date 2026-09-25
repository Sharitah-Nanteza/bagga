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
  cd ..
  .venv/bin/python app.py
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

Geocodes and saves the current event location and date. The weather forecast used in guest invites and reminders is based on this configuration.

Request:

```json
{"location": "Kampala, Uganda", "date": "2026-09-26"}
```

Returns `200` with the resolved location, coordinates, and date. Returns `400` for missing fields or `404` when the location cannot be found.

#### `GET /event`

Returns the saved event configuration, or `404` when no event has been configured.

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

Sends a weather-aware reminder SMS to every registered guest. Returns `200` with a per-guest result list. If there are no guests, returns `{"message": "No guests to remind."}`.

### Ushers

#### `POST /ushers`

Registers an usher, assigns a post, and sends an SMS notification.

Request:

```json
{"name": "Grace", "phone": "+254712345678", "post": "Main Entrance"}
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