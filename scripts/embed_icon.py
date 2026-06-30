"""EXE にアイコンリソースを埋め込むスクリプト (CI 用)

Usage: python scripts/embed_icon.py <exe_path> <ico_path>
"""
import struct
import sys

import win32api


def embed_icon(exe_path: str, ico_path: str) -> None:
    with open(ico_path, "rb") as f:
        ico_data = f.read()

    count = struct.unpack_from("<H", ico_data, 4)[0]
    entries = []
    for i in range(count):
        off = 6 + i * 16
        w, h, _cc, _res, planes, bpp, sz, offset = struct.unpack_from("<BBBBHHIi", ico_data, off)
        if w == 0:
            w = 256
        if h == 0:
            h = 256
        entries.append((w, h, ico_data[offset : offset + sz]))

    handle = win32api.BeginUpdateResource(exe_path, False)
    for idx, (w, h_img, data) in enumerate(entries, 1):
        win32api.UpdateResource(handle, 3, idx, data)

    grp = struct.pack("<HHH", 0, 1, len(entries))
    for idx, (w, h_img, data) in enumerate(entries, 1):
        grp += struct.pack(
            "<BBBBHHIH",
            w if w < 256 else 0,
            h_img if h_img < 256 else 0,
            0, 0, 1, 32, len(data), idx,
        )
    win32api.UpdateResource(handle, 14, 1, grp)
    win32api.EndUpdateResource(handle, False)
    print(f"Embedded {len(entries)} icon sizes into {exe_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/embed_icon.py <exe_path> <ico_path>")
        sys.exit(1)
    embed_icon(sys.argv[1], sys.argv[2])
