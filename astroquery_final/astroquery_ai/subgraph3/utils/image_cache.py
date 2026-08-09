"""Image caching utilities for streaming processing."""

import os
import tempfile
from pathlib import Path
from typing import List
from PIL import Image
from .logger import get_logger


logger = get_logger(__name__)


class ImageCache:
    """
    Manages temporary image files for streaming PDF processing.

    Images are saved to disk and loaded on-demand to reduce memory usage.
    """

    def __init__(self, cache_dir: str = None):
        """
        Initialize image cache.

        Phase 3: 惰性创建目录 — import 期零 I/O 副作用,
        首次实际使用 (save/load/size) 时才 mkdir。

        Args:
            cache_dir: Directory for temporary images (default: system temp dir)
        """
        if cache_dir is None:
            self.cache_dir = Path(tempfile.gettempdir()) / "graph3_image_cache"
        else:
            self.cache_dir = Path(cache_dir)

    def _ensure_dir(self) -> None:
        """确保缓存目录存在 (惰性, 首次使用时调用)。"""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Image cache directory: {self.cache_dir}")

    def save_images(self, bibcode: str, images: List[Image.Image]) -> List[str]:
        """
        Save images to disk and return file paths.

        Args:
            bibcode: Paper bibcode (used as subdirectory name)
            images: List of PIL Image objects

        Returns:
            List of file paths
        """
        self._ensure_dir()
        # Create subdirectory for this paper
        paper_dir = self.cache_dir / bibcode.replace("/", "_").replace(":", "_")
        paper_dir.mkdir(parents=True, exist_ok=True)

        paths = []
        for idx, img in enumerate(images):
            path = paper_dir / f"page_{idx+1}.png"
            img.save(path, format="PNG")
            paths.append(str(path))

        logger.debug(f"Saved {len(paths)} images for {bibcode} to {paper_dir}")
        return paths

    def load_images(self, image_paths: List[str]) -> List[Image.Image]:
        """
        Load images from disk.

        Args:
            image_paths: List of image file paths

        Returns:
            List of PIL Image objects
        """
        images = []
        for path in image_paths:
            if not os.path.exists(path):
                logger.warning(f"Image file not found: {path}")
                continue

            img = Image.open(path)
            # Convert to RGB to ensure consistency
            if img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)

        logger.debug(f"Loaded {len(images)} images from disk")
        return images

    def cleanup(self, bibcode: str = None):
        """
        Clean up cached images.

        Args:
            bibcode: If specified, only delete this paper's images.
                    If None, delete all cached images.
        """
        if bibcode:
            paper_dir = self.cache_dir / bibcode.replace("/", "_").replace(":", "_")
            if paper_dir.exists():
                import shutil
                shutil.rmtree(paper_dir)
                logger.debug(f"Cleaned up cache for {bibcode}")
        else:
            if self.cache_dir.exists():
                import shutil
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                logger.debug("Cleaned up entire image cache")

    def get_cache_size(self) -> float:
        """
        Get total size of cached images in MB.

        Returns:
            Size in megabytes
        """
        if not self.cache_dir.exists():
            return 0.0
        total_size = 0
        for root, dirs, files in os.walk(self.cache_dir):
            for file in files:
                file_path = os.path.join(root, file)
                total_size += os.path.getsize(file_path)

        return total_size / (1024 * 1024)


# Global image cache instance
image_cache = ImageCache()
