from fastapi import APIRouter

from ..db import get_db_connection
from ..schemas import HistoryRequest, PlanUpgrade
from ..services.plans import PLANS, check_and_reset_daily_limits, get_user_plan

router = APIRouter()

@router.get("/plans")
def get_plans():
    return {
        "status": "success",
        "plans": {
            key: {
                "name":           val["name"],
                "price":          val["price"],
                "msg_per_day":    val["msg_per_day"],
                "images_per_day": val["images_per_day"],
                "max_file_mb":    val["max_file_mb"],
                "voice_output":   val["voice_output"],
                "context_length": val["context_length"],
                "color":          val["color"],
                "badge":          val["badge"],
            }
            for key, val in PLANS.items()
            if key != "admin"
        }
    }


@router.post("/my_plan")
def get_my_plan(req: HistoryRequest):
    if req.email == "guest":
        return {
            "status": "success",
            "plan":   "free",
            "badge":  "FREE",
            "color":  "#6b7280",
            "name":   "Free",
            "expires": None,
            "limits": {
                "msg_per_day":    5,
                "images_per_day": 0,
                "max_file_mb":    5,
                "voice_output":   False,
                "context_length": 8000,
            },
            "usage": {"credits_left": 0, "msg_count": 0},
        }

    plan   = get_user_plan(req.email)
    limits = check_and_reset_daily_limits(req.email)

    expires = None
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT plan_expires FROM users WHERE email = %s",
            (req.email,)
        )
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            expires = row[0].strftime("%Y-%m-%d")
    except:
        pass

    return {
        "status":  "success",
        "plan":    plan["plan_key"],
        "badge":   plan["badge"],
        "color":   plan["color"],
        "name":    plan["name"],
        "expires": expires,
        "limits": {
            "msg_per_day":    plan["msg_per_day"],
            "images_per_day": plan["images_per_day"],
            "max_file_mb":    plan["max_file_mb"],
            "voice_output":   plan["voice_output"],
            "context_length": plan["context_length"],
        },
        "usage": {
            "credits_left": limits["credits"],
            "msg_count":    limits["msg_count"],
        },
    }


@router.post("/upgrade_plan")
def upgrade_plan(req: PlanUpgrade):
    if req.email == "guest":
        return {"status": "error", "message": "Гости не могут изменить план"}
    if req.plan not in ("free", "pro", "premium"):
        return {"status": "error", "message": "Неверный план"}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        price  = PLANS[req.plan]["price"]
        cursor.execute(
            """INSERT INTO payments (email, plan, amount, status, tx_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (req.email, req.plan, price, "pending", req.tx_id)
        )
        conn.commit()
        conn.close()
        return {
            "status":  "success",
            "message": f"Заявка на план {req.plan} отправлена. Ожидайте подтверждения.",
            "plan":    req.plan,
            "price":   price,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
