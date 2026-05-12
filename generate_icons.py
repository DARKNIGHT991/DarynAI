"""
Запустить локально для генерации иконок:
  pip install Pillow
  python generate_icons.py
Затем загрузить icon-192.png и icon-512.png в корень проекта.
"""

from PIL import Image, ImageDraw, ImageFont
import math

def create_daryn_icon(size: int, filename: str):
    # Фон
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = size * 0.05
    cx  = size / 2
    cy  = size / 2

    # Тёмный фон (скруглённый квадрат)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=size * 0.2,
        fill=(5, 5, 5, 255)
    )

    # Шестиугольник (логотип Daryn AI)
    hex_r = size * 0.38
    points = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        points.append((
            cx + hex_r * math.cos(angle),
            cy + hex_r * math.sin(angle)
        ))

    draw.polygon(points, outline=(59, 130, 246, 255), fill=None)

    # Обводка шестиугольника (толще)
    for offset in range(1, max(2, size // 64) + 1):
        pts_out = []
        for i in range(6):
            angle = math.radians(60 * i - 30)
            r = hex_r + offset
            pts_out.append((
                cx + r * math.cos(angle),
                cy + r * math.sin(angle)
            ))
        draw.polygon(pts_out, outline=(59, 130, 246, 180))

    # Буква D в центре
    font_size = int(size * 0.32)
    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except:
            font = ImageFont.load_default()

    text = "D"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    draw.text(
        (cx - tw / 2, cy - th / 2 - bbox[1]),
        text,
        font=font,
        fill=(59, 130, 246, 255)
    )

    img.save(filename, "PNG")
    print(f"✅ Создан: {filename} ({size}x{size})")


if __name__ == "__main__":
    create_daryn_icon(192, "icon-192.png")
    create_daryn_icon(512, "icon-512.png")
    print("🎉 Иконки готовы!")
