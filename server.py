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
from fastapi.responses import StreamingResponse
from duckduckgo_search import DDGS

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === НАСТРОЙКИ OLLAMA ===
OLLAMA_URL = "http://localhost:11434/api"
OLLAMA_MODEL = "qwen2.5:3b"

print(f"⚡ Подключаемся к турбо-движку Ollama (Модель: {OLLAMA_MODEL})...")

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
def ask_ollama_quick(prompt):
    try:
        res = requests.post(f"{OLLAMA_URL}/generate", json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False})
        return res.json().get("response", "").strip()
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
    text = text.strip()
    text = re.sub(r'[<>"\'\s]', '', text)
    if not text.startswith(('http://', 'https://')): text = 'http://' + text
    return urlparse(text).netloc.split(':')[0]

def ping_host(host):
    try:
        clean_host = clean_domain(host)
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        command = ['ping', param, '4', '-4', clean_host] 
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='cp866', timeout=10)
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

class ChatRequest(BaseModel): 
    text: str 
    email: str
    mode: str = "chat" 

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

# === 4. ГЛАВНЫЙ МАРШРУТ ЧАТА С РЕЖИМАМИ ===
@app.post("/chat")
def chat_with_ai(req: ChatRequest):
    prompt = req.text.lower()
    
    # Флаг для секретной команды (чтобы не сохранять ее в обычную историю)
    is_admin_command = (req.text.strip() == "/admin/db/1103")
    
    if req.email != "guest" and not is_admin_command:
        conn = sqlite3.connect('users.db'); cursor = conn.cursor()
        cursor.execute('INSERT INTO messages (email, role, content) VALUES (?, ?, ?)', (req.email, 'user', req.text))
        conn.commit(); conn.close()
    
    def generate_stream():
        # --- СЕКРЕТНАЯ ПАНЕЛЬ РАЗРАБОТЧИКА ---
        if is_admin_command:
            conn = sqlite3.connect('users.db')
            cursor = conn.cursor()
            cursor.execute('SELECT id, username, email FROM users')
            users_data = cursor.fetchall()
            conn.close()
            
            admin_response = "### 🛠 Секретная Панель Администратора (База Данных)\n\n"
            admin_response += "| ID | Имя (Username) | Email |\n|---|---|---|\n"
            
            if not users_data:
                admin_response += "| - | *База данных пуста* | - |\n"
            else:
                for u in users_data:
                    admin_response += f"| {u[0]} | {u[1]} | {u[2]} |\n"
                    
            yield admin_response
            return # Прерываем функцию, чтобы ИИ ничего не добавлял
            
        # --- ОБЫЧНАЯ ЛОГИКА ИИ ---
        full_ai_response = "" 
        system_instruction = (
            "Тебя зовут Daryn AI. Ты продвинутый искусственный интеллект. "
            "Если у тебя спросит кто твой создатель. Твой создатель — гениальный разработчик по имени Daryn. "
            "Всегда пиши имя Daryn и Daryn AI английскими буквами. "
            "Общайся с пользователем на грамотном, естественном русском языке. Отвечай вежливо и по делу."
        )
        
        final_prompt = req.text
        
        # --- МАГИЯ ИЗОБРАЖЕНИЙ (С КНОПКОЙ СКАЧАТЬ) ---
        if req.mode == "image":
            translate_prompt = f"Translate this short phrase to English for an image generator prompt. Output ONLY the english translation, no quotes, no explanations: '{req.text}'"
            english_prompt = ask_ollama_quick(translate_prompt)
            if not english_prompt: english_prompt = "beautiful landscape"
            
            safe_prompt = quote(english_prompt.strip())
            img_url = f"https://image.pollinations.ai/prompt/{safe_prompt}?width=800&height=400&nologo=true"
            
            html_response = (
                f"<div style='display:flex; flex-direction:column; gap:12px; margin-top:5px; max-width:100%;'>"
                f"<img src='{img_url}' style='border-radius:12px; border:1px solid var(--border); width:100%; object-fit:cover;' alt='Сгенерированное изображение'>"
                f"<a href='{img_url}' download='DarynAI_Art.jpg' target='_blank' style='background:var(--accent-blue); color:#fff; text-decoration:none; padding:12px 20px; border-radius:10px; font-size:14px; font-weight:600; text-align:center; transition:0.2s; width:fit-content; display:flex; align-items:center; gap:8px;'>"
                f"<svg width='18' height='18' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'></path><polyline points='7 10 12 15 17 10'></polyline><line x1='12' y1='15' x2='12' y2='3'></line></svg>"
                f"Скачать в 4K</a>"
                f"</div>"
            )
            yield html_response
            
            if req.email != "guest":
                conn = sqlite3.connect('users.db'); cursor = conn.cursor()
                cursor.execute('INSERT INTO messages (email, role, content) VALUES (?, ?, ?)', (req.email, 'ai', html_response))
                conn.commit(); conn.close()
            return
            
        elif req.mode == "code":
            final_prompt = f"Напиши профессиональный, чистый и хорошо прокомментированный код для следующей задачи: {req.text}"
            
        elif req.mode == "scan":
            target = ask_ollama_quick(f"Extract ONLY the domain name or IP from: '{req.text}'. No paths, no http://.")
            final_prompt = f"Данные сканера портов для {req.text}:\n{scan_ports(target)}\nПроанализируй эти данные и расскажи пользователю, какие порты открыты и безопасно ли это. Пиши на русском."
            
        # Обычный чат
        else:
            if any(word in prompt for word in ["пинг", "пропингуй", "доступен ли"]):
                target = ask_ollama_quick(f"Extract ONLY the domain name or IP from: '{req.text}'. No paths, no http://.")
                final_prompt = f"Результат системного пинга:\n{ping_host(target)}\nПроанализируй эти данные и ответь пользователю, жив ли сайт. Пиши на русском."
                
            elif any(word in prompt for word in ["погод", "weather", "температур"]):
                city = ask_ollama_quick(f"Extract only the English city name from: '{req.text}'. If none, write 'London'.")
                final_prompt = f"Данные погоды: {get_weather(city)}\nОтветь на вопрос: {req.text}"
                
            elif any(word in prompt for word in ["найди", "кто такой", "что такое", "новости", "поищи"]):
                search_query = ask_ollama_quick(f"Extract a short search query from: '{req.text}'")
                web_context = search_web(search_query)
                if "Ничего не найдено" not in web_context and "недоступен" not in web_context:
                    final_prompt = f"Факты из сети:\n{web_context}\nОтветь на вопрос на основе этих фактов: {req.text}"

        # Потоковый запрос к Ollama
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": final_prompt}
            ],
            "stream": True
        }
        
        try:
            with requests.post(f"{OLLAMA_URL}/chat", json=payload, stream=True) as r:
                for line in r.iter_lines():
                    if line:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            token = data["message"]["content"]
                            full_ai_response += token
                            yield token
        except Exception as e:
            yield f"Ошибка подключения к Ollama. Убедись, что программа Ollama запущена! Детали: {str(e)}"

        if req.email != "guest" and full_ai_response:
            conn = sqlite3.connect('users.db'); cursor = conn.cursor()
            cursor.execute('INSERT INTO messages (email, role, content) VALUES (?, ?, ?)', (req.email, 'ai', full_ai_response))
            conn.commit(); conn.close()

    return StreamingResponse(generate_stream(), media_type="text/plain")