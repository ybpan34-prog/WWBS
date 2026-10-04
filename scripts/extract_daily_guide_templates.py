"""Extract Sola Guide navigation references from supplied game screenshots."""
import argparse
from pathlib import Path

from PIL import Image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("screenshot", type=Path)
    args = parser.parse_args()
    output = Path(__file__).resolve().parents[1] / "templates" / "daily"
    output.mkdir(parents=True, exist_ok=True)
    with Image.open(args.screenshot) as image:
        if image.size == (1179, 630):
            crop = image.crop((31, 242, 66, 285)).convert("RGB")
            crop.resize((57, 70), Image.Resampling.LANCZOS).save(output / "guide_battle_tab.png")
        elif image.size == (1920, 1080):
            # The unselected “无音清剿” row in the battle sidebar.
            image.crop((278, 750, 467, 792)).convert("RGB").save(
                output / "guide_tacet_section.png"
            )
        elif image.size in ((1920, 1118), (1920, 1119)):
            # Supplied material-page reference includes a 38px game title bar.
            client = image.crop((0, 38, 1920, 1118))
            client.crop((108, 52, 222, 88)).convert("RGB").save(
                output / "guide_material_title.png"
            )
        else:
            raise ValueError("Expected a 1179x630 or 1920x1080 Sola Guide screenshot")


if __name__ == "__main__":
    main()
