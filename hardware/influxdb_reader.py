
"""
InfluxDB reader for the CO2 project.

Reads CO2, temperature, and relative humidity measurements
from InfluxDB 3.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
from influxdb_client_3 import InfluxDBClient3

# --------------------------------------------------
# Configuration
# --------------------------------------------------
"""
This is read from the environment variables:

    INFLUXDB_HOST:
        InfluxDB server URL. Default: http://localhost:8181

    INFLUXDB_TOKEN:
        Authentication token. Required.

    INFLUXDB_DATABASE:
        InfluxDB database name. Default: co2db

    INFLUXDB_MEASUREMENT:
        Sensor measurement/table name. Default: scd41

Required sensor fields:
    co2: Carbon dioxide concentration (ppm)
    temp_c: Temperature (degrees Celsius)
    rh: Relative humidity (percent)

Database configuration:
      This project uses InfluxDB 3 Core.
      Database: co2db
      Measurement: scd41
"""

INFLUXDB_HOST = os.getenv(
    "INFLUXDB_HOST",
    "http://localhost:8181"
)

INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN")

INFLUXDB_DATABASE = os.getenv(
    "INFLUXDB_DATABASE",
    "co2db"
)

INFLUXDB_MEASUREMENT = os.getenv(
    "INFLUXDB_MEASUREMENT",
    "scd41"
)

# Expected sensor field names
CO2_FIELD = os.getenv("INFLUXDB_CO2_FIELD", "co2")
TEMPERATURE_FIELD = os.getenv("INFLUXDB_TEMPERATURE_FIELD", "temp_c")
HUMIDITY_FIELD = os.getenv("INFLUXDB_HUMIDITY_FIELD", "rh")

# Maximum limit for age of a reading, in seconds
DEFAULT_MAX_AGE_SECONDS = 60


# --------------------------------------------------
# InfluxDB Connection
# --------------------------------------------------

def get_influxdb_client() -> InfluxDBClient3:
    """
    Create and return an InfluxDB 3 client.

    Returns:
        InfluxDBClient3: Connected InfluxDB client.

    Raises:
        ValueError: If the InfluxDB token is missing.
        ConnectionError: If the connection cannot be established.
    """

    if not INFLUXDB_TOKEN:
        raise ValueError(
            "Missing InfluxDB token. Set the INFLUXDB_TOKEN environment variable."
        )

    try:
        client = InfluxDBClient3(
            host=INFLUXDB_HOST,
            token=INFLUXDB_TOKEN,
            database=INFLUXDB_DATABASE
        )

        # Verify that the connection works.
        client.query("SELECT 1")

        return client

    except Exception as error:
        raise ConnectionError(
            f"Could not connect to InfluxDB: {error}"
        ) from error

# --------------------------------------------------
# Latest Sensor Reading
# --------------------------------------------------

def get_latest_reading() -> dict[str, Any] | None:
    """
    Get the most recent sensor reading from InfluxDB.

    Returns:
        dict: Latest sensor reading containing timestamp,
              CO2, temperature, and humidity.
        None: If no sensor readings are available.
    """

    client = get_influxdb_client()

    try:
        # Escape quotation marks in the measurement identifier.
        measurement = INFLUXDB_MEASUREMENT.replace('"', '""')

        query = f"""
            SELECT time, {CO2_FIELD}, {TEMPERATURE_FIELD}, {HUMIDITY_FIELD}
            FROM "{measurement}"
            ORDER BY time DESC
            LIMIT 1
        """

        # Execute the query and convert the result to a DataFrame.
        result = client.query(query)
        df = result.to_pandas()

        # Check whether the database returned any readings.
        if df.empty:
            return None
        # Validate the readings before returning them.
        validated = validate_readings(df)

        if validated.empty:
            return None
        # Return the newest valid reading.
        return validated.iloc[-1].to_dict()

    finally:
        client.close()

# --------------------------------------------------
# Historical Sensor Readings
# --------------------------------------------------

def get_historical_readings(
    minutes: int = 30
) -> pd.DataFrame:
    """
    Get the sensor readings from a configurable time window.

    Args:
        minutes: Number of minutes of historical data to retrieve.

    Returns:
        pd.DataFrame: Sensor readings ordered chronologically.
    """

    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0:
        raise ValueError("minutes must be a positive integer.")

    client = get_influxdb_client()

    try:
        measurement = INFLUXDB_MEASUREMENT.replace('"', '""')

        query = f"""
            SELECT time, {CO2_FIELD}, {TEMPERATURE_FIELD}, {HUMIDITY_FIELD}
            FROM "{measurement}"
            WHERE time >= now() - INTERVAL '{minutes}' MINUTE
            ORDER BY time ASC
        """

        # Execute the query and convert the result to a DataFrame.
        result = client.query(query)
        df = result.to_pandas()

        if df.empty:
            return pd.DataFrame(
                columns=["time", "co2", "temp_c", "rh", "is_stale"]
            )

        # Validate and clean the historical readings.
        return validate_readings(df)

    finally:
        client.close()

# --------------------------------------------------
# Data Validation
# --------------------------------------------------

def validate_readings(
    df: pd.DataFrame,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS
) -> pd.DataFrame:
    """
    Check and clean sensor readings.

    Checks:
        - Required columns are present.
        - Timestamps are valid.
        - Sensor values are numeric and within the expected ranges.
        - Duplicate timestamps are removed.
        - Stale readings are identified.

    Returns:
        pd.DataFrame: Validated sensor readings.
    """

    if not isinstance(df, pd.DataFrame):
        raise TypeError("Input must be a Pandas DataFrame.")

    if not isinstance(max_age_seconds, int) or isinstance(max_age_seconds, bool) or max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be a positive integer.")

    required_columns = ["time", "co2", "temp_c", "rh"]

    # Check for missing columns.
    missing_columns = [
        column for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {missing_columns}"
        )

    # Work with a copy so the original DataFrame is unchanged.
    cleaned = df[required_columns].copy()

    # Convert timestamps to UTC.
    cleaned["time"] = pd.to_datetime(
        cleaned["time"],
        errors="coerce",
        utc=True
    )

    # Convert sensor values to numeric types.
    for column in ["co2", "temp_c", "rh"]:
        cleaned[column] = pd.to_numeric(
            cleaned[column],
            errors="coerce"
        )

    # Remove rows with missing or invalid values.
    cleaned = cleaned.dropna(subset=required_columns)

    # Check expected sensor measurement ranges.
    valid_rows = (
        cleaned["co2"].between(0, 40000)
        & cleaned["temp_c"].between(-40, 85)
        & cleaned["rh"].between(0, 100)
    )

    cleaned = cleaned.loc[valid_rows].copy()

    # Remove duplicate timestamps, keeping the last record.
    cleaned = cleaned.drop_duplicates(
        subset=["time"],
        keep="last"
    )

    # Sort readings from oldest to newest.
    cleaned = cleaned.sort_values("time").reset_index(drop=True)

    # Identify readings older than the allowed age.
    current_time = pd.Timestamp.now(tz="UTC")

    cleaned["is_stale"] = (
        (current_time - cleaned["time"]).dt.total_seconds()
        > max_age_seconds
    )

    return cleaned

# --------------------------------------------------
# Usage Example
# --------------------------------------------------

if __name__ == "__main__":
    try:
        # Retrieve the latest sensor reading.
        latest = get_latest_reading()

        if latest is not None:
            print("Latest Sensor Reading:")
            print(latest)
        else:
            print("No valid sensor readings available.")

        # Retrieve the last 30 minutes of readings.
        history = get_historical_readings(minutes=30)

        print("\nHistorical Sensor Readings:")
        print(history.tail())

    except (ValueError, ConnectionError) as error:
        print(f"InfluxDB reader error: {error}")