import argparse
import json

from app.services.ranking import rank_post_images


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant-id", default="demo")
    parser.add_argument("--post-id", default="post_001")
    parser.add_argument("--top", type=int, default=5)
    args = parser.parse_args()

    try:
        result = rank_post_images(
            tenant_id=args.tenant_id,
            post_id=args.post_id,
            top=args.top,
        )
    except ValueError as error:
        parser.exit(1, f"{error}\n")

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()