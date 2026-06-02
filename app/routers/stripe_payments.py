from datetime import datetime, timedelta

import stripe
from fastapi import APIRouter, Header, HTTPException, Request

from ..config import FRONTEND_URL, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
from ..db import get_db_connection
from ..schemas import StripeCheckoutRequest, StripeConfirmRequest
from ..services.plans import PLANS

router = APIRouter(prefix="/stripe", tags=["stripe"])

stripe.api_key = STRIPE_SECRET_KEY


def _stripe_value(obj, key: str, default=None):
    if hasattr(obj, "get"):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _activate_paid_plan(email: str, plan: str, session_id: str) -> None:
    plan_data = PLANS[plan]
    expires = datetime.now() + timedelta(days=30)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE users
           SET plan = %s, credits = %s, plan_expires = %s
           WHERE email = %s""",
        (plan, plan_data["images_per_day"], expires, email),
    )
    cursor.execute(
        """UPDATE payments
           SET status = 'confirmed'
           WHERE tx_id = %s""",
        (session_id,),
    )
    conn.commit()
    conn.close()


@router.post("/create-checkout-session")
def create_checkout_session(req: StripeCheckoutRequest):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")
    if not STRIPE_SECRET_KEY.startswith("sk_"):
        raise HTTPException(
            status_code=500,
            detail="STRIPE_SECRET_KEY must be a Stripe secret key that starts with sk_",
        )
    if req.email == "guest":
        raise HTTPException(status_code=401, detail="Please log in before payment")
    if req.plan not in ("pro", "premium"):
        raise HTTPException(status_code=400, detail="Invalid plan")

    plan_data = PLANS[req.plan]
    amount_cents = int(round(float(plan_data["price"]) * 100))

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            customer_email=req.email,
            client_reference_id=req.email,
            line_items=[
                {
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": amount_cents,
                        "product_data": {
                            "name": f"Daryn AI {plan_data['name']} - 30 days",
                        },
                    },
                    "quantity": 1,
                }
            ],
            metadata={"email": req.email, "plan": req.plan},
            success_url=(
                f"{FRONTEND_URL}/?payment=success&plan={req.plan}"
                "&session_id={CHECKOUT_SESSION_ID}"
            ),
            cancel_url=f"{FRONTEND_URL}/?payment=cancelled",
        )
    except Exception as e:
        message = getattr(e, "user_message", None) or str(e)
        raise HTTPException(status_code=502, detail=f"Stripe error: {message}")

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """INSERT INTO payments (email, plan, amount, status, tx_id)
               VALUES (%s, %s, %s, %s, %s)""",
            (req.email, req.plan, plan_data["price"], "pending", session.id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Payment database error: {e}")

    return {"status": "success", "checkout_url": session.url}


@router.post("/confirm-checkout-session")
def confirm_checkout_session(req: StripeConfirmRequest):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")

    try:
        session = stripe.checkout.Session.retrieve(req.session_id)
    except Exception as e:
        message = getattr(e, "user_message", None) or str(e)
        raise HTTPException(status_code=502, detail=f"Stripe error: {message}")

    payment_status = _stripe_value(session, "payment_status")
    metadata = _stripe_value(session, "metadata", {}) or {}
    email = _stripe_value(metadata, "email")
    plan = _stripe_value(metadata, "plan")

    if payment_status != "paid":
        return {
            "status": "pending",
            "message": "Payment is not completed yet",
            "payment_status": payment_status,
        }

    if not email or plan not in ("pro", "premium"):
        raise HTTPException(status_code=400, detail="Invalid checkout session metadata")

    try:
        _activate_paid_plan(email, plan, _stripe_value(session, "id"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Plan activation error: {e}")

    return {"status": "success", "email": email, "plan": plan}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="stripe-signature"),
):
    payload = await request.body()

    try:
        if STRIPE_WEBHOOK_SECRET:
            if not stripe_signature:
                raise HTTPException(status_code=400, detail="Missing Stripe signature")
            event = stripe.Webhook.construct_event(
                payload, stripe_signature, STRIPE_WEBHOOK_SECRET
            )
        else:
            event = stripe.Event.construct_from(
                await request.json(),
                stripe.api_key,
            )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        if _stripe_value(session, "payment_status") == "paid":
            metadata = _stripe_value(session, "metadata", {}) or {}
            email = _stripe_value(metadata, "email")
            plan = _stripe_value(metadata, "plan")
            if email and plan in ("pro", "premium"):
                _activate_paid_plan(email, plan, _stripe_value(session, "id"))

    return {"received": True}
