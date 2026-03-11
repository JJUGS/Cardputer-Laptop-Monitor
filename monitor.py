import time
import requests
import serial
import psutil
from serial.tools import list_ports

BAUD = 115200
URL = "http://localhost:8085/data.json"

REFRESH_SEC = 0.35
REQUEST_TIMEOUT = 1.5


def auto_detect_port():
    """
    Try to find the Cardputer automatically.
    Prefers common ESP32 / USB-serial adapters like CP210x and CH340.
    """
    keywords = [
        "cp210",
        "ch340",
        "usb serial",
        "esp32",
        "m5",
        "cardputer",
        "jtag",
        "silicon labs",
        "wch",
    ]

    ports = list(list_ports.comports())

    if not ports:
        raise RuntimeError("No serial ports found. Plug in the Cardputer and try again.")

    # First pass: look for likely ESP32 / M5 related ports
    matches = []
    for port in ports:
        desc = f"{port.device} {port.description} {port.hwid}".lower()
        if any(keyword in desc for keyword in keywords):
            matches.append(port.device)

    if len(matches) == 1:
        return matches[0]

    if len(matches) > 1:
        print("Multiple likely serial devices found:")
        for i, device in enumerate(matches, 1):
            print(f"  {i}. {device}")

        print(f"Using first likely match: {matches[0]}")
        return matches[0]

    # Fallback: use the first available port
    print("No obvious Cardputer port found. Falling back to first available serial port.")
    for i, port in enumerate(ports, 1):
        print(f"  {i}. {port.device} - {port.description}")

    return ports[0].device


def open_serial():
    port = auto_detect_port()
    print(f"Opening serial connection on {port} at {BAUD} baud...")
    ser = serial.Serial(port, BAUD, timeout=1)
    time.sleep(1.0)
    print("Serial connected.")
    return ser


def walk(node, path, out):
    """Collect (full_path, value) pairs from LibreHardwareMonitor JSON."""
    if isinstance(node, dict):
        text = node.get("Text")
        value = node.get("Value")

        new_path = path
        if isinstance(text, str) and text.strip():
            new_path = path + [text.strip()]

        if value is not None and text is not None:
            out.append((" / ".join(new_path), str(value)))

        for v in node.values():
            if isinstance(v, (dict, list)):
                walk(v, new_path, out)

    elif isinstance(node, list):
        for item in node:
            walk(item, path, out)


def pick(out, must_contain, value_hint=None):
    """
    Return first sensor value whose path contains all strings in must_contain.
    Optionally require value_hint to be present in value text.
    """
    required = [s.lower() for s in must_contain]

    for path, value in out:
        path_l = path.lower()
        if all(s in path_l for s in required):
            if value_hint is None or value_hint in value:
                return value
    return "NA"


def parse_float_loose(val):
    """Extract first numeric value from strings like '661.7 MHz' or '57.6 °C'."""
    if not isinstance(val, str):
        return None

    buf = []
    seen_digit = False
    seen_dot = False
    seen_minus = False

    for ch in val.strip():
        if ch.isdigit():
            buf.append(ch)
            seen_digit = True
        elif ch == "." and not seen_dot:
            buf.append(ch)
            seen_dot = True
        elif ch == "-" and not seen_digit and not seen_minus:
            buf.append(ch)
            seen_minus = True
        elif seen_digit:
            break

    try:
        s = "".join(buf)
        if s in ("", "-", ".", "-."):
            return None
        return float(s)
    except Exception:
        return None


def bytes_to_gb_string(num_bytes):
    gb = num_bytes / (1024 ** 3)
    return f"{gb:.1f}GB"


def safe_percent_string(value):
    if value is None:
        return "NA"
    return f"{round(value):.0f}%"


def normalize_speed_string(value):
    """
    Convert LibreHardwareMonitor throughput strings into clean B/s, KB/s, MB/s, or GB/s.
    """
    if value == "NA":
        return "NA"

    n = parse_float_loose(value)
    if n is None:
        return "NA"

    v = value.upper()

    if "GB/S" in v:
        return f"{n:.2f}GB/s"
    if "MB/S" in v:
        return f"{n:.2f}MB/s"
    if "KB/S" in v:
        return f"{n:.2f}KB/s"
    if "B/S" in v:
        return f"{n:.0f}B/s"

    if n >= 1024 ** 3:
        return f"{n / (1024 ** 3):.2f}GB/s"
    if n >= 1024 ** 2:
        return f"{n / (1024 ** 2):.2f}MB/s"
    if n >= 1024:
        return f"{n / 1024:.2f}KB/s"
    return f"{n:.0f}B/s"


def fetch_lhm_json():
    r = requests.get(URL, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def send_line(ser, line):
    ser.write((line + "\n").encode("utf-8"))


def send_na_block(ser):
    send_line(ser, "CPU|util=NA|clock=NA|temp=NA")
    send_line(ser, "RAM|util=NA|used=NA|total=NA|speed=NA")
    send_line(ser, "IGPU|util=NA|temp=NA|clock=NA")
    send_line(ser, "WIFI|up=NA|down=NA")


def main():
    ser = open_serial()

    prev_net = psutil.net_io_counters()
    prev_net_time = time.time()

    while True:
        try:
            data = fetch_lhm_json()
            sensors = []
            walk(data, [], sensors)

            # ---------------- CPU ----------------
            cpu_temp = pick(sensors, ["temperatures", "core (tctl/tdie)"], "°C")
            if cpu_temp == "NA":
                cpu_temp = pick(sensors, ["temperatures", "package"], "°C")
            if cpu_temp == "NA":
                cpu_temp = pick(sensors, ["temperatures", "cpu"], "°C")

            cpu_util = pick(sensors, ["load", "cpu total"], "%")
            if cpu_util == "NA":
                cpu_util = safe_percent_string(psutil.cpu_percent(interval=None))

            cpu_clock = pick(sensors, ["clocks", "cores (average)"], "MHz")
            if cpu_clock == "NA":
                cpu_clock = pick(sensors, ["clocks", "cpu core #1"], "MHz")

            # ---------------- RAM ----------------
            vm = psutil.virtual_memory()
            ram_util = safe_percent_string(vm.percent)
            ram_used = bytes_to_gb_string(vm.used)
            ram_total = bytes_to_gb_string(vm.total)

            mem_clk = pick(sensors, ["clocks", "memory"], "MHz")
            ram_speed = "NA"
            mhz = parse_float_loose(mem_clk)
            if mhz is not None:
                ram_speed = f"{mhz * 2:.0f} MT/s"

            # ---------------- iGPU ----------------
            igpu_util = pick(sensors, ["amd radeon", "load", "gpu core"], "%")
            if igpu_util == "NA":
                igpu_util = pick(sensors, ["gpu", "load", "core"], "%")

            igpu_clk = pick(sensors, ["amd radeon", "clocks", "gpu core"], "MHz")
            if igpu_clk == "NA":
                igpu_clk = pick(sensors, ["gpu", "clocks", "gpu core"], "MHz")

            igpu_temp = pick(sensors, ["amd ryzen", "temperatures", "gfx"], "°C")
            if igpu_temp == "NA":
                igpu_temp = pick(sensors, ["temperatures", "gfx"], "°C")
            if igpu_temp == "NA":
                igpu_temp = pick(sensors, ["amd radeon", "temperatures"], "°C")

            # ---------------- Wi-Fi / Network ----------------
            now = time.time()
            net = psutil.net_io_counters()
            dt = max(now - prev_net_time, 0.001)

            up_bps = (net.bytes_sent - prev_net.bytes_sent) / dt
            down_bps = (net.bytes_recv - prev_net.bytes_recv) / dt

            prev_net = net
            prev_net_time = now

            wifi_up = normalize_speed_string(f"{up_bps} B/s")
            wifi_down = normalize_speed_string(f"{down_bps} B/s")

            lhm_wifi_up = pick(sensors, ["wi-fi", "throughput", "upload speed"])
            lhm_wifi_down = pick(sensors, ["wi-fi", "throughput", "download speed"])

            if lhm_wifi_up != "NA":
                wifi_up = normalize_speed_string(lhm_wifi_up)
            if lhm_wifi_down != "NA":
                wifi_down = normalize_speed_string(lhm_wifi_down)

            # ---------------- Send to Cardputer ----------------
            cpu_line = f"CPU|util={cpu_util}|clock={cpu_clock}|temp={cpu_temp}"
            ram_line = f"RAM|util={ram_util}|used={ram_used}|total={ram_total}|speed={ram_speed}"
            igpu_line = f"IGPU|util={igpu_util}|temp={igpu_temp}|clock={igpu_clk}"
            wifi_line = f"WIFI|up={wifi_up}|down={wifi_down}"

            send_line(ser, cpu_line)
            send_line(ser, ram_line)
            send_line(ser, igpu_line)
            send_line(ser, wifi_line)

        except KeyboardInterrupt:
            print("\nStopping monitor.py...")
            break

        except serial.SerialException as e:
            print(f"Serial error: {e}")
            print("Trying to reconnect in 2 seconds...")
            time.sleep(2)

            try:
                ser.close()
            except Exception:
                pass

            ser = open_serial()
            send_na_block(ser)

        except Exception as e:
            send_na_block(ser)
            print("monitor.py error:", e)

        time.sleep(REFRESH_SEC)

    try:
        ser.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()