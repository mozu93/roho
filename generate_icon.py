from PIL import Image, ImageDraw, ImageFont
import struct, zlib, io

def create_icon():
    """シンプルな青い四角アイコンを生成する"""
    sizes = [16, 32, 48, 256]
    images = []
    for size in sizes:
        img = Image.new("RGBA", (size, size), (37, 99, 235, 255))  # blue-600
        draw = ImageDraw.Draw(img)
        # "R" の文字
        font_size = max(8, size // 2)
        try:
            from PIL import ImageFont
            font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()
        bbox = draw.textbbox((0, 0), "R", font=font)
        x = (size - (bbox[2] - bbox[0])) // 2
        y = (size - (bbox[3] - bbox[1])) // 2
        draw.text((x, y), "R", fill="white", font=font)
        images.append(img)

    import os
    os.makedirs("assets/icons", exist_ok=True)
    images[0].save(
        "assets/icons/rouho.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print("アイコン生成完了: assets/icons/rouho.ico")

if __name__ == "__main__":
    create_icon()
