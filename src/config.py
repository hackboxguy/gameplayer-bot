"""Configuration loader for gameplayer-bot.

Reads configs/game.ini and provides typed access to settings.
"""

import configparser
import os

DEFAULT_CONFIG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "configs", "game.ini"
)


class Config:
    """Loads and provides access to game.ini settings."""

    def __init__(self, path=None):
        self._parser = configparser.ConfigParser()
        self._path = path or DEFAULT_CONFIG
        if not os.path.exists(self._path):
            raise FileNotFoundError(f"Config not found: {self._path}")
        self._parser.read(self._path)

    @property
    def plugin_name(self):
        return self._parser.get("general", "plugin", fallback="chrome-dino")

    @property
    def camera_type(self):
        return self._parser.get("general", "camera_type", fallback="auto")

    @property
    def camera_device(self):
        return self._parser.getint("general", "camera_device", fallback=0)

    @property
    def camera_width(self):
        return self._parser.getint("general", "camera_width", fallback=640)

    @property
    def camera_height(self):
        return self._parser.getint("general", "camera_height", fallback=480)

    @property
    def camera_fps(self):
        return self._parser.getint("general", "camera_fps", fallback=60)

    @property
    def roi(self):
        """Returns (x1, y1, x2, y2) tuple for the game area ROI."""
        return (
            self._parser.getint("roi", "x1", fallback=0),
            self._parser.getint("roi", "y1", fallback=0),
            self._parser.getint("roi", "x2", fallback=self.camera_width),
            self._parser.getint("roi", "y2", fallback=self.camera_height),
        )

    def get(self, section, key, fallback=None):
        """Generic getter for plugin-specific settings."""
        return self._parser.get(section, key, fallback=fallback)

    def getint(self, section, key, fallback=0):
        return self._parser.getint(section, key, fallback=fallback)

    def getfloat(self, section, key, fallback=0.0):
        return self._parser.getfloat(section, key, fallback=fallback)
