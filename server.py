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
import PyPDF2
from urllib.parse import urlparse, quote
from fastapi import FastAPI
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

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"

if not GROQ_API_KEY:
    print("🚨 ВНИМАНИЕ: GROQ_API_KEY не найден!")
else:
    client = Groq(api_key=GROQ_API_KEY)

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("🚨 DATABASE_URL не найден! БД не подключена.")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL: return
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(255) NOT NULL, email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, email VARCHAR(255) NOT NULL, role VARCHAR(50) NOT NULL, content TEXT NOT NULL)''')
        conn.commit()
        conn.close()
    except Exception as e: print(f"🚨 Ошибка БД: {e}")

init_db()

def ask_ai_quick(prompt):
    try:
        res = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model="llama-3.1-8b-instant")
        return res.choices[0].message.content.strip()
    except: return ""

def search_web(query):
    try:
        results = DDGS().text(query, max_results=3)
        if not results: return "Ничего не найдено."
        return "\n".join([f"- {res['body']}" for res in results])
    except: return "Поиск временно недоступен."

def get_weather(city):
    try:
        res = requests.get(f"https://wttr.in/{city}?format=3", timeout=5)
        res.encoding = 'utf-8'
        if res.status_code == 200: return res.text
        return "Ошибка: город не найден."
    except: return "Служба погоды недоступна."

def clean_domain(text):
    match = re.search(r'([a-zA-Z0-9.-]+\.[a-zA-Z]{2,}|(?:\d{1,3}\.){3}\d{1,3})', text.lower())
    if match:
        domain = match.group(1)
        if domain.startswith("www."): 
            return domain[4:]
        return domain
    return text.strip()

def ping_host(host):
    try:
        clean_host = clean_domain(host)
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        result = subprocess.run(['ping', param, '4', '-4', clean_host], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return f"Пинг успешен:\n{result.stdout}" if result.returncode == 0 else f"Хост недоступен:\n{result.stderr or result.stdout}"
    except Exception as e: return f"Ошибка при пинге: {str(e)}"

def scan_ports(host):
    try:
        clean_host = clean_domain(host)
        ip = socket.gethostbyname(clean_host)
        open_ports = []
        for port in [21, 22, 25, 53, 80, 110, 143, 443, 3306, 3389, 8080]:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            if sock.connect_ex((ip, port)) == 0: open_ports.append(str(port))
            sock.close()
        return f"Цель: {clean_host} ({ip})\nОткрытые порты: {', '.join(open_ports)}" if open_ports else f"Цель: {clean_host} ({ip})\nОткрытых портов нет."
    except Exception as e: return f"Ошибка сканирования: {str(e)}"

class UserRegister(BaseModel): username: str; email: str; password: str
class UserLogin(BaseModel): email: str; password: str
class HistoryRequest(BaseModel): email: str

class ChatRequest(BaseModel): 
    text: str
    email: str
    mode: str = "chat"
    file_name: str | None = None
    file_type: str | None = None
    file_data: str | None = None

class ProfileUpdate(BaseModel):
    email: str
    new_username: str

@app.get("/")
def serve_frontend():
    try:
        with open("index.html", "r", encoding="utf-8") as f: return HTMLResponse(content=f.read())
    except FileNotFoundError: return HTMLResponse(content="<h1>Ошибка: index.html не найден!</h1>", status_code=404)

@app.post("/register")
def register(user: UserRegister):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT email FROM users WHERE email = %s', (user.email,))
        if cursor.fetchone(): conn.close(); return {"status": "error", "message": "Email уже зарегистрирован"}
        hashed = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute('INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s)', (user.username, user.email, hashed))
        conn.commit(); conn.close()
        return {"status": "success", "username": user.username, "email": user.email}
    except Exception as e: return {"status": "error", "message": f"Ошибка БД: {str(e)}"}

@app.post("/login")
def login(user: UserLogin):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT username, password_hash FROM users WHERE email = %s', (user.email,))
        row = cursor.fetchone(); conn.close()
        if not row: return {"status": "error", "message": "Email не найден"}
        if bcrypt.checkpw(user.password.encode('utf-8'), row[1].encode('utf-8')): return {"status": "success", "username": row[0], "email": user.email}
        return {"status": "error", "message": "Неверный пароль"}
    except Exception as e: return {"status": "error", "message": f"Ошибка БД: {str(e)}"}

@app.post("/history")
def get_history(req: HistoryRequest):
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('SELECT role, content FROM messages WHERE email = %s ORDER BY id ASC', (req.email,))
        rows = cursor.fetchall(); conn.close()
        return {"status": "success", "history": [{"role": r[0], "content": r[1]} for r in rows]}
    except: return {"status": "success", "history": []}

@app.post("/update_profile")
def update_profile(req: ProfileUpdate):
    if req.email == "guest": return {"status": "error", "message": "Гости не могут менять профиль."}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET username = %s WHERE email = %s', (req.new_username, req.email))
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/clear_history")
def clear_user_history(req: HistoryRequest):
    if req.email == "guest": return {"status": "success"}
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM messages WHERE email = %s', (req.email,))
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/chat")
def chat_with_ai(req: ChatRequest):
    prompt_text = req.text.lower()
    SECRET_ADMIN_COMMAND = os.getenv("ADMIN_COMMAND")
    is_admin_command = bool(SECRET_ADMIN_COMMAND and req.text.strip() == SECRET_ADMIN_COMMAND)
    
    history_save_text = req.text
    if req.file_name:
        history_save_text = f"📎 [{req.file_name}]\n" + req.text
        
    if req.email != "guest" and not is_admin_command:
        try:
            conn = get_db_connection(); cursor = conn.cursor()
            cursor.execute('INSERT INTO messages (email, role, content) VALUES (%s, %s, %s)', (req.email, 'user', history_save_text))
            conn.commit(); conn.close()
        except: pass
    
    def generate_stream():
        if not GROQ_API_KEY:
            yield "Ошибка сервера: Отсутствует GROQ_API_KEY."
            return

        if is_admin_command:
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('SELECT id, username, email FROM users')
                users_data = cursor.fetchall()
                conn.close()
                admin_response = "### 🛠 Секретная Панель Администратора\n\n| ID | Имя | Email |\n|---|---|---|\n"
                if not users_data: admin_response += "| - | Пусто | - |\n"
                else:
                    for u in users_data: admin_response += f"| {u[0]} | {u[1]} | {u[2]} |\n"
                yield admin_response
            except Exception as e: yield f"Ошибка доступа к БД: {e}"
            return

        full_ai_response = "" 
        
        system_instruction = (
            "Ты — Daryn AI, высокоинтеллектуальный ассистент и Dev-платформа. Твой создатель — Daryn. "
            "ГЛАВНОЕ ПРАВИЛО ЯЗЫКА: Всегда отвечай строго на том языке, на котором к тебе обращается пользователь! "
            "Запрос на русском -> ответ на русском. Запрос на казахском -> ответ на чистом, грамотном казахском. "
            "Если тебя спрашивают 'Кто ты?' или 'Что ты умеешь?', перечисли свои навыки (ОБЯЗАТЕЛЬНО переведи их на язык пользователя): "
            "1) Написание, анализ и отладка программного кода; "
            "2) Сетевые утилиты: сканирование сайтов, серверов и портов; "
            "3) Создание медиаконтента: генерация видео и изображений; "
            "4) Глубокий анализ PDF-документов и текстовых файлов; "
            "5) Машинное зрение: детальный анализ фотографий и скриншотов. "
            "Опирайся только на достоверные факты."
        )

        final_prompt = req.text
        current_model = GROQ_MODEL
        messages = []

        if req.file_data:
            try:
                if req.file_type and req.file_type.startswith("image/"):
                    current_model = "meta-llama/llama-4-scout-17b-16e-instruct"
                    messages = [{"role": "user", "content": [{"type": "text", "text": final_prompt if final_prompt else "Опиши, что на этой картинке детально."}, {"type": "image_url", "image_url": {"url": f"data:{req.file_type};base64,{req.file_data}"}}]}]
                else:
                    file_content = ""
                    if req.file_name.lower().endswith(".pdf"):
                        pdf_bytes = io.BytesIO(base64.b64decode(req.file_data))
                        reader = PyPDF2.PdfReader(pdf_bytes)
                        for page in reader.pages: file_content += (page.extract_text() or "") + "\n"
                    else: 
                        file_content = base64.b64decode(req.file_data).decode('utf-8')
                    file_content = file_content[:20000] 
                    combined_prompt = f"Я прикрепил файл '{req.file_name}'. Вот его содержимое:\n\nhttp://googleusercontent.com/immersive_entry_chip/0
