import requests
from ..config import RESEND_API_KEY

def send_verification_email(email: str, code: str):
    if not RESEND_API_KEY:
        print("🚨 RESEND_API_KEY not found")
        return False

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json"
    }

    html_content = f"""
    <div style="font-family: 'Inter', sans-serif; background-color: #050505; color: #fff; padding: 40px; border-radius: 16px; max-width: 500px; margin: auto; border: 1px solid #3b82f633;">
        <div style="text-align: center; margin-bottom: 30px;">
            <svg viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" style="width: 50px; height: 50px; display: inline-block;">
                <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon>
                <path d="M9 8h3.5a4 4 0 1 1 0 8H9v-8z"></path>
            </svg>
            <h1 style="color: #3b82f6; margin-top: 10px; font-weight: 900; letter-spacing: 1px;">DARYN AI</h1>
        </div>
        <div style="background: rgba(59, 130, 246, 0.1); border: 1px solid #3b82f644; padding: 30px; border-radius: 12px; text-align: center;">
            <p style="font-size: 16px; color: #ccc; margin-bottom: 20px;">Ваш код подтверждения:</p>
            <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #fff; margin-bottom: 20px;">{code}</div>
            <p style="font-size: 12px; color: #888;">Код действителен в течение 10 минут.</p>
        </div>
        <p style="margin-top: 30px; font-size: 13px; color: #555; text-align: center;">
            Если вы не регистрировались в Daryn AI, просто проигнорируйте это письмо.
        </p>
    </div>
    """

    data = {
        "from": "Daryn AI <onboarding@resend.dev>",
        "to": [email],
        "subject": f"{code} — Код подтверждения Daryn AI",
        "html": html_content
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        if response.status_code in [200, 201]:
            print(f"✅ Email sent to {email}")
            return True
        else:
            print(f"🚨 Failed to send email: {response.text}")
            return False
    except Exception as e:
        print(f"🚨 Error sending email: {e}")
        return False
