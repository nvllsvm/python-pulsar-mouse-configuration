# python-pulsar-mouse-tool
A tool to view/edit the on-device settings of a Pulsar mouse. 
An alternative to the Windows-only Pulsar Fusion software.

Supported mice:
- Pulsar X2 v2 Mini

Features:
- view and modify settings stored on the mouse hardware
- view battery information

## History
The protocol was reverse engineered using Wireshark to inspect USB packets
when the mouse was passed-through to a Windows virtual machine running
the official Pulsar Fusion software.

It was mainly created for me to view the battery charge percentage and will
likely not see expanded support for other Pulsar mice. It also does not implement
all the features that Pulsar Fusion allows for configuration of (eg. button remapping, macros).

This repository serves mainly as a documentation of my reverse-engineering efforts and
could serve as a reference for implmenting in a more accesible, widely-used piece of software 
(eg. [libratbag](https://github.com/libratbag/libratbag)).


## Setup
Requires Python 3.7+ and [pyusb](https://github.com/pyusb/pyusb).

Simply clone this repository and run `python3 pulsar.py`.

**Note:** You'll likely need to either run with `sudo` or add a [udev rule](49-pulsar-mouse.rules).

## Usage
```
$ ./pulsar.py  --help
usage: pulsar.py [-h] [--dpi DPI] [--dpi-mode DPI_MODE] [--led-brightness LED_BRIGHTNESS] [--led-color LED_COLOR]
                 [--led-effect {off,steady,breathe}] [--polling-rate {1000,500,250,125}] [--restore]

options:
  -h, --help            show this help message and exit
  --dpi DPI
  --dpi-mode DPI_MODE
  --led-brightness LED_BRIGHTNESS
  --led-color LED_COLOR
  --led-effect {off,steady,breathe}
  --polling-rate {1000,500,250,125}
  --restore             restore factory-default settings
```


## Examples
### Retreive Current Settings and Battery Status
```
$ ./pulsar.py 
{
  "active_dpi_mode": 0,
  "active_profile": 0,
  "angle_snapping_enabled": false,
  "autosleep_seconds": 60,
  "debounce_milliseconds": 3,
  "dpi_modes": [
    {
      "dpi": 400,
      "dpi_mode": 0,
      "led_color": "#2c2d2e"
    },
    {
      "dpi": 800,
      "dpi_mode": 1,
      "led_color": "#303132"
    },
    {
      "dpi": 1600,
      "dpi_mode": 2,
      "led_color": "#343536"
    },
    {
      "dpi": 3200,
      "dpi_mode": 3,
      "led_color": "#38393a"
    }
  ],
  "led": {
    "effect": null,
    "enabled": false
  },
  "lod": {
    "mm": 1,
    "ripple_enabled": false
  },
  "motion_sync_enabled": true,
  "polling_rate_hz": 1000,
  "power": {
    "battery_millivolts": 3871,
    "battery_percent": 50,
    "connected": false
  }
}
```

### Set the active DPI mode's DPI
```
$ ./pulsar.py --dpi 400
```
