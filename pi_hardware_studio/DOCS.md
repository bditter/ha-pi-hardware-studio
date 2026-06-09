# Pi Hardware Studio

Open the Web UI, mount the detected boot partition, review the current state,
and apply only the settings you need.

All boot configuration writes create a timestamped sibling backup of
`config.txt`. Most changes require a full host reboot. Some Home Assistant OS
and Raspberry Pi firmware combinations can require a second full reboot before
new device nodes appear.

## Fan curve

Fan temperatures are stored in Celsius because Raspberry Pi firmware accepts
millidegrees Celsius. The C/F switch changes only how values are displayed and
entered in the Web UI. Fan speed percentages are converted to firmware PWM
values from 0 through 255.

## SSH

Paste one complete public key line, such as an `ssh-ed25519` key. The key is
appended to `CONFIG/authorized_keys` on the boot partition if it is not already
present. Private keys are rejected.

## Warning

Raw `config.txt` editing can prevent the host from booting. Use the structured
controls when possible and keep a current Home Assistant backup.
