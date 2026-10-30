"""Download all CSV sessions from ESP32 Offline Logger. Requires: pip install pyserial"""
import argparse
import csv
import io
import re
import time
from pathlib import Path
import serial
from serial.tools import list_ports

NAME = re.compile(r"^session_\d{6}\.csv$")


def read_until(ser, marker, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == marker:
            return
        if line.startswith("ERROR"):
            raise RuntimeError(line)
    raise TimeoutError(f"Timed out waiting for {marker}")


def get_files(ser):
    ser.write(b"LIST\n")
    read_until(ser, "LIST_BEGIN")
    files = []
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == "LIST_END":
            return files
        if line.startswith("FILE:"):
            name = line[5:].split(":", 1)[0]
            if NAME.fullmatch(name):
                files.append(name)
    raise TimeoutError("File listing did not finish")


def get_csv(ser, name):
    ser.write(f"DOWNLOAD {name}\n".encode())
    read_until(ser, f"CSV_BEGIN:{name}")
    lines = []
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line == f"CSV_END:{name}":
            if not lines or lines[0] != "elapsed_seconds,co2_ppm,temp_c,humidity_pct":
                raise ValueError(f"Invalid CSV header in {name}")
            reader = csv.reader(io.StringIO("\n".join(lines)))
            if any(len(row) != 4 for row in reader):
                raise ValueError(f"Invalid CSV rows in {name}")
            return "\n".join(lines) + "\n"
        if line.startswith("ERROR"):
            raise RuntimeError(line)
        if line:
            lines.append(line)
    raise TimeoutError(f"Download timed out: {name}")


def main():
    parser = argparse.ArgumentParser(description="Download offline CO2 recording sessions")
    parser.add_argument("--port", help="USB serial port, e.g. COM5")
    parser.add_argument("--out", default="co2_sessions", help="Output folder")
    args = parser.parse_args()
    if not args.port:
        ports = list(list_ports.comports())
        if not ports:
            parser.error("No serial ports found. Connect ESP32 and try --port COM5")
        print("Available ports:")
        for port in ports:
            print(f"  {port.device}: {port.description}")
        if len(ports) != 1:
            parser.error("Specify a port using --port COM5")
        args.port = ports[0].device

    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    with serial.Serial(args.port, 115200, timeout=1, write_timeout=5) as ser:
        # Opening a serial port can reset some ESP32 boards and start a new session.
        time.sleep(3)
        ser.reset_input_buffer()
        ser.write(b"STOP\n")
        time.sleep(0.5)
        ser.reset_input_buffer()
        files = get_files(ser)
        print(f"Found {len(files)} session(s).")
        for name in files:
            target = output / name
            if target.exists():
                print(f"Skipping existing file: {target}")
                continue
            content = get_csv(ser, name)
            part = output / (name + ".part")
            part.write_text(content, encoding="utf-8", newline="")
            part.replace(target)
            print(f"Saved {target}")
    print("Done. Recordings remain on the ESP32; none were deleted.")


if __name__ == "__main__":
    main()
