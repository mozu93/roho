from PIL import Image, ImageDraw, ImageFont
import os


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/YuGothM.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/arialbd.ttf",
    ]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _center_text(draw, text, font, canvas_size, color, y_offset=0):
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    x = (canvas_size - w) // 2 - bbox[0]
    y = (canvas_size - h) // 2 - bbox[1] + y_offset
    draw.text((x, y), text, fill=color, font=font)


def _make_frame(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 青グラデーション背景
    for i in range(size):
        ratio = i / size
        r = int(14  + ratio * 30)
        g = int(116 + ratio * 54)
        b = int(232 - ratio * 20)
        draw.line([(0, i), (size, i)], fill=(r, g, b, 255))

    # 丸角マスク
    mask = Image.new("L", (size, size), 0)
    radius = max(4, size // 6)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=radius, fill=255)
    img.putalpha(mask)

    if size >= 48:
        # 「労」大字
        f_main = _get_font(int(size * 0.55))
        _center_text(draw, "労", f_main, size, (255, 255, 255, 240), int(-size * 0.04))
        # 「保険名簿」小字
        f_sub = _get_font(int(size * 0.11))
        _center_text(draw, "保険名簿", f_sub, size, (255, 255, 255, 200), int(size * 0.28))
    else:
        # 小サイズは「労」のみ
        f_main = _get_font(max(8, int(size * 0.65)))
        _center_text(draw, "労", f_main, size, (255, 255, 255, 240), 0)

    return img


def create_icon():
    sizes = [16, 32, 48, 256]
    images = [_make_frame(s) for s in sizes]

    os.makedirs("assets/icons", exist_ok=True)
    images[0].save(
        "assets/icons/rouho.ico",
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=images[1:],
    )
    print("Icon generated: assets/icons/rouho.ico")


if __name__ == "__main__":
    create_icon()
