"""Camera wrapper for gameplayer-bot.

Supports:
- CSI camera via picamera2 (libcamera) — default on Raspberry Pi
- USB camera via OpenCV (V4L2) — for USB webcams like Logitech Brio
"""

import cv2
import numpy as np

try:
    from picamera2 import Picamera2
    HAS_PICAMERA2 = True
except ImportError:
    HAS_PICAMERA2 = False


class CSICamera:
    """CSI camera capture via picamera2."""

    def __init__(self, width=640, height=480, fps=60):
        if not HAS_PICAMERA2:
            raise RuntimeError(
                "picamera2 not available. Install with: "
                "sudo apt install python3-picamera2"
            )
        self._width = width
        self._height = height
        self._fps = fps
        self._camera = None

    def start(self):
        """Initialize and start the camera."""
        self._camera = Picamera2()
        config = self._camera.create_video_configuration(
            main={
                "size": (self._width, self._height),
                "format": "RGB888",
            },
            controls={"FrameRate": self._fps},
        )
        self._camera.configure(config)
        self._camera.start()

    def capture(self):
        """Capture a single frame as a numpy array (H, W, 3) RGB."""
        if self._camera is None:
            raise RuntimeError("Camera not started. Call start() first.")
        return self._camera.capture_array()

    def stop(self):
        """Stop the camera."""
        if self._camera is not None:
            self._camera.stop()
            self._camera.close()
            self._camera = None


class USBCamera:
    """USB camera capture via OpenCV (V4L2)."""

    def __init__(self, width=640, height=480, fps=60, device=0):
        self._width = width
        self._height = height
        self._fps = fps
        self._device = device
        self._cap = None

    def start(self):
        """Open the USB camera."""
        self._cap = cv2.VideoCapture(self._device, cv2.CAP_V4L2)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"Cannot open USB camera (device {self._device}). "
                "Check: ls /dev/video*"
            )
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap.set(cv2.CAP_PROP_FPS, self._fps)

    def capture(self):
        """Capture a single frame as a numpy array (H, W, 3) RGB."""
        if self._cap is None:
            raise RuntimeError("Camera not started. Call start() first.")
        ret, frame = self._cap.read()
        if not ret:
            raise RuntimeError("Failed to capture frame from USB camera.")
        # OpenCV captures in BGR, convert to RGB for consistency
        return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    def stop(self):
        """Release the USB camera."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None


class DummyCamera:
    """Fake camera for testing without hardware.

    Returns a solid white frame (simulates blank game screen).
    """

    def __init__(self, width=640, height=480, fps=60):
        self._width = width
        self._height = height

    def start(self):
        pass

    def capture(self):
        return np.full((self._height, self._width, 3), 255, dtype=np.uint8)

    def stop(self):
        pass


def _has_csi_camera():
    """Check if a CSI camera (not USB) is available via libcamera."""
    if not HAS_PICAMERA2:
        return False
    try:
        cam = Picamera2()
        # cam.camera.id contains the full device path, e.g.:
        #   CSI:  '/base/soc/i2c0mux/i2c@1/imx219@10'
        #   USB:  '/base/scb/pcie@7d500000/pci@0,0/usb@0,0-1:1.0-046d:085e'
        cam_id = cam.camera.id if hasattr(cam.camera, 'id') else ""
        cam.close()
        # USB/UVC cameras have "usb" in their device path
        if "usb" in cam_id.lower():
            return False
        return True
    except Exception:
        return False


def create_camera(camera_type="auto", width=640, height=480, fps=60, device=0):
    """Factory function to create the appropriate camera.

    Args:
        camera_type: "csi", "usb", "dummy", or "auto".
            auto: tries CSI first, falls back to USB.
        width, height, fps: capture settings.
        device: V4L2 device index for USB cameras (default 0).

    Returns:
        Camera instance with start()/capture()/stop() interface.
    """
    if camera_type == "csi":
        return CSICamera(width, height, fps)
    elif camera_type == "usb":
        return USBCamera(width, height, fps, device)
    elif camera_type == "dummy":
        return DummyCamera(width, height, fps)
    elif camera_type == "auto":
        if HAS_PICAMERA2 and _has_csi_camera():
            return CSICamera(width, height, fps)
        return USBCamera(width, height, fps, device)
    else:
        raise ValueError(f"Unknown camera type: {camera_type}")
