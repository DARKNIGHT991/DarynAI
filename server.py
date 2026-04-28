import os
import sqlite3
import bcrypt
import requests
import socket
import subprocess
import platform
import re
import json
from urllib.parse import urlparse, quote
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
# Добавили HTMLResponse для вывода сайта
from fastapi.responses import StreamingResponse, HTMLResponse 
from duckduckgo_search import DDGS
from dotenv import load_dotenv
from groq import Groq

# Загружаем переменные из .env
load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === НАСТРОЙКИ GROQ API (ОБЛАКО) ===
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "GROQ_MODEL = "llama-3.1-8b-instant"

if not GROQ_API_KEY:
    print("🚨 ВНИМАНИЕ: GROQ_API_KEY не найден в переменных окружения!")
else:
    client = Groq(api_key=GROQ_API_KEY)

# === 1. БАЗА ДАННЫХ ===
def init_db():
    conn = sqlite3.connect('users.db')
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL)''')
    conn.commit()
    conn.close()

init_db()

# === 2. ФУНКЦИИ И ИНСТРУМЕНТЫ ===
def ask_ai_quick(prompt):
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
        )
        return chat_completion.choices[0].message.content.strip()
    except Exception as e:
        return ""

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
    text = text.strip()
    text = re.sub(r'[<>"\'\s]', '', text)
    if not text.startswith(('http://', 'https://')): text = 'http://' + text
    return urlparse(text).netloc.split(':')[0]

def ping_host(host):
    try:
        clean_host = clean_domain(host)
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '4', '-4', clean_host] 
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0: return f"Пинг успешен:\n{result.stdout}"
        else: return f"Хост недоступен:\n{result.stderr or result.stdout}"
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
        if open_ports: return f"Цель: {clean_host} ({ip})\nОткрытые порты: {', '.join(open_ports)}"
        else: return f"Цель: {clean_host} ({ip})\nОткрытых базовых портов не найдено."
    except Exception as e: return f"Ошибка сканирования: {str(e)}"

# === 3. МАРШРУТЫ АПИ ===
class UserRegister(BaseModel): username: str; email: str; password: str
class UserLogin(BaseModel): email: str; password: str
class HistoryRequest(BaseModel): email: str
class ChatRequest(BaseModel): text: str; email: str; mode: str = "chat"

# -----------------------------------------------------
# НОВЫЙ МАРШРУТ: Выдача самого сайта (index.html)
# -----------------------------------------------------
@app.get("/")
def serve_frontend():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse(content="<h1>Ошибка: файл index.html не найден! Убедитесь, что он лежит в одной папке с server.py</h1>", status_code=404)

@app.post("/register")
def register(user: UserRegister):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT email FROM users WHERE email = ?', (user.email,))
    if cursor.fetchone(): return {"status": "error", "message": "Email уже зарегистрирован"}
    hashed = bcrypt.hashpw(user.password.encode('utf-8'), bcrypt.gensalt())
    cursor.execute('INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)', (user.username, user.email, hashed))
    conn.commit(); conn.close()
    return {"status": "success", "username": user.username, "email": user.email}

@app.post("/login")
def login(user: UserLogin):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT username, password_hash FROM users WHERE email = ?', (user.email,))
    row = cursor.fetchone(); conn.close()
    if not row: return {"status": "error", "message": "Email не найден"}
    if bcrypt.checkpw(user.password.encode('utf-8'), row[1]): return {"status": "success", "username": row[0], "email": user.email}
    return {"status": "error", "message": "Неверный пароль"}

@app.post("/history")
def get_history(req: HistoryRequest):
    conn = sqlite3.connect('users.db'); cursor = conn.cursor()
    cursor.execute('SELECT role, content FROM messages WHERE email = ? ORDER BY id ASC', (req.email,))
    rows = cursor.fetchall(); conn.close()
    return {"status": "success", "history": [{"role": r[0], "content": r[1]} for r in rows]}

# === 4. ГЛАВНЫЙ МАРШРУТ ЧАТА ===
@app.post("/chat")
def chat_with_ai(req: ChatRequest):
    prompt_text = req.text.lower()
    is_admin_command = (req.text.strip() == "/admin/db/1103")
    
    if req.email != "guest" and not is_admin_command:
        conn = sqlite3.connect('users.db'); cursor = conn.cursor()
        cursor.execute('INSERT INTO messages (email, role, content) VALUES (?, ?, ?)', (req.email, 'user', req.text))
        conn.commit(); conn.close()
    
    def generate_stream():
        if not GROQ_API_KEY:
            yield "Ошибка сервера: Отсутствует GROQ_API_KEY. Добавьте его в переменные окружения Render."
            return

        if is_admin_command:
            conn = sqlite3.connect('users.db'); cursor = conn.cursor()
            cursor.execute('SELECT id, username, email FROM users')
            users_data = cursor.fetchall(); conn.close()
            admin_response = "### 🛠 Секретная Панель Администратора\n\n| ID | Имя | Email |\n|---|---|---|\n"
            if not users_data: admin_response += "| - | Пусто | - |\n"
            else:
                for u in users_data: admin_response += f"| {u[0]} | {u[1]} | {u[2]} |\n"
            yield admin_response
            return

        full_ai_response = "" 
        system_instruction = (
            "Тебя зовут Daryn AI. Твой создатель — Daryn. "
            "Всегда пиши имя Daryn и Daryn AI английскими буквами. "
            "Общайся на грамотном русском языке."
        )
        
        final_prompt = req.text

        if req.mode == "image":
            translate_prompt = f"Translate to English for image prompt, output only translation: '{req.text}'"
            english_prompt = ask_ai_quick(translate_prompt) or "landscape"
            img_url = f"https://image.pollinations.ai/prompt/{quote(english_prompt.strip())}?width=800&height=400&nologo=true"
            
            html_response = (
                f"<div style='display:flex; flex-direction:column; gap:12px; margin-top:5px;'>"
                f"<img src='{img_url}' style='border-radius:12px; border:1px solid var(--border); width:100%;' alt='Art'>"
                f"<a href='{img_url}' download='DarynAI_Art.jpg' target='_blank' style='background:var(--accent-blue); color:#fff; text-decoration:none; padding:12px 20px; border-radius:10px; font-weight:600; text-align:center; width:fit-content; display:flex; align-items:center; gap:8px;'>"
                f"Скачать в 4K</a></div>"
            )
            yield html_response
            if req.email != "guest":
                conn = sqlite3.connect('users.db'); cursor = conn.cursor()
                cursor.execute('INSERT INTO messages (email, role, content) VALUES (?, ?, ?)', (req.email, 'ai', html_response))
                conn.commit(); conn.close()
            return

        elif req.mode == "code":
            final_prompt = f"Напиши профессиональный код для: {req.text}"
        elif req.mode == "scan":
            target = ask_ai_quick(f"Extract only domain/IP: {req.text}")
            final_prompt = f"Данные сканера для {req.text}:\n{scan_ports(target)}\nПроанализируй на русском."
        else:
            if any(w in prompt_text for w in ["пинг", "пропингуй"]):
                target = ask_ai_quick(f"Extract only domain/IP: {req.text}")
                final_prompt = f"Результат пинга:\n{ping_host(target)}\nОтветь на русском."
            elif any(w in prompt_text for w in ["погод", "weather"]):
                city = ask_ai_quick(f"Extract city name in English: {req.text}") or "London"
                final_prompt = f"Погода: {get_weather(city)}\nОтветь на вопрос: {req.text}"
            elif any(w in prompt_text for w in ["найди", "поищи"]):
                search_query = ask_ai_quick(f"Search query for: {req.text}")
                final_prompt = f"Факты из сети:\n{search_web(search_query)}\nОтветь на русском: {req.text}"

        try:
            stream = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[{"role": "system", "content": system_instruction}, {"role": "user", "content": final_prompt}],
                stream=True,
            )
            for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    full_ai_response += token
                    yield token
        except Exception as e:
            yield f"Ошибка облака: {str(e)}"

        if req.email != "guest" and full_ai_response:
            conn = sqlite3.connect('users.db'); cursor = conn.cursor()
            cursor.execute('INSERT INTO messages (email, role, content) VALUES (?, ?, ?)', (req.email, 'ai', full_ai_response))
            conn.commit(); conn.close()

    return StreamingResponse(generate_stream(), media_type="text/plain")
