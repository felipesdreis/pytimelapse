"""Tests for pytimelapse."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pytimelapse import Timelapse
from pytimelapse.timelapse import SUPPORTED_EXTENSIONS


class TestTimelapseInit:
    def test_defaults(self):
        tl = Timelapse(input_dir="./frames", output="out.mp4")
        assert tl.fps == 24
        assert tl.size is None
        assert tl.pattern is None

    def test_custom_params(self):
        tl = Timelapse(
            input_dir="./frames",
            output="out.mp4",
            fps=30,
            size=(1920, 1080),
            pattern="frame_*.jpg",
        )
        assert tl.fps == 30
        assert tl.size == (1920, 1080)
        assert tl.pattern == "frame_*.jpg"


class TestCollectFrames:
    def test_no_images_raises(self, tmp_path):
        tl = Timelapse(input_dir=str(tmp_path), output="out.mp4")
        with pytest.raises(FileNotFoundError):
            tl._collect_frames()

    def test_collects_supported_images(self, tmp_path):
        for ext in (".jpg", ".png"):
            (tmp_path / f"frame{ext}").touch()
        # Unsupported file should be ignored
        (tmp_path / "notes.txt").touch()

        tl = Timelapse(input_dir=str(tmp_path), output="out.mp4")
        frames = tl._collect_frames()
        names = [f.name for f in frames]
        assert "frame.jpg" in names
        assert "frame.png" in names
        assert "notes.txt" not in names

    def test_custom_pattern(self, tmp_path):
        (tmp_path / "img_001.jpg").touch()
        (tmp_path / "img_002.jpg").touch()
        (tmp_path / "other.jpg").touch()

        tl = Timelapse(input_dir=str(tmp_path), output="out.mp4", pattern="img_*.jpg")
        frames = tl._collect_frames()
        assert len(frames) == 2

    def test_frames_are_sorted(self, tmp_path):
        for name in ("c.jpg", "a.jpg", "b.jpg"):
            (tmp_path / name).touch()

        tl = Timelapse(input_dir=str(tmp_path), output="out.mp4")
        frames = tl._collect_frames()
        assert [f.name for f in frames] == ["a.jpg", "b.jpg", "c.jpg"]


class TestCreate:
    def test_import_error_without_cv2(self, tmp_path):
        (tmp_path / "frame.jpg").touch()
        tl = Timelapse(input_dir=str(tmp_path), output=str(tmp_path / "out.mp4"))

        with patch.dict("sys.modules", {"cv2": None}):
            with pytest.raises(ImportError, match="opencv-python"):
                tl.create()

    def test_creates_output_with_cv2(self, tmp_path):
        """Test create() calls cv2 correctly using mocks."""
        frame_path = tmp_path / "frame_001.jpg"
        frame_path.touch()
        output = tmp_path / "out.mp4"

        import numpy as np

        fake_img = np.zeros((480, 640, 3), dtype=np.uint8)

        mock_writer = MagicMock()
        mock_cv2 = MagicMock()
        mock_cv2.imread.return_value = fake_img
        mock_cv2.VideoWriter.return_value = mock_writer
        mock_cv2.VideoWriter_fourcc.return_value = 0x7634706D

        with patch.dict("sys.modules", {"cv2": mock_cv2}):
            tl = Timelapse(input_dir=str(tmp_path), output=str(output))
            result = tl.create(verbose=False)

        assert result == output
        mock_writer.write.assert_called_once()
        mock_writer.release.assert_called_once()
