"""Bounded HTTP calls to the ESP32; acknowledgement is not proof of rotation."""
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class FanError(RuntimeError):
    pass


class FanController:
    def __init__(self, url, token, timeout_seconds=2):
        parsed = urlsplit(url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("esp32.url must be an http:// hostname or IP without credentials")
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError("esp32.url must not contain a path, query or fragment")
        if not isinstance(token, str) or len(token) < 16 or token == "CHANGE_ME":
            raise ValueError("Set a matching 16+ character ESP32 token in config.yaml and ESP32.ino")
        if not 0 < timeout_seconds <= 5:
            raise ValueError("ESP32 timeout must be between 0 and 5 seconds")
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
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                result = json.loads(response.read(4096))
        except (OSError, ValueError, urllib.error.URLError) as exc:
            raise FanError("ESP32 request failed; check address, token, firmware and network") from exc
        if not isinstance(result, dict):
            raise FanError("Invalid ESP32 response")
        return result

    def set_state(self, fan_on):
        if type(fan_on) is not bool:
            raise ValueError("fan_on must be a boolean")
        state = "on" if fan_on else "off"
        result = self._request("/fan", state)
        if result.get("command_applied") is not True or result.get("state") != state:
            raise FanError("ESP32 did not acknowledge the requested state")
        return result

    def status(self):
        result = self._request("/fan")
        if result.get("state") not in ("on", "off"):
            raise FanError("Invalid ESP32 fan status")
        return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None
