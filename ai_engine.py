import os
import json
import google.generativeai as genai

# Read Gemini API Key from system environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[AI Init Warning] Could not configure Gemini API: {e}")

# Heuristic keywords for local offline fallback
URGENT_KEYWORDS = [
    'mic', 'microphone', 'sound', 'audio', 'speaker', 'loud', 'silent', 'volume', 'hear', 'echo', 'noise',
    'ac', 'aircon', 'fan', 'hot', 'heat', 'warm', 'stuffy', 'fire', 'help', 'emergency', 'broken', 'bad', 'dark', 'light', 'power',
    'edoboozi', 'sikyawulira', 'ebugumu', 'omuliro', 'akazindaalo', 'obuzibu', 'ebikwata',
    'sauti', 'joto', 'mbovu', 'msaidie', 'moto', 'kipaza', 'haisikiki', 'fani'
]

def analyze_feedback(text_prompt, language="en"):
    """
    Analyzes raw USSD feedback text safely.
    Attempts Gemini API analysis first, and automatically falls back to 
    local rules if offline or if API key is unconfigured (prevents 500 errors).
    """
    if not text_prompt:
        return {
            "category": "GENERAL",
            "urgency": "NORMAL",
            "sentiment": "NEUTRAL",
            "translated_text": "",
            "suggested_reply": "Thank you for your feedback!"
        }

    # Helper function for local rules fallback
    def local_fallback():
        text_lower = text_prompt.lower()
        is_urgent = any(kw in text_lower for kw in URGENT_KEYWORDS)

        urgency = "HIGH" if is_urgent else "NORMAL"
        sentiment = "NEGATIVE" if is_urgent else ("POSITIVE" if any(w in text_lower for w in ["good", "weebale", "sifa", "thanks"]) else "NEUTRAL")
        
        category = "AUDIO/SOUND" if any(w in text_lower for w in ["sound", "mic", "edoboozi", "sauti", "speaker"]) else (
            "AC/FACILITIES" if any(w in text_lower for w in ["ac", "hot", "heat", "joto", "ebugumu", "fan"]) else "GENERAL"
        )
        
        suggested_reply = "Thank you! Our technical team has been notified and is adjusting venue systems now." if is_urgent else "Thank you for attending and sharing your thoughts with us!"

        return {
            "category": category,
            "urgency": urgency,
            "sentiment": sentiment,
            "translated_text": text_prompt,
            "suggested_reply": suggested_reply
        }

    # If API Key is missing, use local fallback immediately
    if not GEMINI_API_KEY:
        print("[AI Engine] No GEMINI_API_KEY found. Running local heuristic engine.")
        return local_fallback()

    # Attempt Gemini API Call with try/except guard
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        prompt = f"""
        You are the AI Operations Intelligence engine for 'Bagga', an enterprise venue feedback system in Uganda.
        Analyze the incoming attendee feedback (Language: {language}): "{text_prompt}"

        Return strictly valid JSON with these keys:
        1. "category": EXACTLY ONE of ["PRAISE", "AUDIO/SOUND", "AC/FACILITIES", "GENERAL"]
        2. "urgency": EXACTLY ONE of ["HIGH", "NORMAL"]
        3. "sentiment": EXACTLY ONE of ["POSITIVE", "NEUTRAL", "NEGATIVE"]
        4. "translated_text": English translation if not in English, otherwise repeat the text.
        5. "suggested_reply": A professional, concise SMS reply (under 140 chars) for the venue manager to send back to the attendee.

        Return ONLY raw JSON. No markdown code blocks, no extra commentary.
        """

        response = model.generate_content(prompt)
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_json)

        return {
            "category": str(data.get("category", "GENERAL")).upper(),
            "urgency": str(data.get("urgency", "NORMAL")).upper(),
            "sentiment": str(data.get("sentiment", "NEUTRAL")).upper(),
            "translated_text": str(data.get("translated_text", text_prompt)),
            "suggested_reply": str(data.get("suggested_reply", "Thank you for your feedback!"))
        }

    except Exception as e:
        print(f"[AI Engine Exception Guarded] Fallback active due to error: {e}")
        return local_fallback()