import base64
import io
from datetime import datetime
from urllib.parse import quote

import PyPDF2
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..config import ADMIN_COMMAND, ADMIN_EMAIL, GROQ_API_KEY, GROQ_MODEL, client
from ..db import get_db_connection
from ..schemas import ChatRequest
from ..services.ai import ask_ai_quick, search_web
from ..services.memory import format_user_memories, remember_from_message
from ..services.network import get_weather, ping_host, scan_ports
from ..services.plans import check_and_reset_daily_limits, get_user_plan

router = APIRouter()

@router.post("/chat")
def chat_with_ai(req: ChatRequest):
    prompt_text          = req.text.lower()
    is_admin_command = bool(
        ADMIN_COMMAND and req.text.strip() == ADMIN_COMMAND
    )

    user_plan = get_user_plan(req.email)

    history_save_text = req.text
    if req.file_name:
        history_save_text = f"📎 [{req.file_name}]\n" + req.text

    if req.email != "guest" and not is_admin_command:
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

        try:
            conn   = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (email, role, content, chat_id) VALUES (%s, %s, %s, %s)",
                (req.email, "user", history_save_text, req.chat_id)
            )
            conn.commit()
            conn.close()
        except:
            pass

    def generate_stream():
        if not GROQ_API_KEY:
            yield "Ошибка сервера: Отсутствует GROQ_API_KEY."
            return

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

        full_ai_response = ""
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

        if req.email != "guest":
            try:
                remember_from_message(req.email, history_save_text)
                system_instruction += format_user_memories(req.email)
            except Exception:
                pass

        final_prompt = req.text
        messages     = []

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
            if req.mode == "image":
                if req.email == "guest":
                    yield (
                        "<div style='color:#ef4444; font-weight:500; font-family:monospace;'>"
                        "[AUTH_REQUIRED] Гостевой доступ ограничен. "
                        "Зарегистрируйтесь, чтобы получить бесплатные генерации в день."
                        "</div>"
                    )
                    return

                is_admin = bool(ADMIN_EMAIL and req.email == ADMIN_EMAIL)
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

                if req.email != "guest":
                    try:
                        conn   = get_db_connection()
                        cursor = conn.cursor()
                        cursor.execute(
                            "INSERT INTO messages (email, role, content, chat_id) VALUES (%s, %s, %s, %s)",
                            (req.email, "ai", html_resp, req.chat_id)
                        )
                        if req.chat_id:
                            cursor.execute(
                                "UPDATE chats SET updated_at = NOW() WHERE id = %s",
                                (req.chat_id,)
                            )
                        conn.commit()
                        conn.close()
                    except:
                        pass
                return

            elif req.mode == "code":
                final_prompt = f"Напиши профессиональный код для: {req.text}"

            elif req.mode == "scan":
                final_prompt = (
                    f"Данные для {req.text}:\n"
                    f"{scan_ports(req.text)}\n"
                    f"Проанализируй."
                )

            else:
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

        if req.email != "guest" and full_ai_response:
            try:
                conn   = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO messages (email, role, content, chat_id) VALUES (%s, %s, %s, %s)",
                    (req.email, "ai", full_ai_response, req.chat_id)
                )
                # Auto-name chat on first AI response if title is still default
                if req.chat_id:
                    cursor.execute(
                        "SELECT title FROM chats WHERE id = %s AND email = %s",
                        (req.chat_id, req.email)
                    )
                    row = cursor.fetchone()
                    if row and row[0] in ("Новый чат", "New Chat", "Жаңа чат"):
                        auto_title = ask_ai_quick(
                            f"Generate a short chat title (max 5 words, no quotes) "
                            f"based on this user message: '{req.text[:200]}'. "
                            f"Respond ONLY with the title, same language as the message."
                        ) or req.text[:40]
                        auto_title = auto_title.strip('"\'').strip()[:60]
                        cursor.execute(
                            "UPDATE chats SET title = %s, updated_at = NOW() WHERE id = %s",
                            (auto_title, req.chat_id)
                        )
                    else:
                        cursor.execute(
                            "UPDATE chats SET updated_at = NOW() WHERE id = %s",
                            (req.chat_id,)
                        )
                conn.commit()
                conn.close()
            except:
                pass

    return StreamingResponse(generate_stream(), media_type="text/plain")
