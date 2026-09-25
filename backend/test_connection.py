import os
from dotenv import load_dotenv
import africastalking

load_dotenv()

username = os.getenv("AT_USERNAME")
api_key = os.getenv("AT_API_KEY")

if not username or not api_key:
    print("Missing AT_USERNAME or AT_API_KEY in .env file")
    exit()

africastalking.initialize(username, api_key)
sms = africastalking.SMS

print("Africa's Talking SDK initialized successfully.")
print(f"Username: {username}")

try:
    response = sms.send(
        "Hello from Event Command Center test script!",
        ["+254760322433"]  # replace with your registered sandbox test number
    )
    print("SMS send response:")
    print(response)
except Exception as e:
    print("Error sending SMS:", e)