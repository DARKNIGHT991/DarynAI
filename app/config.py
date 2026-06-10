import os

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
ADMIN_COMMAND = os.getenv("ADMIN_COMMAND")
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
RESPONSE_SIGNING_SECRET = os.getenv("RESPONSE_SIGNING_SECRET", "daryn-dev-secret")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://darynai.onrender.com").strip()
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

if not GROQ_API_KEY:
    print("🚨 ВНИМАНИЕ: GROQ_API_KEY не найден!")
