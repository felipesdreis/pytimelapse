"""Command-line interface for pytimelapse."""

import argparse
import sys

from .timelapse import Timelapse


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a timelapse video from a directory of images."
    )
    parser.add_argument("input_dir", help="Directory containing source images")
    parser.add_argument("output", help="Output video file path (e.g. timelapse.mp4)")
    parser.add_argument(
        "--fps",
        type=int,
        default=24,
        help="Frames per second for the output video (default: 24)",
    )
    parser.add_argument(
        "--size",
        nargs=2,
        type=int,
        metavar=("WIDTH", "HEIGHT"),
        help="Resize frames to WIDTH x HEIGHT",
    )
    parser.add_argument(
        "--pattern",
        help="Glob pattern to match image files (e.g. 'frame_*.jpg')",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress output",
    )

    args = parser.parse_args()

    size = tuple(args.size) if args.size else None

    tl = Timelapse(
        input_dir=args.input_dir,
        output=args.output,
        fps=args.fps,
        size=size,
        pattern=args.pattern,
    )

    try:
        tl.create(verbose=not args.quiet)
    except (FileNotFoundError, ValueError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
