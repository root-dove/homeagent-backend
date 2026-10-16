import argparse
import json
import os
import sys
from pathlib import Path
from typing import cast

from app.vision.gemini_analyzer import (
    GeminiImageAnalyzer,
    MediaResolution,
    VisionAnalysisError,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze one room image with the Gemini vision API.",
    )
    parser.add_argument("image", type=Path, help="Path to a local JPEG, PNG, or WebP image")
    parser.add_argument(
        "--model",
        default=os.getenv("GEMINI_VISION_MODEL", "gemini-3.8-flash"),
        help="Gemini vision model (default: GEMINI_VISION_MODEL or gemini-3.8-flash)",
    )
    parser.add_argument(
        "--media-resolution",
        choices=("low", "medium", "high"),
        default="high",
        help="Gemini image processing resolution (default: high)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=180,
        help="Gemini request timeout in seconds (default: 180)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("GEMINI_API_KEY environment variable is required.", file=sys.stderr)
        raise SystemExit(2)

    try:
        analysis = GeminiImageAnalyzer(
            api_key=api_key,
            model=args.model,
            timeout_seconds=args.timeout_seconds,
        ).analyze(
            args.image,
            media_resolution=cast(MediaResolution, args.media_resolution),
        )
    except (ValueError, VisionAnalysisError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error

    output = {
        "result": analysis.result.model_dump(mode="json"),
        "metadata": {
            "model": analysis.metadata.model,
            "model_version": analysis.metadata.model_version,
            "response_id": analysis.metadata.response_id,
            "input_tokens": analysis.metadata.input_tokens,
            "output_tokens": analysis.metadata.output_tokens,
            "total_tokens": analysis.metadata.total_tokens,
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
