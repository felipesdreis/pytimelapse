# pytimelapse

A Python library for creating timelapse videos from a sequence of images.

## Installation

```bash
pip install pytimelapse
```

## Usage

```python
from pytimelapse import Timelapse

# Create a timelapse from a directory of images
tl = Timelapse(input_dir="./frames", output="timelapse.mp4", fps=24)
tl.create()
```

## Features

- Create timelapse videos from image sequences
- Configurable FPS (frames per second)
- Support for common image formats (JPG, PNG, BMP, TIFF)
- Optional resize and crop
- Progress reporting

## Requirements

- Python 3.8+
- OpenCV (`opencv-python`)
- Pillow

## License

MIT
