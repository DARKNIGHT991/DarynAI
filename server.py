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
GROQ_MODEL = "llama-3.1-8b-instant"

if not GROQ_API_KEY:
    print("🚨 ВНИМАНИЕ: GROQ_API_KEY не найден в переменных окружения!")
else:
    client = Groq(api_key=GROQ_API_KEY)

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("🚨 DATABASE_URL не найден! БД не может быть подключена.")
    return psycopg2.connect(DATABASE_URL)

def init_db():
    if not DATABASE_URL: return
    try:
        conn = get_db_connection(); cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username VARCHAR(255) NOT NULL, email VARCHAR(255) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS messages (id SERIAL PRIMARY KEY, email VARCHAR(255) NOT NULL, role VARCHAR(50) NOT NULL, content TEXT NOT NULL)''')
        conn.commit(); conn.close()
    except Exception as e: print(f"🚨 Ошибка БД: {e}")

init_db()

# Функции инструментов
def ask_ai_quick(prompt):
    try:
        res = client.chat.completions.create(messages=[{"role": "user", "content": prompt}], model=GROQ_MODEL)
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
    text = text.strip(); text = re.sub(r'[<>"\'\s]', '', text)
    if not text.startswith(('http://', 'https://')): text = 'http://' + text
    return urlparse(text).netloc.split(':')[0]

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
        ip = socket.gethostbyname(clean_host); open_ports = []
        for port in [21, 22, 25, 53, 80, 110, 143, 443, 3306, 3389, 8080]:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM); sock.settimeout(0.5)
            if sock.connect_ex((ip, port)) == 0: open_ports.append(str(port))
            sock.close()
        return f"Цель: {clean_host} ({ip})\nОткрытые порты: {', '.join(open_ports)}" if open_ports else f"Цель: {clean_host} ({ip})\nОткрытых портов нет."
    except Exception as e: return f"Ошибка сканирования: {str(e)}"

# Модели API
class UserRegister(BaseModel): username: str; email: str; password: str
class UserLogin(BaseModel): email: str; password: str
class HistoryRequest(BaseModel): email: str

# НОВАЯ СТРУКТУРА ЗАПРОСА ЧАТА (с поддержкой файлов)
class ChatRequest(BaseModel): 
    text: str
    email: str
    mode: str = "chat"
    file_name: str = None
    file_type: str = None
    file_data: str = None

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

@app.post("/chat")
def chat_with_ai(req: ChatRequest):
    prompt_text = req.text.lower()
    is_admin_command = (req.text.strip() == "/admin/db/1103")
    
    # Сохраняем в БД (если есть файл, делаем пометку)
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

        full_ai_response = "" 
        system_instruction = "Тебя зовут Daryn AI. Твой создатель — Daryn. Общайся на грамотном русском языке. Если тебе отправили файл или код, внимательно проанализируй его."
        final_prompt = req.text
        current_model = GROQ_MODEL
        messages = []

        # --- ЛОГИКА ОБРАБОТКИ ФАЙЛОВ ---
        if req.file_data:
            try:
                # Если это КАРТИНКА (Vision)
                if req.file_type and req.file_type.startswith("image/"):
                    current_model = "llama-3.2-11b-vision"
                    messages = [
                        {"role": "user", "content": [
                            {"type": "text", "text": final_prompt if final_prompt else "Опиши, что на этой картинке детально."},
                            {"type": "image_url", "image_url": {"url": f"data:{req.file_type};base64,{req.file_data}"}}
                        ]}
                    ]
                # Если это ДОКУМЕНТ (PDF, TXT, Код)
                else:
                    file_content = ""
                    if req.file_name.lower().endswith(".pdf"):
                        pdf_bytes = io.BytesIO(base64.b64decode(req.file_data))
                        reader = PyPDF2.PdfReader(pdf_bytes)
                        for page in reader.pages:
                            file_content += (page.extract_text() or "") + "\n"
                    else:
                        file_content = base64.b64decode(req.file_data).decode('utf-8')
                    
                    # Обрезаем текст, чтобы не превысить лимит памяти нейросети (ок. 30к символов)
                    file_content = file_content[:20000] 
                    
                    combined_prompt = f"Я прикрепил файл '{req.file_name}'. Вот его содержимое:\n\n```\n{file_content}\n```\n\nМой вопрос: {final_prompt}"
                    messages = [{"role": "system", "content": system_instruction}, {"role": "user", "content": combined_prompt}]
            except Exception as e:
                yield f"⚠️ Ошибка при чтении файла: {str(e)}. Проверьте формат файла."
                return
        
        # --- СТАНДАРТНАЯ ЛОГИКА (Если файла нет) ---
        else:
            if req.mode == "image":
                eng_prompt = ask_ai_quick(f"Translate to English for image prompt: '{req.text}'") or "landscape"
                img_url = f"https://image.pollinations.ai/prompt/{quote(eng_prompt.strip())}?width=800&height=400&nologo=true"
                html_resp = f"<img src='{img_url}' style='border-radius:12px; width:100%;'>"
                yield html_resp
                if req.email != "guest":
                    try:
                        conn = get_db_connection(); cursor = conn.cursor()
                        cursor.execute('INSERT INTO messages (email, role, content) VALUES (%s, %s, %s)', (req.email, 'ai', html_resp))
                        conn.commit(); conn.close()
                    except: pass
                return
            elif req.mode == "code": final_prompt = f"Напиши профессиональный код для: {req.text}"
            elif req.mode == "scan": final_prompt = f"Данные для {req.text}:\n{scan_ports(ask_ai_quick(f'Extract domain: {req.text}'))}\nПроанализируй."
            else:
                if "пинг" in prompt_text: final_prompt = f"Пинг:\n{ping_host(ask_ai_quick(f'Extract domain: {req.text}'))}\nОтветь."
                elif "погод" in prompt_text: final_prompt = f"Погода: {get_weather(ask_ai_quick(f'Extract city English: {req.text}') or 'London')}\nВопрос: {req.text}"
                elif "найди" in prompt_text: final_prompt = f"Факты:\n{search_web(ask_ai_quick(f'Search query: {req.text}'))}\nОтветь: {req.text}"

            messages = [{"role": "system", "content": system_instruction}, {"role": "user", "content": final_prompt}]

        # --- ЗАПРОС К НЕЙРОСЕТИ ---
        try:
            stream = client.chat.completions.create(model=current_model, messages=messages, stream=True)
            for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    full_ai_response += token
                    yield token
        except Exception as e:
            yield f"Ошибка облака: {str(e)}"

        # Сохранение ответа
        if req.email != "guest" and full_ai_response:
            try:
                conn = get_db_connection(); cursor = conn.cursor()
                cursor.execute('INSERT INTO messages (email, role, content) VALUES (%s, %s, %s)', (req.email, 'ai', full_ai_response))
                conn.commit(); conn.close()
            except: pass

    return StreamingResponse(generate_stream(), media_type="text/plain")
