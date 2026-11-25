"""
storage/image_logger.py - save raw frames, canvases and annotated overlays.

Writing JPEGs takes ~50-300 ms each on the Pi, so saving runs in a
background thread; the GUI shows the result immediately.
"""
import logging
import queue
import threading
from pathlib import Path

import cv2

log = logging.getLogger(__name__)


class ImageLogger:
    def __init__(self, jpeg_quality=95):
        self.q = queue.Queue()
        self.quality = int(jpeg_quality)
        self.t = threading.Thread(target=self._worker, daemon=True)
        self.t.start()

    def save(self, path: Path, img):
        if img is not None:
            self.q.put((Path(path), img.copy()))

    def _worker(self):
        while True:
            path, img = self.q.get()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                params = [cv2.IMWRITE_JPEG_QUALITY, self.quality] \
                    if path.suffix.lower() in (".jpg", ".jpeg") else []
                if not cv2.imwrite(str(path), img, params):
                    log.error("Could not write %s", path)
            except Exception:
                log.exception("Image save failed: %s", path)
            finally:
                self.q.task_done()

    def flush(self, timeout=10.0):
        """Wait until queued images are written (used before shutdown)."""
        self.q.join()
