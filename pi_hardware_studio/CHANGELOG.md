# Changelog

## 1.0.5

- Add a backup manager for reviewing and deleting selected Studio backups.
- Restrict deletion to timestamped backups created by Pi Hardware Studio.
- Avoid creating backups when a save does not change `config.txt` or `cmdline.txt`.
- Complete a behavior audit against Pi5FanEnabler while retaining the working fan configuration and stable sensor paths.

## 1.0.4

- Generate fan sensor commands with a stable `hwmon*` path.
- Prevent fan sensors from becoming unavailable when Linux renumbers `hwmonN` after a reboot.

## 1.0.3

- Stop writing explicit fan hysteresis values when they are not configured in the UI.
- Continue removing legacy and previously generated `fan_temp*_hyst` directives when applying a fan curve.

## 1.0.2

- Add a structured Pressure Stall Information toggle that manages `psi=1`.
- Add a guarded raw `cmdline.txt` editor.
- Create timestamped `cmdline.txt` backups before changes.
- Preserve unrelated kernel command-line arguments and enforce the required single-line format.

## 1.0.1

- Generate copy-ready Home Assistant `command_line` fan sensor YAML.
- Insert the detected RPM and PWM sysfs paths automatically.
- Add an in-app Copy YAML action when fan telemetry is available.

## 1.0.0

- Initial stable release.
- Configure I2C, SPI, UART, host SSH, and raw Raspberry Pi boot settings.
- Import and manage existing four-point Raspberry Pi 5 fan curves.
- Display fan temperatures in Celsius or Fahrenheit.
- Detect configured interface state only after mounting the boot partition.
- Create timestamped backups before boot configuration changes.
- Provide an accessible Home Assistant Ingress interface with toggle switches.
