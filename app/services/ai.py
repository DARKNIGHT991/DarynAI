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


import json

def get_tool_call(prompt: str) -> dict | None:
    if client is None:
        return None

    tools_description = """
    Available tools:
    - search_web(query): Use when user asks for information you don't know, latest news, or specific facts.
    - get_weather(city): Use when user asks about weather in a specific city.
    - ping_host(host): Use when user wants to check if a website or server is up.
    - scan_ports(host): Use when user wants to see open ports on a host.
    - none: Use when no tool is needed.
    """

    routing_prompt = f"""
    You are a routing agent for Daryn AI. Analyze the user prompt and decide if any tool is needed.
    {tools_description}

    Return ONLY a JSON object:
    {{"tool": "tool_name", "query": "optimized search query or argument"}}
    If no tool is needed, return {{"tool": "none", "query": ""}}.

    User prompt: {prompt}
    """

    try:
        res = client.chat.completions.create(
            messages=[{"role": "system", "content": "You are a helpful assistant that only outputs JSON."},
                      {"role": "user", "content": routing_prompt}],
            model="llama-3.1-8b-instant",
            response_format={"type": "json_object"}
        )
        data = json.loads(res.choices[0].message.content.strip())
        if data.get("tool") and data["tool"] != "none":
            return data
        return None
    except Exception:
        return None


def search_web(query: str) -> str:
    try:
        results = DDGS().text(query, max_results=3)
        if not results:
            return "Ничего не найдено."
        return "\n".join([f"- {r['body']}" for r in results])
    except Exception:
        return "Поиск временно недоступен."
