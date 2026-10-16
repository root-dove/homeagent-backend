import argparse
import json
import os
import sys
from pathlib import Path
from typing import Literal, cast

from app.vision.openai_analyzer import OpenAIImageAnalyzer, VisionAnalysisError

ImageDetail = Literal["auto", "low", "high", "original"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze one room image with the OpenAI vision API.",
    )
    parser.add_argument("image", type=Path, help="Path to a local JPEG, PNG, or WebP image")
    parser.add_argument(
        "--model",
        default=os.getenv("OPENAI_VISION_MODEL", "gpt-5.5"),
        help="OpenAI vision-capable model (default: OPENAI_VISION_MODEL or gpt-5.5)",
    )
    parser.add_argument(
        "--detail",
        choices=("auto", "low", "high", "original"),
        default="high",
        help="Image detail level sent to the API (default: high)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        print("OPENAI_API_KEY environment variable is required.", file=sys.stderr)
        raise SystemExit(2)

    try:
        analysis = OpenAIImageAnalyzer(api_key=api_key, model=args.model).analyze(
            args.image,
            detail=cast(ImageDetail, args.detail),
        )
    except (ValueError, VisionAnalysisError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error

    output = {
        "result": analysis.result.model_dump(mode="json"),
        "metadata": {
            "model": analysis.metadata.model,
            "response_id": analysis.metadata.response_id,
            "input_tokens": analysis.metadata.input_tokens,
            "output_tokens": analysis.metadata.output_tokens,
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
