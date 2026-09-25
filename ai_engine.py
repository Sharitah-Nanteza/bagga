import os
import json
import google.generativeai as genai

# Configure Gemini API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

def analyze_feedback(text_prompt):
    """
    Analyzes unstructured feedback text using Gemini API and classifies it
    into structured JSON containing 'category' and 'urgency'.
    """
    if not GEMINI_API_KEY:
        # Fallback heuristic if API key is not set
        text_lower = text_prompt.lower()
        if any(w in text_lower for w in ["hot", "speaker", "sound", "mic", "loud", "dark"]):
            return {"category": "AUDIO_LOGISTICS", "urgency": "HIGH"}
        return {"category": "GENERAL", "urgency": "MEDIUM"}

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        system_instruction = """
        You are the AI triage assistant for 'Bagga Whisper', an live event attendee feedback system.
        Analyze the raw feedback text and return strictly valid JSON with two keys:
        1. "category": Choose exactly ONE from [AUDIO_LOGISTICS, FACILITIES, SCHEDULE, CONTENT, GENERAL]
        2. "urgency": Choose exactly ONE from [HIGH, MEDIUM, LOW]

        Rules:
        - If text complains about sound, microphones, speakers, temperature, or room seating -> "urgency": "HIGH"
        - If text asks a simple question or gives general praise -> "urgency": "LOW"
        - Return ONLY JSON. No extra commentary or markdown code blocks.
        """

        response = model.generate_content(f"{system_instruction}\nFeedback: \"{text_prompt}\"")
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_json)
        return {
            "category": data.get("category", "GENERAL").upper(),
            "urgency": data.get("urgency", "MEDIUM").upper()
        }
    except Exception as e:
        print(f"[AI Engine Error] {e}")
        return {"category": "GENERAL", "urgency": "MEDIUM"}