"""Bounded HTTP calls to the ESP32 fan endpoint."""
import json
import logging
import urllib.request
from urllib.parse import urlsplit


logger = logging.getLogger(__name__)


class FanController:
    def __init__(self, url, token, timeout_seconds=2):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or not parsed.hostname:
            raise ValueError("esp32.url must be an http:// hostname or IP")
        if not isinstance(token, str) or len(token) < 16 or token == "CHANGE_ME":
            raise ValueError("Set a matching 16+ character ESP32 token in config.yaml and ESP32.ino")
        if not 0 < timeout_seconds <= 5:
            raise ValueError("ESP32 timeout must be between 0 and 5 seconds")
        self.last_acknowledged_state = None
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout_seconds
        # Local device traffic should not pass through a system HTTP proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _request(self, path, state=None):
        body = None if state is None else json.dumps({"state": state}).encode()
        request = urllib.request.Request(
            self.url + path, data=body,
            headers={"Content-Type": "application/json", "X-API-Key": self.token},
            method="GET" if body is None else "POST",
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            return json.loads(response.read(4096))

    def set_state(self, fan_on):
        state = "on" if fan_on else "off"
        try:
            result = self._request("/fan", state)
            if result.get("command_applied") is not True or result.get("state") != state:
                raise RuntimeError("ESP32 did not acknowledge the requested state")
        except Exception:
            self.last_acknowledged_state = None
            logger.warning("Fan %s command failed; output state unknown", state.upper())
            raise
        if self.last_acknowledged_state != state:
            logger.info("Fan %s acknowledged", state.upper())
        self.last_acknowledged_state = state
        return result

    def status(self):
        result = self._request("/fan")
        return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
