# Pi Hardware Studio

Open the Web UI, mount the detected boot partition, review the current state,
and apply only the settings you need.

All boot configuration writes create a timestamped sibling backup of
the file being changed. Most changes require a full host reboot. Some Home
Assistant OS and Raspberry Pi firmware combinations can require a second full
reboot before new device nodes appear.

## Kernel command line

Enable **Pressure Stall Information (PSI)** and apply settings to add `psi=1`
to `cmdline.txt`. Disabling the switch removes an existing `psi=` argument and
returns control to the operating system default.

The advanced editor can modify the complete `cmdline.txt`. The kernel command
line must remain a single non-empty line. Pi Hardware Studio rejects multiline
content and creates a timestamped backup before saving.

## Fan curve

Fan temperatures are stored in Celsius because Raspberry Pi firmware accepts
millidegrees Celsius. The C/F switch changes only how values are displayed and
entered in the Web UI. Fan speed percentages are converted to firmware PWM
values from 0 through 255.

When the running kernel exposes the fan RPM and PWM files, Pi Hardware Studio
generates two copy-ready Home Assistant `command_line` sensors. The commands use
a stable `hwmon*` path because Linux can change the numbered `hwmonN` directory
after a reboot. Copy the YAML into `configuration.yaml`, check the configuration,
and restart Home Assistant.

## SSH

Paste one complete public key line, such as an `ssh-ed25519` key. The key is
appended to `CONFIG/authorized_keys` on the boot partition if it is not already
present. Private keys are rejected.

## Warning

Raw `config.txt` or `cmdline.txt` editing can prevent the host from booting. Use
the structured controls when possible and keep a current Home Assistant backup.
