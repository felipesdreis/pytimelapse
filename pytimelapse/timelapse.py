"""Core timelapse creation functionality."""

import os
import glob
from pathlib import Path
from typing import Optional, Tuple, List


SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif")


class Timelapse:
    """Creates a timelapse video from a sequence of images.

    Args:
        input_dir: Directory containing the source images.
        output: Path for the output video file.
        fps: Frames per second for the output video. Defaults to 24.
        size: Optional (width, height) tuple to resize frames. If None, uses
              the dimensions of the first image.
        pattern: Glob pattern to match image files. Defaults to all supported
                 image types in the input directory.
    """

    def __init__(
        self,
        input_dir: str,
        output: str,
        fps: int = 24,
        size: Optional[Tuple[int, int]] = None,
        pattern: Optional[str] = None,
    ) -> None:
        self.input_dir = Path(input_dir)
        self.output = Path(output)
        self.fps = fps
        self.size = size
        self.pattern = pattern

    def _collect_frames(self) -> List[Path]:
        """Collect and sort image files from the input directory."""
        if self.pattern:
            files = sorted(self.input_dir.glob(self.pattern))
        else:
            files = []
            for ext in SUPPORTED_EXTENSIONS:
                files.extend(self.input_dir.glob(f"*{ext}"))
                files.extend(self.input_dir.glob(f"*{ext.upper()}"))
            files = sorted(set(files))

        if not files:
            raise FileNotFoundError(
                f"No images found in '{self.input_dir}' matching "
                f"extensions {SUPPORTED_EXTENSIONS}"
            )
        return files

    def create(self, verbose: bool = True) -> Path:
        """Create the timelapse video.

        Args:
            verbose: If True, print progress information.

        Returns:
            Path to the created video file.

        Raises:
            FileNotFoundError: If no images are found in the input directory.
            ImportError: If opencv-python is not installed.
        """
        try:
            import cv2
        except ImportError as exc:
            raise ImportError(
                "opencv-python is required to create timelapse videos. "
                "Install it with: pip install opencv-python"
            ) from exc

        frames = self._collect_frames()

        if verbose:
            print(f"Found {len(frames)} frames in '{self.input_dir}'")

        # Determine output size from the first frame if not specified
        first = cv2.imread(str(frames[0]))
        if first is None:
            raise ValueError(f"Could not read image: {frames[0]}")

        h, w = first.shape[:2]
        out_size = self.size if self.size else (w, h)

        self.output.parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(self.output), fourcc, self.fps, out_size)

        try:
            for i, frame_path in enumerate(frames):
                img = cv2.imread(str(frame_path))
                if img is None:
                    if verbose:
                        print(f"  Warning: skipping unreadable frame {frame_path}")
                    continue

                if out_size != (img.shape[1], img.shape[0]):
                    img = cv2.resize(img, out_size)

                writer.write(img)

                if verbose and (i + 1) % 100 == 0:
                    print(f"  Processed {i + 1}/{len(frames)} frames...")
        finally:
            writer.release()

        if verbose:
            print(f"Timelapse saved to '{self.output}'")

        return self.output
