[![Home Assistant App][badge_home_assistant]][repository_link]
[![Latest Release][badge_release]][release_link]
[![License: MIT][badge_license]][license_link]

# Pi Hardware Studio

![Pi Hardware Studio](pi_hardware_studio/logo.png)

Pi Hardware Studio is a Home Assistant app for configuring Raspberry Pi hardware
features from one Ingress dashboard.

## Planned first release

- Enable or disable I2C, SPI, and the primary UART.
- Configure the Raspberry Pi 5 fan curve with four temperature/speed points.
- Display and edit fan temperatures in Celsius or Fahrenheit.
- Provision an SSH public key for Home Assistant OS host access on port 22222.
- Inspect and carefully edit the boot `config.txt`.
- Create a timestamped backup before every boot configuration write.
- Request a Home Assistant host reboot after configuration changes.
- Display detected fan RPM and PWM percentage when the kernel exposes them.

## Installation

This repository is still under development. When it is published:

1. In Home Assistant, open **Settings > Apps > App store**.
2. Open **Repositories** from the menu.
3. Add this repository URL.
4. Install **Pi Hardware Studio**.
5. Disable protection mode for the app. Mounting the host boot partition
   requires elevated access.
6. Start the app and open its Web UI.

## Security

Pi Hardware Studio needs `SYS_ADMIN` and full device access to locate and mount the
Home Assistant OS boot partition. Keep protection mode enabled for unrelated
apps. Review this repository before installing and re-enable protection by
stopping or uninstalling Pi Hardware Studio when configuration is complete.

The app does not expose a standalone web port. Its interface is available only
through Home Assistant Ingress.

## Clean-room implementation

This project is an original implementation. No source code or visual assets
were copied from the projects listed below. Their public behavior and
documentation helped identify useful Raspberry Pi configuration workflows.
At the time this project was started, those repositories did not declare an
open-source license, so their code is not incorporated here.

## Acknowledgements

- [SunFounder Pi Config Wizard WWW](https://github.com/sunfounder/pi-config-wizard-www)
  demonstrated the value of a single web screen for I2C, SPI, raw boot
  configuration, and reboot controls.
- [Pi5FanEnabler](https://github.com/sOckhamSter/Pi5FanEnabler) highlighted the
  Raspberry Pi 5 fan firmware parameters and fan telemetry paths on Home
  Assistant OS.
- [HassOSConfigurator](https://github.com/adamoutler/HassOSConfigurator)
  documented practical Home Assistant OS boot-partition workflows for I2C,
  UART, and SSH key provisioning.

Raspberry Pi configuration behavior is implemented from the official
[Raspberry Pi documentation](https://www.raspberrypi.com/documentation/computers/config_txt.html).
Home Assistant packaging follows the official
[Home Assistant app documentation](https://developers.home-assistant.io/docs/apps/configuration).

## License

[MIT](LICENSE)

[badge_home_assistant]: https://img.shields.io/badge/Home%20Assistant-App-blue.svg?style=for-the-badge&logo=homeassistant&logoColor=white
[badge_release]: https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fraw.githubusercontent.com%2FComputerWhisperers%2Fha-pi-hardware-studio%2Frefs%2Fheads%2Fmain%2Fpi_hardware_studio%2Fconfig.yaml&query=%24.version&style=for-the-badge&label=release
[badge_license]: https://img.shields.io/badge/License-MIT-green.svg?style=for-the-badge
[license_link]: LICENSE
[release_link]: https://github.com/ComputerWhisperers/ha-pi-hardware-studio/releases/latest
[repository_link]: https://github.com/ComputerWhisperers/ha-pi-hardware-studio
