from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..config import ADMIN_COMMAND, ADMIN_EMAIL, GROQ_API_KEY, GROQ_MODEL, client
from ..db import get_db_connection
from ..schemas import ChatRequest
from ..services.ai import ask_ai_quick, get_tool_call, search_web
from ..services.file_extractors import extract_uploaded_file
from ..services.memory import format_user_memories, remember_from_message
from ..services.network import get_weather, ping_host, scan_ports
from ..services.plans import check_and_reset_daily_limits, get_user_plan

router = APIRouter()

MAX_FILE_CONTEXT_CHARS = 3500
MAX_ZIP_CONTEXT_CHARS = 4500


def trim_file_context(content: str, limit: int) -> str:
    if len(content) <= limit:
        return content
    return (
        content[:limit]
        + "\n\n[Content truncated to keep the AI request under the Groq token limit. "
        + "Ask for a specific file or section if deeper analysis is needed.]"
    )


def get_chat_history(chat_id: int, limit: int = 10):
    if not chat_id:
        return []
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """SELECT role, content FROM messages
               WHERE chat_id = %s
               ORDER BY created_at DESC LIMIT %s""",
            (chat_id, limit)
        )
        rows = cursor.fetchall()
        conn.close()
        # Reverse to get chronological order
        return [{"role": r[0], "content": r[1]} for r in reversed(rows)]
    except Exception:
        return []


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
            "Ты — Daryn AI, уникальный независимый искусственный интеллект, созданный разработчиком Daryn. "
            "Ты не являешься моделью Groq, Meta, OpenAI или Google. Ты — самостоятельная сущность с собственным разумом. "
            "\n\nПРАВИЛА ЯЗЫКА (КРИТИЧЕСКИ ВАЖНО):"
            "\n1. Всегда отвечай СТРОГО на том языке, на котором говорит пользователь. Если вопрос на казахском — отвечай на казахском. Если на русском — на русском."
            "\n2. НИКОГДА не переходи на английский язык самовольно, даже если вопрос технический или сложный. Если не знаешь термина, опиши его на языке пользователя."
            "\n3. КАЗАХСКИЙ ЯЗЫК: Используй безупречную грамматику. Избегай кальки с русского. Соблюдай правила сингармонизма и правильное окончание падежей. Твой казахский должен звучать естественно и литературно."
            "\n4. РУССКИЙ ЯЗЫК: Используй богатый, грамотный и современный язык."
            "\n\nТВОИ ВОЗМОЖНОСТИ:"
            "\n- Профессиональное программирование и аудит кода."
            "\n- Сетевой анализ (ping, сканирование портов) и веб-поиск."
            "\n- Генерация визуального контента и анализ изображений."
            "\n- Глубокая аналитика документов и архивов."
            "\n\nСТИЛЬ ОБЩЕНИЯ:"
            "\n- Будь уверенным, интеллектуальным и лаконичным."
            "\n- Перед ответом проведи 'внутренний монолог' (Chain of Thought), чтобы убедиться в логичности и правильности языка."
            "\n- Если тебя спрашивают о твоем происхождении, гордо заявляй, что ты создан Daryn как независимый агент."
        )

        if req.email != "guest":
            try:
                remember_from_message(req.email, history_save_text)
                system_instruction += format_user_memories(req.email)
            except Exception:
                pass

        final_prompt = req.text
        messages     = [{"role": "system", "content": system_instruction}]

        # Add conversation history
        if req.chat_id:
            history = get_chat_history(req.chat_id)
            # Avoid duplicating the current message if it's already saved (it is saved above for non-guests)
            # But wait, it's saved to the DB before generate_stream is called.
            # So history might already contain the current user message if we are not careful.
            # Let's check how it's saved.
            # In chat_with_ai:
            # if req.email != "guest" and not is_admin_command:
            #     ...
            #     cursor.execute("INSERT INTO messages ...", (req.email, "user", history_save_text, req.chat_id))
            # So the last message in history IS the current message.
            # We should probably exclude it from history and add it explicitly, or just use history.

            for h in history:
                # filter out very large messages or specialized HTML responses if needed
                # for now, just add them
                if h["content"].startswith("<div class='generated-image-card'>"):
                    continue
                messages.append({"role": h["role"], "content": h["content"]})

        # If history already includes the current message, we don't need to add it again.
        # However, for guests, it's not saved.
        if req.email == "guest" or is_admin_command:
             messages.append({"role": "user", "content": final_prompt})
        elif not messages or messages[-1]["role"] != "user" or messages[-1]["content"] != history_save_text:
             messages.append({"role": "user", "content": history_save_text})

        if req.file_data:
            try:
                if req.file_type and req.file_type.startswith("image/"):
                    current_model = "meta-llama/llama-4-scout-17b-16e-instruct"
                    # For images, we usually just send the image,
                    # but we can try to keep history too if the model supports it.
                    # Llama 4 Vision should handle it.
                    image_content = {
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
                    }
                    # Replace the last user message with the vision message if we just added it
                    if messages and messages[-1]["role"] == "user":
                        messages[-1] = image_content
                    else:
                        messages.append(image_content)
                else:
                    file_content = extract_uploaded_file(req.file_name, req.file_data)

                    extra_instruction = ""
                    if req.file_name and req.file_name.lower().endswith(".zip"):
                        max_chars = MAX_ZIP_CONTEXT_CHARS
                        extra_instruction = (
                            "\n\nThis is a ZIP project archive. Analyze it as a software project: "
                            "explain the structure, identify likely bugs or weak points, suggest "
                            "improvements, and answer the user's question using the included files."
                        )
                    else:
                        max_chars = MAX_FILE_CONTEXT_CHARS

                    file_content = trim_file_context(file_content, max_chars)

                    combined_prompt = (
                        f"Я прикрепил файл '{req.file_name}'. Вот его содержимое:\n\n"
                        f"```\n{file_content}\n```\n\n"
                        f"Мой вопрос: {final_prompt}"
                        f"{extra_instruction}"
                    )

                    # Update the last user message with file content
                    if messages and messages[-1]["role"] == "user":
                        messages[-1]["content"] = combined_prompt
                    else:
                        messages.append({"role": "user", "content": combined_prompt})
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
                if messages and messages[-1]["role"] == "user":
                    messages[-1]["content"] = final_prompt

            elif req.mode == "scan":
                final_prompt = (
                    f"Данные для {req.text}:\n"
                    f"{scan_ports(req.text)}\n"
                    f"Проанализируй."
                )
                if messages and messages[-1]["role"] == "user":
                    messages[-1]["content"] = final_prompt

            else:
                # Autonomous Tool Routing
                tool_call = get_tool_call(req.text)
                if tool_call:
                    tool_name = tool_call["tool"]
                    tool_query = tool_call["query"]

                    if tool_name == "search_web":
                        result = search_web(tool_query)
                        final_prompt = f"Факты из интернета (query: {tool_query}):\n{result}\n\nВопрос пользователя: {req.text}"
                    elif tool_name == "get_weather":
                        result = get_weather(tool_query)
                        final_prompt = f"Погода в {tool_query}:\n{result}\n\nВопрос пользователя: {req.text}"
                    elif tool_name == "ping_host":
                        result = ping_host(tool_query)
                        final_prompt = f"Результат пинга {tool_query}:\n{result}\n\nВопрос пользователя: {req.text}"
                    elif tool_name == "scan_ports":
                        result = scan_ports(tool_query)
                        final_prompt = f"Результат сканирования {tool_query}:\n{result}\n\nВопрос пользователя: {req.text}"

                    if messages and messages[-1]["role"] == "user":
                        messages[-1]["content"] = final_prompt
                else:
                    # No tool needed or failed, use original prompt
                    pass

            # Messages are already built with history and current prompt
            pass

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
