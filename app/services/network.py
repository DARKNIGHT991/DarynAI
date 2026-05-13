import platform
import re
import socket
import subprocess

import requests


def get_weather(city: str) -> str:
    try:
        res = requests.get(f"https://wttr.in/{city}?format=3", timeout=5)
        res.encoding = "utf-8"
        return res.text if res.status_code == 200 else "Ошибка: город не найден."
    except Exception:
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
        param = "-n" if platform.system().lower() == "windows" else "-c"
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
        ip = socket.gethostbyname(clean_host)
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
