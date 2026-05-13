from datetime import datetime, timedelta

from fastapi import APIRouter

from ..config import ADMIN_EMAIL
from ..db import get_db_connection
from ..schemas import AdminPlanChange
from ..services.plans import PLANS

router = APIRouter()

@router.post("/admin/set_plan")
def admin_set_plan(req: AdminPlanChange):
    if not ADMIN_EMAIL or req.admin_email != ADMIN_EMAIL:
        return {"status": "error", "message": "Доступ запрещён"}
    if req.plan not in PLANS:
        return {"status": "error", "message": "Неверный план"}
    try:
        conn        = get_db_connection()
        cursor      = conn.cursor()
        expires     = datetime.now() + timedelta(days=req.days)
        plan_data   = PLANS[req.plan]

        cursor.execute(
            """UPDATE users
               SET plan = %s, credits = %s, plan_expires = %s
               WHERE email = %s""",
            (req.plan, plan_data["images_per_day"], expires, req.target_email)
        )
        cursor.execute(
            """UPDATE payments SET status = 'confirmed'
               WHERE email = %s AND plan = %s AND status = 'pending'
               ORDER BY created_at DESC LIMIT 1""",
            (req.target_email, req.plan)
        )
        conn.commit()
        conn.close()
        return {
            "status":  "success",
            "message": f"План {req.plan} установлен для {req.target_email}",
            "expires": expires.strftime("%Y-%m-%d"),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/admin/payments")
def admin_get_payments(admin_email: str):
    if not ADMIN_EMAIL or admin_email != ADMIN_EMAIL:
        return {"status": "error", "message": "Доступ запрещён"}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, email, plan, amount, status, tx_id, created_at
               FROM payments ORDER BY created_at DESC LIMIT 100"""
        )
        rows = cursor.fetchall()
        conn.close()
        return {
            "status": "success",
            "payments": [
                {
                    "id":         r[0],
                    "email":      r[1],
                    "plan":       r[2],
                    "amount":     float(r[3]),
                    "status":     r[4],
                    "tx_id":      r[5],
                    "created_at": str(r[6]),
                }
                for r in rows
            ],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/admin/users")
def admin_get_users(admin_email: str):
    if not ADMIN_EMAIL or admin_email != ADMIN_EMAIL:
        return {"status": "error", "message": "Доступ запрещён"}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT id, username, email, plan, credits, msg_count,
                      last_reset, plan_expires, created_at
               FROM users ORDER BY id DESC"""
        )
        rows = cursor.fetchall()
        conn.close()
        return {
            "status": "success",
            "users": [
                {
                    "id":           r[0],
                    "username":     r[1],
                    "email":        r[2],
                    "plan":         r[3],
                    "credits":      r[4],
                    "msg_count":    r[5],
                    "last_reset":   str(r[6]),
                    "plan_expires": str(r[7]) if r[7] else None,
                    "created_at":   str(r[8]),
                }
                for r in rows
            ],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
