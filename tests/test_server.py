import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


SERVER_PATH = Path(__file__).parents[1] / "pi_hardware_studio" / "app" / "server.py"
FIXTURES = Path(__file__).parent / "fixtures"
SPEC = importlib.util.spec_from_file_location("pi_hardware_studio_server", SERVER_PATH)
server = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)


class FanCurveTests(unittest.TestCase):
    def test_accepts_valid_curve(self):
        curve = [
            {"temp_c": 35, "speed_pct": 30},
            {"temp_c": 50, "speed_pct": 50},
            {"temp_c": 60, "speed_pct": 70},
            {"temp_c": 65, "speed_pct": 100},
        ]
        self.assertEqual(server.validate_curve(curve), curve)

    def test_rejects_falling_speed(self):
        curve = [
            {"temp_c": 35, "speed_pct": 30},
            {"temp_c": 50, "speed_pct": 20},
            {"temp_c": 60, "speed_pct": 70},
            {"temp_c": 65, "speed_pct": 100},
        ]
        with self.assertRaises(server.AppError):
            server.validate_curve(curve)

    def test_generates_copy_ready_sensor_yaml(self):
        rpm_path = "/sys/devices/platform/cooling_fan/hwmon/hwmon2/fan1_input"
        pwm_path = "/sys/devices/platform/cooling_fan/hwmon/hwmon2/pwm1"
        yaml = server.generate_fan_sensor_yaml(rpm_path, pwm_path)
        self.assertIn(f"command: 'cat {rpm_path}'", yaml)
        self.assertIn(f"command: 'cat {pwm_path}'", yaml)
        self.assertIn('unique_id: "pi5fan_rpm"', yaml)
        self.assertIn('unique_id: "pi5fan_percentage"', yaml)
        self.assertIn("{{ value | int }}", yaml)
        self.assertIn("{{ ((value | int) / 255 * 100) | round(0, 'common') }}", yaml)

    def test_detected_fan_paths_are_inserted_into_yaml(self):
        with tempfile.TemporaryDirectory() as directory:
            hwmon = Path(directory) / "hwmon7"
            hwmon.mkdir()
            (hwmon / "fan1_input").write_text("3210\n", encoding="utf-8")
            (hwmon / "pwm1").write_text("128\n", encoding="utf-8")

            telemetry = server.read_fan_telemetry(Path(directory))

            self.assertTrue(telemetry["detected"])
            self.assertEqual(telemetry["rpm"], 3210)
            self.assertEqual(telemetry["speed_pct"], 50)
            self.assertIn(
                f"command: 'cat {hwmon / 'fan1_input'}'",
                telemetry["sensor_yaml"],
            )
            self.assertIn(
                f"command: 'cat {hwmon / 'pwm1'}'",
                telemetry["sensor_yaml"],
            )


class ConfigParsingTests(unittest.TestCase):
    def test_parses_managed_block(self):
        content = """# sample
# BEGIN PI HARDWARE STUDIO
dtparam=i2c_arm=on
dtparam=spi=off
enable_uart=1
dtparam=fan_temp0=35000
dtparam=fan_temp0_hyst=5000
dtparam=fan_temp0_speed=77
dtparam=fan_temp1=50000
dtparam=fan_temp1_hyst=5000
dtparam=fan_temp1_speed=128
dtparam=fan_temp2=60000
dtparam=fan_temp2_hyst=5000
dtparam=fan_temp2_speed=179
dtparam=fan_temp3=65000
dtparam=fan_temp3_hyst=5000
dtparam=fan_temp3_speed=255
# END PI HARDWARE STUDIO
"""
        settings = server.parse_managed_settings(content)
        self.assertTrue(settings["i2c"])
        self.assertFalse(settings["spi"])
        self.assertTrue(settings["serial"])
        self.assertTrue(settings["fan_enabled"])
        self.assertEqual(settings["fan_curve"][0]["temp_c"], 35)

    def test_detects_existing_interface_variants(self):
        content = """# Existing user configuration
dtparam=i2c_arm=on,i2c_arm_baudrate=400000
dtparam=spi=on # display
enable_uart=1
"""
        settings = server.parse_managed_settings(content)
        self.assertTrue(settings["i2c"])
        self.assertTrue(settings["spi"])
        self.assertTrue(settings["serial"])

    def test_detects_i2c_aliases(self):
        self.assertTrue(server.parse_managed_settings("dtparam=i2c=on\n")["i2c"])
        self.assertTrue(server.parse_managed_settings("dtparam=i2c_vc=on\n")["i2c"])

    def test_last_interface_setting_wins(self):
        content = "dtparam=i2c_arm=on\ndtparam=i2c_arm=off\n"
        self.assertFalse(server.parse_managed_settings(content)["i2c"])

    def test_imports_home_assistant_os_configuration(self):
        content = (FIXTURES / "home_assistant_os_config.txt").read_text(encoding="utf-8")
        settings = server.parse_managed_settings(content)
        self.assertTrue(settings["i2c"])
        self.assertFalse(settings["spi"])
        self.assertFalse(settings["serial"])
        self.assertTrue(settings["fan_enabled"])
        self.assertEqual(
            settings["fan_curve"],
            [
                {"temp_c": 35, "speed_pct": 29.4},
                {"temp_c": 50, "speed_pct": 49.0},
                {"temp_c": 60, "speed_pct": 68.6},
                {"temp_c": 65, "speed_pct": 98.0},
            ],
        )

    def test_no_existing_fan_settings_uses_disabled_default_curve(self):
        content = """[all]
dtparam=i2c_arm=on
dtparam=spi=off
"""
        settings = server.parse_managed_settings(content)
        self.assertFalse(settings["fan_enabled"])
        self.assertEqual(
            settings["fan_curve"],
            [
                {"temp_c": 35, "speed_pct": 30},
                {"temp_c": 50, "speed_pct": 50},
                {"temp_c": 60, "speed_pct": 70},
                {"temp_c": 65, "speed_pct": 100},
            ],
        )

    def test_pre_mount_state_ignores_runtime_devices(self):
        settings, runtime = server.resolve_interface_status(
            "",
            mounted=False,
            runtime_interfaces={"i2c": True, "spi": True, "serial": True},
        )
        self.assertFalse(settings["i2c"])
        self.assertFalse(settings["spi"])
        self.assertFalse(settings["serial"])
        self.assertEqual(
            runtime,
            {"i2c": False, "spi": False, "serial": False},
        )

    def test_mounted_switches_follow_config_not_runtime_devices(self):
        content = "[all]\ndtparam=i2c_arm=on\ndtparam=spi=off\nenable_uart=0\n"
        settings, runtime = server.resolve_interface_status(
            content,
            mounted=True,
            runtime_interfaces={"i2c": True, "spi": True, "serial": True},
        )
        self.assertTrue(settings["i2c"])
        self.assertFalse(settings["spi"])
        self.assertFalse(settings["serial"])
        self.assertEqual(
            runtime,
            {"i2c": True, "spi": True, "serial": True},
        )


class CmdlineTests(unittest.TestCase):
    def test_parses_last_psi_parameter(self):
        content = "console=tty1 psi=0 rootwait psi=1"
        self.assertEqual(server.parse_cmdline_parameter(content, "psi"), "1")

    def test_adds_replaces_and_removes_psi_parameter(self):
        original = "console=tty1 psi=0 rootwait"
        enabled = server.update_cmdline_parameter(original, "psi", "1")
        self.assertEqual(enabled, "console=tty1 rootwait psi=1")
        self.assertEqual(
            server.update_cmdline_parameter(enabled, "psi", None),
            "console=tty1 rootwait",
        )

    def test_write_cmdline_creates_backup_and_keeps_one_line(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.txt"
            cmdline_path = root / "cmdline.txt"
            config_path.write_text("# original\n", encoding="utf-8")
            cmdline_path.write_text("console=tty1 rootwait\n", encoding="utf-8")
            manager = server.BootManager()
            manager._mounted = [
                server.MountedBoot(root / "device", root, config_path, cmdline_path)
            ]

            backup = manager.write_cmdline("console=tty1 rootwait psi=1")

            self.assertEqual(
                cmdline_path.read_text(encoding="utf-8"),
                "console=tty1 rootwait psi=1\n",
            )
            self.assertTrue((root / backup).is_file())

    def test_write_cmdline_rejects_multiple_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.txt"
            cmdline_path = root / "cmdline.txt"
            config_path.write_text("# original\n", encoding="utf-8")
            cmdline_path.write_text("console=tty1 rootwait\n", encoding="utf-8")
            manager = server.BootManager()
            manager._mounted = [
                server.MountedBoot(root / "device", root, config_path, cmdline_path)
            ]

            with self.assertRaises(server.AppError):
                manager.write_cmdline("console=tty1\npsi=1")


class ConfigWriteTests(unittest.TestCase):
    @staticmethod
    def apply(manager, root, payload):
        original_data_root = server.DATA_ROOT
        original_settings_file = server.SETTINGS_FILE
        server.DATA_ROOT = root / "data"
        server.SETTINGS_FILE = server.DATA_ROOT / "settings.json"
        try:
            return manager.apply_settings(payload)
        finally:
            server.DATA_ROOT = original_data_root
            server.SETTINGS_FILE = original_settings_file

    def test_apply_settings_creates_backup_and_managed_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.txt"
            config_path.write_text("# original\n", encoding="utf-8")
            manager = server.BootManager()
            manager._mounted = [
                server.MountedBoot(root / "device", root, config_path)
            ]
            result = self.apply(
                manager,
                root,
                {
                    "i2c": True,
                    "spi": False,
                    "serial": True,
                    "fan_enabled": True,
                    "fan_curve": [
                        {"temp_c": 35, "speed_pct": 30},
                        {"temp_c": 50, "speed_pct": 50},
                        {"temp_c": 60, "speed_pct": 70},
                        {"temp_c": 65, "speed_pct": 100},
                    ],
                    "temperature_unit": "C",
                },
            )

            updated = config_path.read_text(encoding="utf-8")
            self.assertIn(server.MANAGED_BEGIN, updated)
            self.assertIn("dtparam=fan_temp3_speed=255", updated)
            self.assertTrue((root / result["backup"]).is_file())

    def test_apply_settings_replaces_existing_fan_directives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.txt"
            config_path.write_text(
                (FIXTURES / "home_assistant_os_config.txt").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            manager = server.BootManager()
            manager._mounted = [server.MountedBoot(root / "device", root, config_path)]
            self.apply(
                manager,
                root,
                {
                    "i2c": True,
                    "spi": False,
                    "serial": False,
                    "fan_enabled": True,
                    "fan_curve": [
                        {"temp_c": 40, "speed_pct": 25},
                        {"temp_c": 50, "speed_pct": 50},
                        {"temp_c": 60, "speed_pct": 75},
                        {"temp_c": 70, "speed_pct": 100},
                    ],
                    "temperature_unit": "C",
                },
            )

            updated = config_path.read_text(encoding="utf-8")
            self.assertEqual(updated.count("dtparam=fan_temp0="), 1)
            self.assertIn("dtparam=fan_temp0=40000", updated)
            self.assertNotIn("dtparam=fan_temp0=35000", updated)

    def test_disabled_fan_curve_writes_no_fan_directives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.txt"
            config_path.write_text("[all]\ndtparam=i2c_arm=on\n", encoding="utf-8")
            manager = server.BootManager()
            manager._mounted = [server.MountedBoot(root / "device", root, config_path)]

            self.apply(
                manager,
                root,
                {
                    "i2c": True,
                    "spi": False,
                    "serial": False,
                    "fan_enabled": False,
                    "fan_curve": [
                        {"temp_c": 35, "speed_pct": 30},
                        {"temp_c": 50, "speed_pct": 50},
                        {"temp_c": 60, "speed_pct": 70},
                        {"temp_c": 65, "speed_pct": 100},
                    ],
                    "temperature_unit": "C",
                },
            )

            updated = config_path.read_text(encoding="utf-8")
            self.assertNotIn("fan_temp", updated)
            self.assertFalse(server.parse_managed_settings(updated)["fan_enabled"])

    def test_enabled_fan_curve_adds_settings_when_none_exist(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.txt"
            config_path.write_text("[all]\ndtparam=i2c_arm=on\n", encoding="utf-8")
            manager = server.BootManager()
            manager._mounted = [server.MountedBoot(root / "device", root, config_path)]

            self.apply(
                manager,
                root,
                {
                    "i2c": True,
                    "spi": False,
                    "serial": False,
                    "fan_enabled": True,
                    "fan_curve": [
                        {"temp_c": 35, "speed_pct": 30},
                        {"temp_c": 50, "speed_pct": 50},
                        {"temp_c": 60, "speed_pct": 70},
                        {"temp_c": 65, "speed_pct": 100},
                    ],
                    "temperature_unit": "C",
                },
            )

            updated = config_path.read_text(encoding="utf-8")
            self.assertIn("dtparam=fan_temp0=35000", updated)
            self.assertIn("dtparam=fan_temp3_speed=255", updated)
            self.assertTrue(server.parse_managed_settings(updated)["fan_enabled"])

    def test_apply_settings_enables_psi_in_cmdline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "config.txt"
            cmdline_path = root / "cmdline.txt"
            config_path.write_text("[all]\ndtparam=i2c_arm=on\n", encoding="utf-8")
            cmdline_path.write_text("console=tty1 psi=0 rootwait\n", encoding="utf-8")
            manager = server.BootManager()
            manager._mounted = [
                server.MountedBoot(root / "device", root, config_path, cmdline_path)
            ]

            result = self.apply(
                manager,
                root,
                {
                    "i2c": True,
                    "spi": False,
                    "serial": False,
                    "psi": True,
                    "fan_enabled": False,
                    "fan_curve": [
                        {"temp_c": 35, "speed_pct": 30},
                        {"temp_c": 50, "speed_pct": 50},
                        {"temp_c": 60, "speed_pct": 70},
                        {"temp_c": 65, "speed_pct": 100},
                    ],
                    "temperature_unit": "C",
                },
            )

            self.assertEqual(
                cmdline_path.read_text(encoding="utf-8"),
                "console=tty1 rootwait psi=1\n",
            )
            self.assertTrue((root / result["cmdline_backup"]).is_file())


if __name__ == "__main__":
    unittest.main()
