from duckduckgo_search import DDGS

from ..config import client


def ask_ai_quick(prompt: str) -> str:
    if client is None:
        return ""
    try:
        res = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant"
        )
        return res.choices[0].message.content.strip()
    except Exception:
        return ""


def search_web(query: str) -> str:
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return "Ничего не найдено."
        return "\n".join([f"- {r['body']}" for r in results])
    except Exception:
        return "Поиск временно недоступен."
