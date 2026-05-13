from datetime import datetime

from ..config import ADMIN_EMAIL
from ..db import get_db_connection

PLANS = {
    "free": {
        "name": "Free",
        "price": 0,
        "msg_per_day": 20,
        "images_per_day": 5,
        "max_file_mb": 5,
        "voice_input": True,
        "voice_output": False,
        "context_length": 8000,
        "model": "llama-3.1-8b-instant",
        "color": "#6b7280",
        "badge": "FREE",
    },
    "pro": {
        "name": "Pro",
        "price": 9.99,
        "msg_per_day": 500,
        "images_per_day": 50,
        "max_file_mb": 25,
        "voice_input": True,
        "voice_output": True,
        "context_length": 32000,
        "model": "llama-3.3-70b-versatile",
        "color": "#3b82f6",
        "badge": "PRO",
    },
    "premium": {
        "name": "Premium",
        "price": 24.99,
        "msg_per_day": 9999,
        "images_per_day": 200,
        "max_file_mb": 100,
        "voice_input": True,
        "voice_output": True,
        "context_length": 131072,
        "model": "llama-3.3-70b-versatile",
        "color": "#f59e0b",
        "badge": "PREMIUM",
    },
    "admin": {
        "name": "Admin",
        "price": 0,
        "msg_per_day": 999999,
        "images_per_day": 999999,
        "max_file_mb": 500,
        "voice_input": True,
        "voice_output": True,
        "context_length": 131072,
        "model": "llama-3.3-70b-versatile",
        "color": "#10b981",
        "badge": "ADMIN",
    },
}


def get_user_plan(email: str) -> dict:
    if email == ADMIN_EMAIL and ADMIN_EMAIL:
        return {**PLANS["admin"], "plan_key": "admin"}

    if email == "guest":
        return {
            **PLANS["free"],
            "plan_key": "free",
            "msg_per_day": 5,
            "images_per_day": 0,
        }

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT plan, plan_expires FROM users WHERE email = %s",
            (email,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {**PLANS["free"], "plan_key": "free"}

        plan_key = row[0] or "free"
        plan_expires = row[1]

        if plan_key in ("pro", "premium") and plan_expires:
            if datetime.now() > plan_expires:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET plan = 'free' WHERE email = %s",
                    (email,)
                )
                conn.commit()
                conn.close()
                plan_key = "free"

        return {**PLANS.get(plan_key, PLANS["free"]), "plan_key": plan_key}

    except Exception as e:
        print(f"🚨 get_user_plan error: {e}")
        return {**PLANS["free"], "plan_key": "free"}


def check_and_reset_daily_limits(email: str) -> dict:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT credits, msg_count, last_reset FROM users WHERE email = %s",
            (email,)
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            return {"credits": 5, "msg_count": 0}

        credits = row[0] if row[0] is not None else 5
        msg_count = row[1] if row[1] is not None else 0
        last_reset = row[2]
        now = datetime.now()

        if last_reset is None or (now - last_reset).total_seconds() >= 86400:
            plan = get_user_plan(email)
            credits = plan["images_per_day"]
            msg_count = 0
            cursor.execute(
                """UPDATE users
                   SET credits = %s, msg_count = 0, last_reset = %s
                   WHERE email = %s""",
                (credits, now, email)
            )
            conn.commit()

        conn.close()
        return {"credits": credits, "msg_count": msg_count}

    except Exception as e:
        print(f"🚨 check_and_reset_daily_limits error: {e}")
        return {"credits": 0, "msg_count": 0}
