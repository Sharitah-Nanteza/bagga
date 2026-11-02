import os
import json
import re
from html import unescape
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from google import genai
except ImportError:
    genai = None

# Read Gemini API Key from system environment
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
AI_CLIENT = None

if GEMINI_API_KEY and genai:
    try:
        AI_CLIENT = genai.Client(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"[AI Init Warning] Could not configure Gemini API: {e}")

URGENT_PATTERNS = (
    r"\b(?:fire|smoke|emergency|urgent|danger|unsafe)\b",
    r"\b(?:cannot|can't|couldn't|unable to)\s+(?:hear|listen)\b",
    r"\b(?:no|low|weak|poor)\s+(?:sound|audio|volume|power)\b",
    r"\b(?:sound|audio|volume|microphone|mic|speaker|fan)\s+(?:is\s+)?(?:too low|too loud|silent|not working|broken|off)\b",
    r"\b(?:too hot|extremely hot|overheating|stuffy|no air conditioning)\b",
    r"\b(?:dark|no lights|lights are off|power outage|no electricity)\b",
    r"\b(?:sikyawulira|tewulira|omuliro|ebbugumu|ebugumu)\b",
    r"\b(?:edoboozi liri wansi|edoboozi teriwulikika|edoboozi tekola)\b",
    r"\b(?:sauti iko chini|sauti ni ndogo|hakuna sauti|siwezi kusikia|joto kali|umeme umekatika|hakuna umeme|moto|dharura)\b",
)

AUDIO_KEYWORDS = ('sound', 'audio', 'speaker', 'mic', 'microphone', 'edoboozi', 'sauti')
FACILITY_KEYWORDS = ('ac', 'aircon', 'hot', 'heat', 'joto', 'ebugumu', 'ebbugumu', 'fan')


def _is_urgent_feedback(text):
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in URGENT_PATTERNS)

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
        is_urgent = _is_urgent_feedback(text_lower)

        urgency = "HIGH" if is_urgent else "NORMAL"
        sentiment = "NEGATIVE" if is_urgent else ("POSITIVE" if any(w in text_lower for w in ["good", "weebale", "sifa", "thanks"]) else "NEUTRAL")
        
        category = "AUDIO/SOUND" if any(w in text_lower for w in AUDIO_KEYWORDS) else (
            "AC/FACILITIES" if any(w in text_lower for w in FACILITY_KEYWORDS) else "GENERAL"
        )
        
        suggested_reply = "Thank you! Our technical team has been notified and is adjusting venue systems now." if is_urgent else "Thank you for attending and sharing your thoughts with us!"

        return {
            "category": category,
            "urgency": urgency,
            "sentiment": sentiment,
            "translated_text": text_prompt if language == "en" else "",
            "suggested_reply": suggested_reply
        }

    # If API Key is missing, use local fallback immediately
    if not AI_CLIENT:
        print("[AI Engine] Gemini unavailable. Running local heuristic engine.")
        return local_fallback()

    # Attempt Gemini API Call with try/except guard
    try:
        prompt = f"""
        You are the AI Operations Intelligence engine for 'Bagga', an enterprise venue feedback system in Uganda.
        Analyze the incoming attendee feedback (Language: {language}): "{text_prompt}"

        Triage urgency by the need for immediate staff action, not by negative sentiment alone.
        Mark "HIGH" only for an immediate safety/medical threat or a major active-event disruption
        that needs staff attention now (for example, fire, smoke, danger, or attendees being unable
        to hear because the sound system has failed). Mark "NORMAL" for praise, suggestions,
        preferences, routine complaints, and isolated or non-critical issues. When severity is
        unclear, choose "NORMAL". Do not infer an emergency just because the attendee says "help"
        or describes something as broken.

        Return strictly valid JSON with these keys:
        1. "category": EXACTLY ONE of ["PRAISE", "AUDIO/SOUND", "AC/FACILITIES", "GENERAL"]
        2. "urgency": EXACTLY ONE of ["HIGH", "NORMAL"]
        3. "sentiment": EXACTLY ONE of ["POSITIVE", "NEUTRAL", "NEGATIVE"]
        4. "translated_text": English translation if not in English, otherwise repeat the text.
        5. "suggested_reply": A professional, concise SMS reply (under 140 chars) for the venue manager to send back to the attendee.

        Return ONLY raw JSON. No markdown code blocks, no extra commentary.
        """

        response = AI_CLIENT.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        clean_json = (response.text or "").replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_json)
        translated_text = str(data.get("translated_text", "")).strip()
        urgency_value = str(data.get("urgency", "NORMAL")).strip().upper()
        urgency = "HIGH" if urgency_value in {"HIGH", "URGENT", "CRITICAL", "EMERGENCY"} else "NORMAL"
        if language == "en":
            translated_text = text_prompt
        elif translated_text.casefold() == text_prompt.strip().casefold():
            translated_text = ""

        return {
            "category": str(data.get("category", "GENERAL")).upper(),
            "urgency": urgency,
            "sentiment": str(data.get("sentiment", "NEUTRAL")).upper(),
            "translated_text": translated_text,
            "suggested_reply": str(data.get("suggested_reply", "Thank you for your feedback!"))
        }

    except Exception as e:
        print(f"[AI Engine Exception Guarded] Fallback active due to error: {e}")
        return local_fallback()


def translate_to_english(text, language):
    """Translate supported attendee feedback, returning None when unavailable."""
    source_languages = {"lg": "Luganda", "sw": "Kiswahili"}
    source_language = source_languages.get(language)
    if not text or not source_language:
        return None

    if AI_CLIENT:
        prompt = f"""
Translate the following {source_language} attendee feedback into English.
Preserve the original meaning and tone. Return only the English translation.

Feedback: {text}
"""
        try:
            response = AI_CLIENT.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt
            )
            translated_text = (response.text or "").strip().strip('"')
            if translated_text and translated_text.casefold() != text.strip().casefold():
                return translated_text
        except Exception as e:
            print(f"[Translation Exception Guarded] Gemini translation failed; trying fallback: {e}")

    params = urlencode({
        'q': text[:5000],
        'langpair': f'{language}|en'
    })
    request = Request(
        f'https://api.mymemory.translated.net/get?{params}',
        headers={'User-Agent': 'BaggaFeedbackDashboard/1.0'}
    )
    try:
        with urlopen(request, timeout=12) as response:
            result = json.load(response)
        translated_text = unescape(str(result.get('responseData', {}).get('translatedText', '')).strip())
        if result.get('responseStatus') != 200:
            return None
        if not translated_text or translated_text.casefold() == text.strip().casefold():
            return None
        return translated_text
    except Exception as e:
        print(f"[Translation Exception Guarded] Fallback translation unavailable: {e}")
        return None