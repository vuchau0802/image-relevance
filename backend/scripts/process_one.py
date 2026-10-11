import json

from app.config import PROJECT_ROOT
from app.services.vision import process_image
from app.services.retries import run_with_retries


def main():
    image_path = PROJECT_ROOT / "data" / "images" / "img_001.jpg"

    result = run_with_retries(
        lambda: process_image(image_path),
        max_attempts=3,
        base_delay=1.0,
    )

    print(result.model_dump_json(indent=2))

    output_folder = PROJECT_ROOT / "data" / "processed"
    output_folder.mkdir(parents=True, exist_ok=True)

    output_path = output_folder / f"{image_path.stem}.json"
    output_path.write_text(
        json.dumps(result.model_dump(), indent=2),
        encoding="utf-8",
    )

    print(f"Saved result: {output_path}")


if __name__ == "__main__":
    main()