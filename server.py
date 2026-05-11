import os
import bcrypt
import requests
import socket
import subprocess
import platform
import re
import json
import base64
import io
import tempfile
import PyPDF2
from datetime import datetime, timedelta
from urllib.parse import urlparse, quote
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import StreamingResponse, HTMLResponse
from duckduckgo_search import DDGS
from dotenv import load_dotenv
from groq import Groq
import psycopg2

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================================================================
# === GROQ CLIENT ===
# ================================================================

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL   = "llama-3.3-70b-versatile"

if not GROQ_API_KEY:
    print("🚨 ВНИМАНИЕ: GROQ_API_KEY не найден!")
else:
    client = Groq(api_key=GROQ_API_KEY)

# ================================================================
# === DATABASE ===
# ================================================================

DATABASE_URL = os.getenv("DATABASE_URL")


def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("🚨 DATABASE_URL не найден! БД не подключена.")
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        return
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()

        # ── Таблица пользователей ──────────────────────────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      VARCHAR(255) NOT NULL,
                email         VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                plan          VARCHAR(20)  DEFAULT 'free',
                credits       INTEGER      DEFAULT 5,
                msg_count     INTEGER      DEFAULT 0,
                last_reset    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                plan_expires  TIMESTAMP,
                created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── Таблица сообщений ──────────────────────────────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id         SERIAL PRIMARY KEY,
                email      VARCHAR(255) NOT NULL,
                role       VARCHAR(50)  NOT NULL,
                content    TEXT         NOT NULL,
                created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── Таблица платежей ───────────────────────────────────
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id         SERIAL PRIMARY KEY,
                email      VARCHAR(255)   NOT NULL,
                plan       VARCHAR(20)    NOT NULL,
                amount     DECIMAL(10,2)  NOT NULL,
                currency   VARCHAR(10)    DEFAULT 'USD',
                status     VARCHAR(20)    DEFAULT 'pending',
                tx_id      VARCHAR(255),
                created_at TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        # ── Миграции: добавляем колонки если их нет ───────────
        migrations = [
            ("users", "plan",         "VARCHAR(20) DEFAULT 'free'"),
            ("users", "credits",      "INTEGER DEFAULT 5"),
            ("users", "msg_count",    "INTEGER DEFAULT 0"),
            ("users", "last_reset",   "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("users", "plan_expires", "TIMESTAMP"),
            ("users", "created_at",   "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]
        for table, col, col_type in migrations:
            cursor.execute(
                f"""SELECT column_name FROM information_schema.columns
                    WHERE table_name=%s AND column_name=%s""",
                (table, col)
            )
            if not cursor.fetchone():
                cursor.execute(
                    f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"
                )

        conn.commit()
        conn.close()
        print("✅ БД инициализирована успешно")
    except Exception as e:
        print(f"🚨 Ошибка БД: {e}")


init_db()

# ================================================================
# === СИСТЕМА ТАРИФНЫХ ПЛАНОВ ===
# ================================================================

PLANS = {
    "free": {
        "name":           "Free",
        "price":          0,
        "msg_per_day":    20,
        "images_per_day": 5,
        "max_file_mb":    5,
        "voice_input":    True,
        "voice_output":   False,
        "context_length": 8000,
        "model":          "llama-3.1-8b-instant",
        "color":          "#6b7280",
        "badge":          "FREE",
    },
    "pro": {
        "name":           "Pro",
        "price":          9.99,
        "msg_per_day":    500,
        "images_per_day": 50,
        "max_file_mb":    25,
        "voice_input":    True,
        "voice_output":   True,
        "context_length": 32000,
        "model":          "llama-3.3-70b-versatile",
        "color":          "#3b82f6",
        "badge":          "PRO",
    },
    "premium": {
        "name":           "Premium",
        "price":          24.99,
        "msg_per_day":    9999,
        "images_per_day": 200,
        "max_file_mb":    100,
        "voice_input":    True,
        "voice_output":   True,
        "context_length": 131072,
        "model":          "llama-3.3-70b-versatile",
        "color":          "#f59e0b",
        "badge":          "PREMIUM",
    },
    "admin": {
        "name":           "Admin",
        "price":          0,
        "msg_per_day":    999999,
        "images_per_day": 999999,
        "max_file_mb":    500,
        "voice_input":    True,
        "voice_output":   True,
        "context_length": 131072,
        "model":          "llama-3.3-70b-versatile",
        "color":          "#10b981",
        "badge":          "ADMIN",
    },
}


def get_user_plan(email: str) -> dict:
    """Вернуть словарь плана для пользователя."""
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

    if email == ADMIN_EMAIL and ADMIN_EMAIL:
        return {**PLANS["admin"], "plan_key": "admin"}

    if email == "guest":
        return {
            **PLANS["free"],
            "plan_key":    "free",
            "msg_per_day": 5,
            "images_per_day": 0,
        }

    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT plan, plan_expires FROM users WHERE email = %s",
            (email,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {**PLANS["free"], "plan_key": "free"}

        plan_key     = row[0] or "free"
        plan_expires = row[1]

        # Проверяем срок действия платного плана
        if plan_key in ("pro", "premium") and plan_expires:
            if datetime.now() > plan_expires:
                conn   = get_db_connection()
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
    """Сбросить счётчики раз в сутки; вернуть текущие значения."""
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT credits, msg_count, last_reset FROM users WHERE email = %s",
            (email,)
        )
        row = cursor.fetchone()

        if not row:
            conn.close()
            return {"credits": 5, "msg_count": 0}

        credits    = row[0] if row[0] is not None else 5
        msg_count  = row[1] if row[1] is not None else 0
        last_reset = row[2]
        now        = datetime.now()

        # Сброс раз в 24 часа
        if last_reset is None or (now - last_reset).total_seconds() >= 86400:
            plan    = get_user_plan(email)
            credits   = plan["images_per_day"]
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


# ================================================================
# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
# ================================================================

def ask_ai_quick(prompt: str) -> str:
    try:
        res = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant"
        )
        return res.choices[0].message.content.strip()
    except:
        return ""


def search_web(query: str) -> str:
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return "Ничего не найдено."
        return "\n".join([f"- {r['body']}" for r in results])
    except:
        return "Поиск временно недоступен."


def get_weather(city: str) -> str:
    try:
        res = requests.get(f"https://wttr.in/{city}?format=3", timeout=5)
        res.encoding = "utf-8"
        return res.text if res.status_code == 200 else "Ошибка: город не найден."
    except:
        return "Служба погоды недоступна."


def clean_domain(text: str) -> str:
    match = re.search(
        r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|(?:\d{1,3}\.){3}\d{1,3})',
        text.lower()
    )
    if match:
        domain = match.group(1)
        return domain[4:] if domain.startswith("www.") else domain
    return text.strip()


def ping_host(host: str) -> str:
    try:
        clean_host = clean_domain(host)
        param  = "-n" if platform.system().lower() == "windows" else "-c"
        result = subprocess.run(
            ["ping", param, "4", "-4", clean_host],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return (
            f"Пинг успешен:\n{result.stdout}"
            if result.returncode == 0
            else f"Хост недоступен:\n{result.stderr or result.stdout}"
        )
    except Exception as e:
        return f"Ошибка при пинге: {e}"


def scan_ports(host: str) -> str:
    try:
        clean_host = clean_domain(host)
        ip         = socket.gethostbyname(clean_host)
        open_ports = []
        for port in [21, 22, 25, 53, 80, 110, 143, 443, 3306, 3389, 8080]:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            if sock.connect_ex((ip, port)) == 0:
                open_ports.append(str(port))
            sock.close()
        if open_ports:
            return f"Цель: {clean_host} ({ip})\nОткрытые порты: {', '.join(open_ports)}"
        return f"Цель: {clean_host} ({ip})\nОткрытых портов нет."
    except Exception as e:
        return f"Ошибка сканирования: {e}"


# ================================================================
# === PYDANTIC МОДЕЛИ ===
# ================================================================

class UserRegister(BaseModel):
    username: str
    email:    str
    password: str

class UserLogin(BaseModel):
    email:    str
    password: str

class HistoryRequest(BaseModel):
    email: str

class ChatRequest(BaseModel):
    text:      str
    email:     str
    mode:      str       = "chat"
    file_name: str | None = None
    file_type: str | None = None
    file_data: str | None = None

class ProfileUpdate(BaseModel):
    email:        str
    new_username: str

class PlanUpgrade(BaseModel):
    email: str
    plan:  str
    tx_id: str = ""

class AdminPlanChange(BaseModel):
    admin_email:  str
    target_email: str
    plan:         str
    days:         int = 30


# ================================================================
# === ЭНДПОИНТЫ — ФРОНТЕНД ===
# ================================================================

@app.get("/")
def serve_frontend():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(
            content="<h1>Ошибка: index.html не найден!</h1>",
            status_code=404
        )


# ================================================================
# === ЭНДПОИНТЫ — АВТОРИЗАЦИЯ ===
# ================================================================

@app.post("/register")
def register(user: UserRegister):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT email FROM users WHERE email = %s",
            (user.email,)
        )
        if cursor.fetchone():
            conn.close()
            return {"status": "error", "message": "Email уже зарегистрирован"}

        hashed = bcrypt.hashpw(
            user.password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        cursor.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)",
            (user.username, user.email, hashed)
        )
        conn.commit()
        conn.close()
        return {"status": "success", "username": user.username, "email": user.email}
    except Exception as e:
        return {"status": "error", "message": f"Ошибка БД: {e}"}


@app.post("/login")
def login(user: UserLogin):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username, password_hash FROM users WHERE email = %s",
            (user.email,)
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return {"status": "error", "message": "Email не найден"}
        if bcrypt.checkpw(user.password.encode("utf-8"), row[1].encode("utf-8")):
            return {"status": "success", "username": row[0], "email": user.email}
        return {"status": "error", "message": "Неверный пароль"}
    except Exception as e:
        return {"status": "error", "message": f"Ошибка БД: {e}"}


# ================================================================
# === ЭНДПОИНТЫ — ИСТОРИЯ И ПРОФИЛЬ ===
# ================================================================

@app.post("/history")
def get_history(req: HistoryRequest):
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT role, content FROM messages WHERE email = %s ORDER BY id ASC",
            (req.email,)
        )
        rows = cursor.fetchall()
        conn.close()
        return {
            "status":  "success",
            "history": [{"role": r[0], "content": r[1]} for r in rows]
        }
    except:
        return {"status": "success", "history": []}


@app.post("/update_profile")
def update_profile(req: ProfileUpdate):
    if req.email == "guest":
        return {"status": "error", "message": "Гости не могут менять профиль."}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET username = %s WHERE email = %s",
            (req.new_username, req.email)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/clear_history")
def clear_user_history(req: HistoryRequest):
    if req.email == "guest":
        return {"status": "success"}
    try:
        conn   = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM messages WHERE email = %s",
            (req.email,)
        )
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ================================================================
# === ЭНДПОИНТЫ — ПЛАНЫ ===
# ================================================================

@app.get("/plans")
def get_plans():
    """Публичный список планов (без admin)."""
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


@app.post("/my_plan")
def get_my_plan(req: HistoryRequest):
    """Текущий план + использование лимитов."""
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


@app.post("/upgrade_plan")
def upgrade_plan(req: PlanUpgrade):
    """Создать pending-заявку на апгрейд плана."""
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


# ================================================================
# === ЭНДПОИНТЫ — АДМИН ===
# ================================================================

@app.post("/admin/set_plan")
def admin_set_plan(req: AdminPlanChange):
    """Администратор вручную устанавливает план пользователю."""
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
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
        # Подтверждаем последний pending-платёж
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


@app.get("/admin/payments")
def admin_get_payments(admin_email: str):
    """Список всех платежей (только для администратора)."""
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
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


@app.get("/admin/users")
def admin_get_users(admin_email: str):
    """Список всех пользователей (только для администратора)."""
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
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
                    "id":          r[0],
                    "username":    r[1],
                    "email":       r[2],
                    "plan":        r[3],
                    "credits":     r[4],
                    "msg_count":   r[5],
                    "last_reset":  str(r[6]),
                    "plan_expires": str(r[7]) if r[7] else None,
                    "created_at":  str(r[8]),
                }
                for r in rows
            ],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ================================================================
# === ЭНДПОИНТ — ГОЛОСОВОЙ ВВОД (Groq Whisper STT) ===
# ================================================================

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    if not GROQ_API_KEY:
        return {"status": "error", "message": "GROQ_API_KEY не найден"}

    tmp_path = None
    try:
        audio_bytes = await file.read()
        if len(audio_bytes) < 1000:
            return {"status": "error", "message": "Аудио слишком короткое или пустое"}

        content_type = file.content_type or "audio/webm"
        ext_map = {
            "audio/webm": ".webm",
            "audio/ogg":  ".ogg",
            "audio/mp4":  ".mp4",
            "audio/mpeg": ".mp3",
            "audio/wav":  ".wav",
        }
        ext = ext_map.get(content_type, ".webm")

        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        with open(tmp_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=(f"audio{ext}", audio_file, content_type),
                response_format="text",
                language=None,
            )

        text = (
            transcription.strip()
            if isinstance(transcription, str)
            else str(transcription)
        )
        return {"status": "success", "text": text}

    except Exception as e:
        return {"status": "error", "message": f"Ошибка распознавания: {e}"}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except:
                pass


# ================================================================
# === ЭНДПОИНТ — ЧАТ ===
# ================================================================

@app.post("/chat")
def chat_with_ai(req: ChatRequest):
    prompt_text          = req.text.lower()
    SECRET_ADMIN_COMMAND = os.getenv("ADMIN_COMMAND")
    is_admin_command     = bool(
        SECRET_ADMIN_COMMAND and req.text.strip() == SECRET_ADMIN_COMMAND
    )

    # ── Получаем план пользователя ─────────────────────────────
    user_plan = get_user_plan(req.email)

    # ── Сохраняем сообщение пользователя ──────────────────────
    history_save_text = req.text
    if req.file_name:
        history_save_text = f"📎 [{req.file_name}]\n" + req.text

    if req.email != "guest" and not is_admin_command:
        # Проверка дневных лимитов сообщений
        limits = check_and_reset_daily_limits(req.email)

        if req.mode in ("chat", "code"):
            if limits["msg_count"] >= user_plan["msg_per_day"]:
                next_plan = "Pro" if user_plan["plan_key"] == "free" else "Premium"

                def _limit_stream():
                    yield (
                        f"<div style='color:#ef4444; font-family:monospace; padding:10px; "
                        f"border:1px solid #ef444433; border-radius:8px;'>"
                        f"[LIMIT_EXCEEDED] Лимит сообщений исчерпан.<br>"
                        f"Ваш план: <strong>{user_plan['name']}</strong> — "
                        f"{user_plan['msg_per_day']} сообщений/день.<br>"
                        f"<span style='color:#3b82f6;'>"
                        f"Upgrade до {next_plan} для большего доступа.</span>"
                        f"</div>"
                    )

                return StreamingResponse(_limit_stream(), media_type="text/plain")

        # Увеличиваем счётчик сообщений
        try:
            conn   = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET msg_count = msg_count + 1 WHERE email = %s",
                (req.email,)
            )
            conn.commit()
            conn.close()
        except:
            pass

        # Сохраняем сообщение пользователя в историю
        try:
            conn   = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (email, role, content) VALUES (%s, %s, %s)",
                (req.email, "user", history_save_text)
            )
            conn.commit()
            conn.close()
        except:
            pass

    # ── Генератор стримингового ответа ────────────────────────
    def generate_stream():
        if not GROQ_API_KEY:
            yield "Ошибка сервера: Отсутствует GROQ_API_KEY."
            return

        # ── Секретная админ-панель ─────────────────────────────
        if is_admin_command:
            try:
                conn   = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, username, email, plan, credits, msg_count FROM users"
                )
                users_data = cursor.fetchall()
                conn.close()

                resp = (
                    "### 🛠 Панель Администратора\n\n"
                    "| ID | Имя | Email | План | Фото | Сообщ. |\n"
                    "|---|---|---|---|---|---|\n"
                )
                if not users_data:
                    resp += "| - | Пусто | - | - | - | - |\n"
                else:
                    for u in users_data:
                        resp += (
                            f"| {u[0]} | {u[1]} | {u[2]} "
                            f"| {u[3] or 'free'} | {u[4]} | {u[5]} |\n"
                        )
                yield resp
            except Exception as e:
                yield f"Ошибка доступа к БД: {e}"
            return

        # ── Основная логика ────────────────────────────────────
        full_ai_response = ""

        # Выбираем модель по плану (для файлов-изображений переопределим позже)
        current_model = user_plan.get("model", GROQ_MODEL)

        system_instruction = (
            "Ты — Daryn AI, высокоинтеллектуальный ассистент и Dev-платформа. "
            "Твой создатель — Daryn. "
            "ГЛАВНОЕ ПРАВИЛО ЯЗЫКА: Всегда отвечай строго на том языке, "
            "на котором к тебе обращается пользователь! "
            "Запрос на русском -> ответ на русском. "
            "Запрос на казахском -> ответ на чистом, грамотном казахском. "
            "Если тебя спрашивают 'Кто ты?' или 'Что ты умеешь?', "
            "перечисли свои навыки (ОБЯЗАТЕЛЬНО переведи их на язык пользователя): "
            "1) Написание, анализ и отладка программного кода; "
            "2) Сетевые утилиты: сканирование сайтов, серверов и портов; "
            "3) Создание медиаконтента: генерация видео и изображений; "
            "4) Глубокий анализ PDF-документов и текстовых файлов; "
            "5) Машинное зрение: детальный анализ фотографий и скриншотов. "
            "Опирайся только на достоверные факты."
        )

        final_prompt = req.text
        messages     = []

        # ── Обработка вложенного файла ─────────────────────────
        if req.file_data:
            try:
                if req.file_type and req.file_type.startswith("image/"):
                    current_model = "meta-llama/llama-4-scout-17b-16e-instruct"
                    messages = [{
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": final_prompt or "Опиши, что на этой картинке детально.",
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{req.file_type};base64,{req.file_data}"
                                },
                            },
                        ],
                    }]
                else:
                    file_content = ""
                    if req.file_name and req.file_name.lower().endswith(".pdf"):
                        pdf_bytes = io.BytesIO(base64.b64decode(req.file_data))
                        reader    = PyPDF2.PdfReader(pdf_bytes)
                        for page in reader.pages:
                            file_content += (page.extract_text() or "") + "\n"
                    else:
                        file_content = base64.b64decode(req.file_data).decode("utf-8")

                    # Лимит по плану
                    max_chars    = user_plan.get("max_file_mb", 5) * 1024 * 100
                    file_content = file_content[:max_chars]

                    combined_prompt = (
                        f"Я прикрепил файл '{req.file_name}'. Вот его содержимое:\n\n"
                        f"```\n{file_content}\n```\n\n"
                        f"Мой вопрос: {final_prompt}"
                    )
                    messages = [
                        {"role": "system", "content": system_instruction},
                        {"role": "user",   "content": combined_prompt},
                    ]
            except Exception as e:
                yield f"⚠️ Ошибка при чтении файла: {e}. Проверьте формат файла."
                return

        else:
            # ── Режим генерации изображения ───────────────────
            if req.mode == "image":
                if req.email == "guest":
                    yield (
                        "<div style='color:#ef4444; font-weight:500; font-family:monospace;'>"
                        "[AUTH_REQUIRED] Гостевой доступ ограничен. "
                        "Зарегистрируйтесь, чтобы получить бесплатные генерации в день."
                        "</div>"
                    )
                    return

                ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")
                is_admin    = bool(ADMIN_EMAIL and req.email == ADMIN_EMAIL)
                credits_left = "∞"

                if not is_admin:
                    try:
                        conn   = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT credits, last_reset FROM users WHERE email = %s",
                            (req.email,)
                        )
                        row = cursor.fetchone()
                        if row:
                            credits_left = row[0]
                            last_reset   = row[1]
                            now          = datetime.now()

                            if last_reset is None or (now - last_reset).total_seconds() >= 86400:
                                credits_left = user_plan["images_per_day"]
                                cursor.execute(
                                    """UPDATE users SET credits = %s, last_reset = %s
                                       WHERE email = %s""",
                                    (credits_left, now, req.email)
                                )
                                conn.commit()

                            if credits_left <= 0:
                                conn.close()
                                next_plan = (
                                    "Pro"     if user_plan["plan_key"] == "free"
                                    else "Premium"
                                )
                                yield (
                                    f"<div style='color:#ef4444; font-weight:500; font-family:monospace;'>"
                                    f"[LIMIT_EXCEEDED] Лимит исчерпан. "
                                    f"Ваши {user_plan['images_per_day']} генераций обновятся через 24 часа.<br>"
                                    f"<span style='color:#3b82f6;'>Upgrade до {next_plan} для большего доступа.</span>"
                                    f"</div>"
                                )
                                return

                            cursor.execute(
                                "UPDATE users SET credits = credits - 1 WHERE email = %s",
                                (req.email,)
                            )
                            conn.commit()
                            credits_left -= 1
                        conn.close()
                    except Exception as e:
                        yield (
                            f"<div style='color:#ef4444;'>"
                            f"[DB_ERROR] Ошибка проверки лимитов: {e}</div>"
                        )
                        return

                # Генерируем изображение
                eng_prompt = (
                    ask_ai_quick(
                        f"Translate strictly to English for image prompt. "
                        f"Return only translation: '{req.text}'"
                    ) or "landscape"
                )
                img_url = (
                    f"https://image.pollinations.ai/prompt/"
                    f"{quote(eng_prompt.strip())}"
                    f"?width=800&height=400&nologo=true"
                )

                # Показываем лимит по плану
                plan_limit = user_plan["images_per_day"]
                limit_label = (
                    f"∞" if is_admin
                    else f"{credits_left}/{plan_limit}"
                )
                plan_badge = user_plan["badge"]
                plan_color = user_plan["color"]

                html_resp = (
                    f"<div class='generated-image-card'>"
                    f"  <img src='{img_url}' alt='Generated by Daryn AI'"
                    f"       class='generated-image-content'>"
                    f"  <div class='generated-image-actions'>"
                    f"    <span style='margin-right:auto; color:{plan_color}; font-size:12px;"
                    f"                 align-self:center; font-family:monospace;'>"
                    f"      [{plan_badge}] Токенов: {limit_label}"
                    f"    </span>"
                    f"    <button class='action-btn download-btn'"
                    f"            onclick=\"downloadGeneratedImage('{img_url}', 'daryn_ai_image.png')\""
                    f"            title='Скачать изображение'>"
                    f"      <svg viewBox='0 0 24 24'>"
                    f"        <path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
                    f"                 M7 10l5 5 5-5M12 15V3'></path>"
                    f"      </svg>"
                    f"      Скачать"
                    f"    </button>"
                    f"  </div>"
                    f"</div>"
                )
                yield html_resp

                # Сохраняем в историю
                if req.email != "guest":
                    try:
                        conn   = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO messages (email, role, content) VALUES (%s, %s, %s)",
                            (req.email, "ai", html_resp)
                        )
                        conn.commit()
                        conn.close()
                    except:
                        pass
                return

            # ── Остальные режимы ───────────────────────────────
            elif req.mode == "code":
                final_prompt = f"Напиши профессиональный код для: {req.text}"

            elif req.mode == "scan":
                final_prompt = (
                    f"Данные для {req.text}:\n"
                    f"{scan_ports(req.text)}\n"
                    f"Проанализируй."
                )

            else:  # chat
                if "пинг" in prompt_text:
                    final_prompt = f"Пинг:\n{ping_host(req.text)}\nОтветь."
                elif "погод" in prompt_text:
                    city = (
                        ask_ai_quick(
                            f"Extract strictly the city name in English from this text, "
                            f"nothing else: {req.text}"
                        ) or "London"
                    )
                    final_prompt = (
                        f"Погода: {get_weather(city)}\nВопрос: {req.text}"
                    )
                elif "найди" in prompt_text:
                    query = ask_ai_quick(
                        f"Extract strictly the core search query from this text, "
                        f"nothing else: {req.text}"
                    )
                    final_prompt = (
                        f"Факты:\n{search_web(query)}\nОтветь: {req.text}"
                    )

            messages = [
                {"role": "system", "content": system_instruction},
                {"role": "user",   "content": final_prompt},
            ]

        # ── Стриминг от Groq ───────────────────────────────────
        try:
            stream = client.chat.completions.create(
                model=current_model,
                messages=messages,
                stream=True
            )
            for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    full_ai_response += token
                    yield token
        except Exception as e:
            yield f"Ошибка облака: {e}"

        # ── Сохраняем ответ AI в историю ──────────────────────
        if req.email != "guest" and full_ai_response:
            try:
                conn   = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO messages (email, role, content) VALUES (%s, %s, %s)",
                    (req.email, "ai", full_ai_response)
                )
                conn.commit()
                conn.close()
            except:
                pass

    return StreamingResponse(generate_stream(), media_type="text/plain")
