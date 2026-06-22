"""Download the brand fonts into images/fonts/ (run once before rendering).

All three are SIL Open Font License (free for commercial use). Google Fonts now
ships these as *variable* fonts; the image composer selects weights via the
font's Weight axis, so we only need one file per family.

    Lora            -> serif body / quotes
    Playfair Display -> display serif headlines
    Inter           -> sans-serif
"""
from pathlib import Path

import requests

DEST = Path(__file__).resolve().parent / "images" / "fonts"
RAW = "https://github.com/google/fonts/raw/main/ofl"

# saved_name -> URL (brackets percent-encoded for the raw host)
FONTS = {
    "Lora.ttf": f"{RAW}/lora/Lora%5Bwght%5D.ttf",
    "Playfair.ttf": f"{RAW}/playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf",
    "Inter.ttf": f"{RAW}/inter/Inter%5Bopsz,wght%5D.ttf",
}


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for name, url in FONTS.items():
        out = DEST / name
        if out.exists() and out.stat().st_size > 10_000:
            print(f"have {name}")
            continue
        r = requests.get(url, timeout=60)
        r.raise_for_status()
        out.write_bytes(r.content)
        print(f"downloaded {name} ({len(r.content):,} bytes)")


if __name__ == "__main__":
    main()
