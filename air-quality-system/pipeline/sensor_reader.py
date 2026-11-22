"""KCO2-HW-01 — InfluxDB online sensor reader. Implementation owned by teammate."""

IMPLEMENTED = False


class WaitingForData(Exception):
    """The reader has not collected enough usable, fresh history yet."""


class SensorReader:
    def __init__(self, config):
        """Receive the influxdb configuration mapping; create the client here."""
        raise NotImplementedError("KCO2-HW-01 — InfluxDB online sensor reader")

    def get_recent_readings(self):
        """Return oldest-to-newest dicts with timestamp, co2, temperature, humidity.

        timestamp: timezone-aware ISO 8601; co2: ppm; temperature: Celsius;
        humidity: percent. Include the history required by HW-02. Raise
        WaitingForData for insufficient history. Do not invent readings.
        """
        raise NotImplementedError

    def close(self):
        """Release database resources when stopped."""
