"""Base class for gameplayer-bot game plugins."""


class GamePlugin:
    """Base class for game plugins.

    Each game plugin implements:
    - detect(frame): analyze camera frame, return game state dict
    - decide(state): given game state, return action dict
    - get_hid_report(action): convert action to raw HID report bytes

    Attributes:
        name: Plugin identifier (matches config section name).
        hid_type: Which HID device to use: "keyboard" or "mouse".
    """

    name = "unnamed"
    hid_type = "keyboard"

    def setup(self, config):
        """Called once at startup with the Config object.

        Override to read plugin-specific settings from game.ini.
        """
        pass

    def on_start(self, hid):
        """Called once before the game loop starts.

        Override to send startup input (e.g. spacebar to begin the game).
        Default is no-op.
        """
        pass

    def calibrate(self, frame):
        """Called once with the first captured frame.

        Override for one-time setup like detecting game area landmarks.
        """
        pass

    def detect(self, frame):
        """Process a camera frame and return game state.

        Args:
            frame: numpy array (H, W, 3) RGB, already cropped to ROI.

        Returns:
            dict with game-specific state.
        """
        raise NotImplementedError

    def decide(self, state):
        """Given game state, decide what action to take.

        Args:
            state: dict from detect().

        Returns:
            dict with action info, e.g. {"action": "jump"} or {"dx": 15}.
        """
        raise NotImplementedError

    def get_hid_report(self, action):
        """Convert an action to a raw HID report.

        Args:
            action: dict from decide().

        Returns:
            bytes: raw HID report to write to /dev/hidgN.
        """
        raise NotImplementedError
