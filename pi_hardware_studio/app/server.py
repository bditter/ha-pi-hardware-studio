#!/usr/bin/env python3
"""Pi Hardware Studio HTTP service."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


APP_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = APP_ROOT / "static"
DATA_ROOT = Path("/data")
MOUNT_ROOT = Path("/run/pi-hardware-studio")
FAN_HWMON_ROOT = Path("/sys/devices/platform/cooling_fan/hwmon")
SETTINGS_FILE = DATA_ROOT / "settings.json"
MAX_BODY_BYTES = 256 * 1024
MANAGED_BEGIN = "# BEGIN PI HARDWARE STUDIO"
MANAGED_END = "# END PI HARDWARE STUDIO"
BACKUP_STAMP_PATTERN = r"\d{8}T\d{12}Z"
PARTITIONS = (
    "vda1",
    "sda1",
    "sdb1",
    "mmcblk0p1",
    "mmcblk0p2",
    "mmcblk1p1",
    "nvme0n1p1",
    "xvda8",
)


class AppError(Exception):
    """An error safe to show in the UI."""


@dataclass
class MountedBoot:
    device: Path
    mountpoint: Path
    config_path: Path
    cmdline_path: Path | None = None

    @property
    def kernel_cmdline_path(self) -> Path:
        return self.cmdline_path or self.config_path.parent / "cmdline.txt"


class BootManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mounted: list[MountedBoot] = []

    @property
    def targets(self) -> list[MountedBoot]:
        with self._lock:
            return list(self._mounted)

    @property
    def primary(self) -> MountedBoot:
        with self._lock:
            if not self._mounted:
                raise AppError("Mount the boot partition first.")
            return self._mounted[0]

    def scan_and_mount(self) -> list[MountedBoot]:
        with self._lock:
            if self._mounted:
                return list(self._mounted)

            MOUNT_ROOT.mkdir(parents=True, exist_ok=True)
            failures: list[str] = []
            for name in PARTITIONS:
                device = Path("/dev") / name
                if not device.exists():
                    continue

                mountpoint = MOUNT_ROOT / name
                mountpoint.mkdir(parents=True, exist_ok=True)
                result = subprocess.run(
                    ["mount", "-o", "rw", str(device), str(mountpoint)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0:
                    failures.append(f"{device}: {result.stderr.strip()}")
                    continue

                boot_files = self._find_boot_files(mountpoint)
                if boot_files:
                    config_path, cmdline_path = boot_files
                    self._mounted.append(
                        MountedBoot(device, mountpoint, config_path, cmdline_path)
                    )
                else:
                    subprocess.run(["umount", str(mountpoint)], check=False)

            if not self._mounted:
                detail = "; ".join(failures) if failures else "No candidate block devices found."
                raise AppError(
                    "No Raspberry Pi boot partition could be mounted. "
                    "Disable protection mode and try again. " + detail
                )
            return list(self._mounted)

    def unmount_all(self) -> None:
        with self._lock:
            for target in reversed(self._mounted):
                subprocess.run(["umount", str(target.mountpoint)], check=False)
            self._mounted.clear()

    @staticmethod
    def _find_boot_files(mountpoint: Path) -> tuple[Path, Path] | None:
        for relative in ("config.txt", "boot/config.txt", "boot/firmware/config.txt"):
            candidate = mountpoint / relative
            cmdline = candidate.parent / "cmdline.txt"
            if candidate.is_file() and cmdline.is_file():
                return candidate, cmdline
        return None

    def read_config(self) -> str:
        return self.primary.config_path.read_text(encoding="utf-8", errors="replace")

    def read_cmdline(self) -> str:
        return self.primary.kernel_cmdline_path.read_text(
            encoding="utf-8", errors="replace"
        ).strip()

    def write_config(self, content: str) -> str | None:
        if "\x00" in content:
            raise AppError("The configuration contains an invalid NUL character.")
        if len(content.encode("utf-8")) > MAX_BODY_BYTES:
            raise AppError("The configuration is too large.")

        target = self.primary.config_path
        if content == target.read_text(encoding="utf-8", errors="replace"):
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = target.with_name(f"{target.name}.pi-hardware-studio-{stamp}.bak")
        shutil.copy2(target, backup)

        temporary = target.with_name(f".{target.name}.pi-hardware-studio.tmp")
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, target)
        return backup.name

    def write_cmdline(self, content: str) -> str | None:
        if "\x00" in content:
            raise AppError("The kernel command line contains an invalid NUL character.")
        if "\n" in content or "\r" in content:
            raise AppError("cmdline.txt must contain exactly one line.")

        normalized = content.strip()
        if not normalized:
            raise AppError("cmdline.txt cannot be empty.")
        if len(normalized.encode("utf-8")) > MAX_BODY_BYTES:
            raise AppError("The kernel command line is too large.")

        target = self.primary.kernel_cmdline_path
        if normalized == target.read_text(encoding="utf-8", errors="replace").strip():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = target.with_name(f"{target.name}.pi-hardware-studio-{stamp}.bak")
        shutil.copy2(target, backup)

        temporary = target.with_name(f".{target.name}.pi-hardware-studio.tmp")
        temporary.write_text(normalized + "\n", encoding="utf-8", newline="\n")
        os.replace(temporary, target)
        return backup.name

    def apply_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        curve = validate_curve(payload.get("fan_curve", []))
        lines = [
            MANAGED_BEGIN,
            "# Generated by Pi Hardware Studio. Use the Web UI to change this block.",
            f"dtparam=i2c_arm={'on' if payload.get('i2c') else 'off'}",
            f"dtparam=spi={'on' if payload.get('spi') else 'off'}",
            f"enable_uart={1 if payload.get('serial') else 0}",
        ]
        if payload.get("fan_enabled"):
            for index, point in enumerate(curve):
                pwm = round(point["speed_pct"] * 255 / 100)
                lines.extend(
                    (
                        f"dtparam=fan_temp{index}={round(point['temp_c'] * 1000)}",
                        f"dtparam=fan_temp{index}_speed={pwm}",
                    )
                )
        lines.append(MANAGED_END)

        current = self.read_config()
        block = "\n".join(lines)
        pattern = re.compile(
            rf"(?ms)^{re.escape(MANAGED_BEGIN)}$.*?^{re.escape(MANAGED_END)}$\n?"
        )
        unmanaged = pattern.sub("", current, count=1)
        unmanaged = remove_active_fan_parameters(unmanaged)
        updated = unmanaged.rstrip() + "\n\n" + block + "\n"

        backup = self.write_config(updated)
        cmdline_backup = None
        if "psi" in payload:
            current_cmdline = self.read_cmdline()
            updated_cmdline = update_cmdline_parameter(
                current_cmdline, "psi", "1" if payload.get("psi") else None
            )
            if updated_cmdline != current_cmdline:
                cmdline_backup = self.write_cmdline(updated_cmdline)
        save_preferences(payload.get("temperature_unit", "C"))
        return {"backup": backup, "cmdline_backup": cmdline_backup}

    def list_backups(self) -> list[dict[str, Any]]:
        target = self.primary
        backups: list[dict[str, Any]] = []
        for source, path in (
            ("config.txt", target.config_path),
            ("cmdline.txt", target.kernel_cmdline_path),
        ):
            pattern = f"{path.name}.pi-hardware-studio-*.bak"
            for backup in path.parent.glob(pattern):
                if not backup.is_file() or not self._is_backup_name(backup.name, path.name):
                    continue
                stat = backup.stat()
                backups.append(
                    {
                        "name": backup.name,
                        "source": source,
                        "size": stat.st_size,
                        "modified": datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat(),
                    }
                )
        return sorted(backups, key=lambda item: item["modified"], reverse=True)

    def delete_backups(self, names: Any) -> list[str]:
        if not isinstance(names, list) or not names:
            raise AppError("Select at least one backup to delete.")
        if not all(isinstance(name, str) for name in names):
            raise AppError("Invalid backup selection.")

        target = self.primary
        allowed_parents = {
            target.config_path.parent.resolve(),
            target.kernel_cmdline_path.parent.resolve(),
        }
        allowed_sources = {
            target.config_path.name,
            target.kernel_cmdline_path.name,
        }
        deleted: list[str] = []
        for name in dict.fromkeys(names):
            if Path(name).name != name or not any(
                self._is_backup_name(name, source) for source in allowed_sources
            ):
                raise AppError(f"Invalid backup name: {name}")
            candidates = [
                parent / name for parent in allowed_parents if (parent / name).is_file()
            ]
            if len(candidates) != 1:
                raise AppError(f"Backup not found: {name}")
            candidates[0].unlink()
            deleted.append(name)
        return deleted

    @staticmethod
    def _is_backup_name(name: str, source: str) -> bool:
        return bool(
            re.fullmatch(
                rf"{re.escape(source)}\.pi-hardware-studio-{BACKUP_STAMP_PATTERN}\.bak",
                name,
            )
        )

    def provision_ssh_key(self, public_key: str) -> dict[str, Any]:
        key = public_key.strip()
        if "\n" in key or "\r" in key:
            raise AppError("Enter exactly one public key line.")
        if "PRIVATE KEY" in key or not re.match(
            r"^(ssh-(rsa|ed25519)|ecdsa-sha2-nistp\d+|sk-ssh-|sk-ecdsa-)\S*\s+\S+",
            key,
        ):
            raise AppError("This does not look like a supported SSH public key.")

        added_to: list[str] = []
        for target in self.targets:
            config_dir = target.mountpoint / "CONFIG"
            config_dir.mkdir(parents=True, exist_ok=True)
            auth_file = config_dir / "authorized_keys"
            existing = auth_file.read_text(encoding="utf-8", errors="replace") if auth_file.exists() else ""
            if key not in {line.strip() for line in existing.splitlines()}:
                with auth_file.open("a", encoding="utf-8", newline="\n") as handle:
                    if existing and not existing.endswith("\n"):
                        handle.write("\n")
                    handle.write(key + "\n")
                added_to.append(target.device.name)
        return {"added_to": added_to, "already_present": not added_to}


def validate_curve(value: Any) -> list[dict[str, float]]:
    if not isinstance(value, list) or len(value) != 4:
        raise AppError("The fan curve must contain exactly four points.")

    result: list[dict[str, float]] = []
    previous_temp = -1.0
    previous_speed = -1.0
    for point in value:
        try:
            temp = float(point["temp_c"])
            speed = float(point["speed_pct"])
        except (KeyError, TypeError, ValueError):
            raise AppError("Every fan point needs numeric temperature and speed values.") from None
        if not 20 <= temp <= 100:
            raise AppError("Fan temperatures must be between 20 C and 100 C.")
        if not 0 <= speed <= 100:
            raise AppError("Fan speeds must be between 0% and 100%.")
        if temp <= previous_temp:
            raise AppError("Fan temperatures must increase from one point to the next.")
        if speed < previous_speed:
            raise AppError("Fan speeds cannot decrease as temperature rises.")
        result.append({"temp_c": round(temp, 3), "speed_pct": round(speed, 2)})
        previous_temp, previous_speed = temp, speed
    return result


def load_preferences() -> dict[str, str]:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return {"temperature_unit": "F" if data.get("temperature_unit") == "F" else "C"}


def save_preferences(unit: str) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(
        json.dumps({"temperature_unit": "F" if unit == "F" else "C"}, indent=2) + "\n",
        encoding="utf-8",
    )


def parse_managed_settings(content: str) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "i2c": False,
        "spi": False,
        "serial": False,
        "fan_enabled": False,
        "fan_curve": [
            {"temp_c": 35, "speed_pct": 30},
            {"temp_c": 50, "speed_pct": 50},
            {"temp_c": 60, "speed_pct": 70},
            {"temp_c": 65, "speed_pct": 100},
        ],
    }
    parameters = parse_active_parameters(content)

    def last_parameter(names: tuple[str, ...]) -> bool | None:
        values = [value for key, value in parameters if key in names]
        if not values:
            return None
        return values[-1] in ("on", "1")

    i2c_state = last_parameter(("i2c", "i2c_arm", "i2c_vc"))
    spi_state = last_parameter(("spi",))
    uart_state = last_parameter(("enable_uart",))
    defaults["i2c"] = bool(i2c_state)
    defaults["spi"] = bool(spi_state)
    defaults["serial"] = bool(uart_state)

    parameter_map = {key: value for key, value in parameters}
    curve: list[dict[str, float]] = []
    for index in range(4):
        temp = parameter_map.get(f"fan_temp{index}")
        speed = parameter_map.get(f"fan_temp{index}_speed")
        if temp and speed:
            try:
                temp_value = int(temp)
                speed_value = int(speed)
            except ValueError:
                curve = []
                break
            curve.append(
                {
                    "temp_c": temp_value / 1000,
                    "speed_pct": round(speed_value * 100 / 255, 1),
                }
            )
    if len(curve) == 4:
        defaults["fan_enabled"] = True
        defaults["fan_curve"] = curve
    return defaults


def parse_active_parameters(content: str) -> list[tuple[str, str]]:
    """Return active config assignments in file order."""
    result: list[tuple[str, str]] = []
    for raw_line in content.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parameters = line[8:] if line.lower().startswith("dtparam=") else line
        for assignment in parameters.split(","):
            if "=" not in assignment:
                continue
            key, value = (part.strip().lower() for part in assignment.split("=", 1))
            result.append((key, value))
    return result


def remove_active_fan_parameters(content: str) -> str:
    """Remove active fan directives before Pi Hardware Studio takes ownership."""
    pattern = re.compile(
        r"^\s*dtparam\s*=\s*fan_temp[0-3](?:_hyst|_speed)?\s*=.*(?:\r?\n|$)",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    return pattern.sub("", content)


def parse_cmdline_parameter(content: str, name: str) -> str | None:
    prefix = f"{name}="
    values = [token[len(prefix):] for token in content.split() if token.startswith(prefix)]
    return values[-1] if values else None


def update_cmdline_parameter(
    content: str, name: str, value: str | None
) -> str:
    prefix = f"{name}="
    tokens = [token for token in content.split() if not token.startswith(prefix)]
    if value is not None:
        tokens.append(f"{name}={value}")
    return " ".join(tokens)


def detect_runtime_interfaces() -> dict[str, bool]:
    """Detect interfaces that are active in the running kernel."""
    return {
        "i2c": any(Path("/dev").glob("i2c-*")),
        "spi": any(Path("/dev").glob("spidev*")),
        "serial": Path("/dev/serial0").exists(),
    }


def resolve_interface_status(
    content: str,
    mounted: bool,
    runtime_interfaces: dict[str, bool] | None = None,
) -> tuple[dict[str, Any], dict[str, bool]]:
    """Keep editable boot settings separate from running-kernel observations."""
    settings = parse_managed_settings(content if mounted else "")
    runtime = runtime_interfaces if mounted and runtime_interfaces is not None else {
        "i2c": False,
        "spi": False,
        "serial": False,
    }
    return settings, runtime


def read_fan_telemetry(root: Path | None = None) -> dict[str, Any]:
    root = root or FAN_HWMON_ROOT
    for hwmon in root.glob("hwmon*"):
        rpm_file = hwmon / "fan1_input"
        pwm_file = hwmon / "pwm1"
        if rpm_file.exists():
            try:
                rpm = int(rpm_file.read_text().strip())
                pwm = int(pwm_file.read_text().strip()) if pwm_file.exists() else None
                return {
                    "detected": True,
                    "rpm": rpm,
                    "speed_pct": round(pwm * 100 / 255) if pwm is not None else None,
                    "rpm_path": str(rpm_file),
                    "pwm_path": str(pwm_file) if pwm_file.exists() else None,
                    "sensor_yaml": generate_fan_sensor_yaml(
                        str(rpm_file),
                        str(pwm_file),
                    )
                    if pwm_file.exists()
                    else None,
                }
            except (OSError, ValueError):
                break
    return {
        "detected": False,
        "rpm": None,
        "speed_pct": None,
        "rpm_path": None,
        "pwm_path": None,
        "sensor_yaml": None,
    }


def generate_fan_sensor_yaml(rpm_path: str, pwm_path: str) -> str:
    """Generate sensors that survive Linux hwmon directory renumbering."""
    rpm_glob = re.sub(r"(?<=[/\\])hwmon\d+(?=[/\\])", "hwmon*", rpm_path)
    pwm_glob = re.sub(r"(?<=[/\\])hwmon\d+(?=[/\\])", "hwmon*", pwm_path)
    return f"""command_line:
  - sensor:
      name: "Pi 5 Fan Speed (RPM)"
      icon: "mdi:fan"
      unique_id: "pi5fan_rpm"
      command: 'cat {rpm_glob} 2>/dev/null | head -n 1'
      unit_of_measurement: "RPM"
      scan_interval: 15
      value_template: "{{{{ value | int }}}}"
      state_class: "measurement"
  - sensor:
      name: "Pi 5 Fan Speed (%)"
      icon: "mdi:fan"
      unique_id: "pi5fan_percentage"
      command: 'cat {pwm_glob} 2>/dev/null | head -n 1'
      unit_of_measurement: "%"
      scan_interval: 15
      value_template: "{{{{ ((value | int) / 255 * 100) | round(0, 'common') }}}}"
      state_class: "measurement"
"""


def request_host_reboot() -> None:
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise AppError("The Supervisor token is unavailable.")
    request = urllib.request.Request(
        "http://supervisor/host/reboot",
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        data=b"{}",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status >= 300:
                raise AppError(f"Supervisor rejected the reboot request ({response.status}).")
    except urllib.error.URLError as error:
        raise AppError(f"Could not request a host reboot: {error.reason}") from error


BOOT = BootManager()


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "PiHardwareStudio/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path.endswith("/api/status"):
            self._status()
        elif path.endswith("/api/config"):
            self._config()
        elif path.endswith("/api/cmdline"):
            self._cmdline()
        elif path.endswith("/api/backups"):
            self._backups()
        else:
            self._static(path)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path.endswith("/api/mount"):
                targets = BOOT.scan_and_mount()
                self._json(
                    {
                        "ok": True,
                        "targets": [
                            {"device": str(item.device), "config": str(item.config_path)}
                            for item in targets
                        ],
                    }
                )
            elif path.endswith("/api/reboot"):
                request_host_reboot()
                self._json({"ok": True})
            else:
                self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
        except AppError as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def do_PUT(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path.endswith("/api/settings"):
                result = BOOT.apply_settings(payload)
            elif path.endswith("/api/config"):
                content = payload.get("content")
                if not isinstance(content, str):
                    raise AppError("Missing configuration content.")
                result = {"backup": BOOT.write_config(content)}
            elif path.endswith("/api/cmdline"):
                content = payload.get("content")
                if not isinstance(content, str):
                    raise AppError("Missing kernel command line content.")
                result = {"backup": BOOT.write_cmdline(content)}
            elif path.endswith("/api/ssh"):
                result = BOOT.provision_ssh_key(str(payload.get("public_key", "")))
            else:
                self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
                return
            self._json({"ok": True, **result})
        except AppError as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        try:
            if not path.endswith("/api/backups"):
                self._json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
                return
            payload = self._read_json()
            deleted = BOOT.delete_backups(payload.get("names"))
            self._json({"ok": True, "deleted": deleted})
        except AppError as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, message: str, *args: Any) -> None:
        print(f"{self.client_address[0]} - {message % args}", flush=True)

    def _status(self) -> None:
        mounted = bool(BOOT.targets)
        content = BOOT.read_config() if mounted else ""
        runtime_interfaces = detect_runtime_interfaces() if mounted else None
        settings, runtime_interfaces = resolve_interface_status(
            content,
            mounted,
            runtime_interfaces,
        )
        settings.update(load_preferences())
        settings["psi"] = (
            parse_cmdline_parameter(BOOT.read_cmdline(), "psi") == "1"
            if mounted
            else False
        )
        self._json(
            {
                "mounted": mounted,
                "target": str(BOOT.primary.config_path) if mounted else None,
                "cmdline_target": (
                    str(BOOT.primary.kernel_cmdline_path) if mounted else None
                ),
                "settings": settings,
                "runtime_interfaces": runtime_interfaces,
                "fan": read_fan_telemetry(),
            }
        )

    def _config(self) -> None:
        try:
            self._json({"content": BOOT.read_config()})
        except AppError as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _cmdline(self) -> None:
        try:
            self._json({"content": BOOT.read_cmdline()})
        except AppError as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _backups(self) -> None:
        try:
            self._json({"backups": BOOT.list_backups()})
        except AppError as error:
            self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise AppError("Invalid request size.") from None
        if length <= 0 or length > MAX_BODY_BYTES:
            raise AppError("Invalid request size.")
        try:
            value = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AppError("Invalid JSON request.") from None
        if not isinstance(value, dict):
            raise AppError("The request body must be an object.")
        return value

    def _json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path: str) -> None:
        relative = path.rsplit("/", 1)[-1] if "." in path.rsplit("/", 1)[-1] else "index.html"
        if relative not in {"index.html", "app.js", "styles.css"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        target = STATIC_ROOT / relative
        body = target.read_bytes()
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }[target.suffix]
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8099), RequestHandler)

    def stop(_signum: int, _frame: Any) -> None:
        BOOT.unmount_all()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("Pi Hardware Studio listening on port 8099", flush=True)
    try:
        server.serve_forever()
    finally:
        BOOT.unmount_all()
        server.server_close()


if __name__ == "__main__":
    main()
