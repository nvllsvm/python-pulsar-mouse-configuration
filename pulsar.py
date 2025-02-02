#!/usr/bin/env python3
import argparse
import ctypes
import dataclasses
import enum
import json
import struct

import usb

PAYLOAD_HEADER = 0x08


class Command(enum.IntEnum):
    ACTIVE_PROFILE_GET = 0x0e
    ACTIVE_PROFILE_SET = 0x0f
    DEVICE_EVENT = 0x0a
    MEM_GET = 0x08
    MEM_SET = 0x07
    POWER = 0x04
    RESTORE = 0x09
    STATUS = 0x03


PollingRateHz = {
    1000: 0x01,
    500: 0x02,
    250: 0x04,
    125: 0x08,
}


class LEDEffect(enum.IntEnum):
    BREATHE = 0x02
    STEADY = 0x01


class ButtonMode(enum.IntEnum):
    CUSTOM1 = 0x05
    DISABLED = 0x00
    DPI_CHANGE = 0x02
    DPI_LOCK = 0x0a
    MOUSE = 0x01
    PROFILE_CHANGE = 0x09


class MouseKey(enum.IntEnum):
    LEFT = 0x01
    RIGHT = 0x02
    WHEEL = 0x04
    BACK = 0x08
    FORWARD = 0x10


class DPIChangeKey(enum.IntEnum):
    LOOP = 0x01
    PLUS = 0x02
    MINUS = 0x03


class DeviceEvent(enum.IntEnum):
    POWER = 0x40
    DPI_MODE = 0x01

    # 08:0a:00:00:00:0a:04:00:00:00:00:00:00:00:00:00:35
    UNKNOWN_1 = 0x04


class Bool(enum.IntEnum):
    TRUE = 0x01
    FALSE = 0x00


def inverse(dict_obj):
    return {v: k for k, v in dict_obj.items()}


def build_payload(command, *,
                  index02=0x00,
                  index03=0x00,
                  index04=0x00,
                  index05=0x00,
                  index06=0x00,
                  index07=0x00,
                  index08=0x00,
                  index09=0x00,
                  index10=0x00,
                  index11=0x00,
                  index12=0x00,
                  index13=0x00,
                  index14=0x00,
                  index15=0x00):
    payload = [
        PAYLOAD_HEADER,
        command,
        index02,
        index03,
        index04,
        index05,
        index06,
        index07,
        index08,
        index09,
        index10,
        index11,
        index12,
        index13,
        index14,
        index15,
    ]
    return bytearray([*payload, checksum(*payload)])


class Payload:
    def __bytes__(self):
        return bytes(self.payload)

    def __eq__(self, other):
        return self.payload == other.payload


class RestorePayload(Payload):
    # TODO does this restore all or only the active profile?
    @property
    def payload(self):
        return build_payload(Command.RESTORE)

    @classmethod
    def from_payload(cls, payload):
        inst = cls()
        assert payload == inst.payload
        return cls()


class RequestActiveProfilePayload(Payload):
    @property
    def payload(self):
        return build_payload(Command.ACTIVE_PROFILE_GET)

    @classmethod
    def from_payload(cls, payload):
        inst = cls()
        assert payload == inst.payload
        return inst


class SetActiveProfilePayload(Payload):
    def __init__(self, profile):
        self.payload = build_payload(
            Command.ACTIVE_PROFILE_SET,
            index05=0x01,
            index06=profile,
        )

    @property
    def profile(self):
        return self.payload[6]

    @classmethod
    def from_payload(cls, payload):
        profile = payload[6]
        inst = cls(profile)
        assert inst.payload == payload
        return inst


class CurrentActiveProfilePayload(Payload):
    def __init__(self, profile):
        self.payload = build_payload(
            Command.ACTIVE_PROFILE_GET,
            index05=0x01,
            index06=profile,
        )

    @property
    def profile(self):
        return self.payload[6]

    @classmethod
    def from_payload(cls, payload):
        profile = payload[6]
        inst = cls(profile)
        assert inst.payload == payload
        return inst


class DeviceEventPayload(Payload):
    @property
    def payload(self):
        return build_payload(
            Command.DEVICE_EVENT,
            index05=0x0a,
            index06=self.EVENT_FUNCTION,
        )

    @classmethod
    def from_payload(cls, payload):
        inst = cls()
        assert payload == inst.payload
        return inst


def dump_data(device):
    start = 0x00
    end = 0xff
    result = []
    for index in range(start, end, 10):
        payload = [
            PAYLOAD_HEADER,
            0x08,
            0x00,
            0x00,
            index,
            0x0a,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
            0x00,
        ]
        payload = [*payload, checksum(*payload)]
        device.send(payload)
        data = device.read()
        assert data[0] == payload[0]
        assert data[1] == payload[1]
        assert data[2] == payload[2]
        assert data[3] == payload[3]
        assert data[4] == payload[4]
        assert data[5] == payload[5]
        result.extend(data)
    return result


class Unknown1DeviceEventPayload(DeviceEventPayload):
    """
    Unkown event
    """
    EVENT_FUNCTION = DeviceEvent.UNKNOWN_1


class DPIModeDeviceEventPayload(DeviceEventPayload):
    """
    DPI mode button was pressed
    """
    EVENT_FUNCTION = DeviceEvent.DPI_MODE


class PowerDeviceEventPayload(DeviceEventPayload):
    """
    A power event occurred, but the device is not currently configured to
    report specific details
    """
    EVENT_FUNCTION = DeviceEvent.POWER


DEVICE_EVENT_CLASSES = [
    Unknown1DeviceEventPayload,
    DPIModeDeviceEventPayload,
    PowerDeviceEventPayload,
]
DEVICE_EVENT_TYPES = {}
for c in DEVICE_EVENT_CLASSES:
    func = c.EVENT_FUNCTION
    assert func not in DEVICE_EVENT_TYPES
    DEVICE_EVENT_TYPES[func] = c


class RequestPowerDetailsPayload(Payload):
    @property
    def payload(self):
        return build_payload(Command.POWER)

    @classmethod
    def from_payload(cls, payload):
        inst = cls()
        assert payload == inst.payload
        return inst


@dataclasses.dataclass
class PowerDetails:
    battery_percentage: int
    battery_millivoltage: int
    power_connected: bool


def parse_power_details(data):
    return PowerDetails(
        battery_percentage=data[6],
        battery_millivoltage=struct.unpack('>H', data[8:10])[0],
        power_connected=bool_to_int(data[7]),
    )


def from_payload(payload):
    assert len(payload) == 17
    assert payload[16] == checksum(*payload[0:16])
    command = payload[1]
    if command == Command.POWER:
        if payload == RequestPowerDetailsPayload().payload:
            return RequestPowerDetailsPayload()
        else:
            raise NotImplementedError
            #return PowerDetailsPayload.from_payload(payload)
    elif command == Command.RESTORE:
        return RestorePayload()
    elif command == Command.STATUS:
        raise NotImplementedError
        #if payload == RequestStatusPayload().payload:
        #    return RequestStatusPayload()
        #else:
        #    return StatusPayload.from_payload(payload)
    elif command == Command.DEVICE_EVENT:
        settings_type = payload[6]
        return DEVICE_EVENT_TYPES[settings_type].from_payload(payload)
    elif command == Command.MEM_SET:
        raise NotImplementedError
        #settings_type = payload[4]
        #return SETTINGS_TYPES[settings_type].from_payload(payload)
    elif command == Command.MEM_GET:
        raise NotImplementedError
    elif command == Command.ACTIVE_PROFILE_SET:
        return SetActiveProfilePayload.from_payload(payload)
    elif command == Command.ACTIVE_PROFILE_GET:
        if payload == RequestActiveProfilePayload().payload:
            return RequestActiveProfilePayload()
        else:
            return CurrentActiveProfilePayload.from_payload(payload)
    else:
        raise NotImplementedError


DEBOUNCE_TIME_MIN = 0x00
DEBOUNCE_TIME_MAX = 0x1e

LOD_MM_MIN = 0x01
LOD_MM_MAX = 0x02

DPI_MODE_MIN = 0x00
DPI_MODE_MAX = 0x03

DPI_LOCK_MIN = 0x00  # 50
DPI_LOCK_MAX = 0x15  # 1100

AUTOSLEEP_TIME_MIN = 0x01  # 10 seconds
AUTOSLEEP_TIME_MAX = 0x3c  # 10 minutes

LED_BRIGHTNESS_MIN = 0x00
LED_BRIGHTNESS_MAX = 0xff

LED_BREATHE_SPEED_MIN = 0x01
LED_BREATHE_SPEED_MAX = 0x05

DPI_MODE_CT_MIN = 0x01
DPI_MODE_CT_MAX = 0x04

DPI_MIN = 50
DPI_MAX = 26000

ADDR_POLLING_RATE = 0x00
ADDR_POLLING_RATE_CHECKSUM = 0x01
ADDR_DPI_MODE_CT = 0x02
ADDR_DPI_MODE_CT_CHECKSUM = 0x03
ADDR_DPI_MODE = 0x04
ADDR_DPI_MODE_CHECKSUM = 0x05
ADDR_LOD_MM = 0x0a
ADDR_LOD_MM_CHECKSUM = 0x0b
ADDR_MODE0_DPI_INDEX1 = 0x0c
ADDR_MODE0_DPI_INDEX2 = 0x0d
ADDR_MODE0_DPI_INDEX3 = 0x0e
ADDR_MODE0_DPI_CHECKSUM = 0x0f
ADDR_MODE1_DPI_INDEX1 = 0x10
ADDR_MODE1_DPI_INDEX2 = 0x11
ADDR_MODE1_DPI_INDEX3 = 0x12
ADDR_MODE1_DPI_CHECKSUM = 0x13
ADDR_MODE2_DPI_INDEX1 = 0x14
ADDR_MODE2_DPI_INDEX2 = 0x15
ADDR_MODE2_DPI_INDEX3 = 0x16
ADDR_MODE2_DPI_CHECKSUM = 0x17
ADDR_MODE3_DPI_INDEX1 = 0x18
ADDR_MODE3_DPI_INDEX2 = 0x19
ADDR_MODE3_DPI_INDEX3 = 0x1a
ADDR_MODE3_DPI_CHECKSUM = 0x1b
ADDR_MODE0_LED_COLOR_R = 0x2c
ADDR_MODE0_LED_COLOR_G = 0x2d
ADDR_MODE0_LED_COLOR_B = 0x2e
ADDR_MODE0_LED_COLOR_CHECKSUM = 0x2f
ADDR_MODE1_LED_COLOR_R = 0x30
ADDR_MODE1_LED_COLOR_G = 0x31
ADDR_MODE1_LED_COLOR_B = 0x32
ADDR_MODE1_LED_COLOR_CHECKSUM = 0x33
ADDR_MODE2_LED_COLOR_R = 0x34
ADDR_MODE2_LED_COLOR_G = 0x35
ADDR_MODE2_LED_COLOR_B = 0x36
ADDR_MODE2_LED_COLOR_CHECKSUM = 0x37
ADDR_MODE3_LED_COLOR_R = 0x38
ADDR_MODE3_LED_COLOR_G = 0x39
ADDR_MODE3_LED_COLOR_B = 0x3a
ADDR_MODE3_LED_COLOR_CHECKSUM = 0x3b
ADDR_LED_EFFECT = 0x4c
ADDR_LED_EFFECT_CHECKSUM = 0x4d
ADDR_LED_BRIGHTNESS = 0x4e
ADDR_LED_BRIGHTNESS_CHECKSUM = 0x4f
ADDR_LED_BREATHE_SPEED = 0x50
ADDR_LED_BREATHE_SPEED_CHECKSUM = 0x51
ADDR_LED_ENABLED = 0x52
ADDR_LED_ENABLED_CHECKSUM = 0x53
ADDR_BUTTON_LEFT_MODE = 0x60
ADDR_BUTTON_LEFT_INDEX2 = 0x61
ADDR_BUTTON_LEFT_INDEX3 = 0x62
ADDR_BUTTON_LEFT_CHECKSUM = 0x63
ADDR_BUTTON_RIGHT_MODE = 0x64
ADDR_BUTTON_RIGHT_INDEX2 = 0x65
ADDR_BUTTON_RIGHT_INDEX3 = 0x66
ADDR_BUTTON_RIGHT_CHECKSUM = 0x67
ADDR_BUTTON_WHEEL_MODE = 0x68
ADDR_BUTTON_WHEEL_INDEX2 = 0x69
ADDR_BUTTON_WHEEL_INDEX3 = 0x6a
ADDR_BUTTON_WHEEL_CHECKSUM = 0x6b
ADDR_BUTTON_BACK_MODE = 0x6c
ADDR_BUTTON_BACK_INDEX2 = 0x6d
ADDR_BUTTON_BACK_INDEX3 = 0x6e
ADDR_BUTTON_BACK_CHECKSUM = 0x6f
ADDR_BUTTON_FORWARD_MODE = 0x70
ADDR_BUTTON_FORWARD_INDEX2 = 0x71
ADDR_BUTTON_FORWARD_INDEX3 = 0x72
ADDR_BUTTON_FORWARD_CHECKSUM = 0x73
ADDR_DEBOUNCE_TIME = 0xa9
ADDR_DEBOUNCE_TIME_CHECKSUM = 0xaa
ADDR_MOTION_SYNC = 0xab
ADDR_MOTION_SYNC_CHECKSUM = 0xac
ADDR_ANGLE_SNAPPING = 0xaf
ADDR_ANGLE_SNAPPING_CHECKSUM = 0xb0
ADDR_LOD_RIPPLE = 0xb1
ADDR_LOD_RIPPLE_CHECKSUM = 0xb2
ADDR_AUTOSLEEP_TIME = 0xb7
ADDR_AUTOSLEEP_TIME_CHECKSUM = 0xb8


ADDR_BUTTON_CUSTOM1 = (0x01, 0x20)


class CustomKey(enum.IntEnum):
    SEARCH = 0x21
    STOP = 0x26
    REFRESH = 0x27


# seems to follow the pattern of (length, v1, v2, v3) until a 0x00 length
BUTTONS_CUSTOM = {
    (0x02, 0x82, CustomKey.SEARCH,  0x02, 0x42, CustomKey.SEARCH,  0x02, 0x49): 'Search',
    (0x02, 0x82, CustomKey.STOP,    0x02, 0x42, CustomKey.STOP,    0x02, 0x3f): 'Stop',
    (0x02, 0x82, CustomKey.REFRESH, 0x02, 0x42, CustomKey.REFRESH, 0x02, 0x3d): 'Refresh',
    (0x04, 0x80, 0x01, 0x00, 0x81, 0x04, 0x00, 0x40, 0x01, 0x00, 0x41, 0x04, 0x00, 0xc5): 'Ctrl+A',
    (0x04, 0x80, 0x01, 0x00, 0x81, 0x05, 0x00, 0x40, 0x01, 0x00, 0x41, 0x05, 0x00, 0xc3): 'Ctrl+B',
}


def bool_to_int(value):
    match value:
        case 0:
            return False
        case 1:
            return True
        case _:
            raise ValueError


def int_to_bool(value):
    match value:
        case 0:
            return False
        case 1:
            return True
        case _:
            raise ValueError


def checksum(*values):
    return ctypes.c_uint8(0x55 - sum(values)).value


class Device:
    VENDOR_ID = 0x3554  # Pulsar
    DEVICE_ID = 0xf508  # X2V2 Mini (regular wireless dongle)

    INTERFACES = {
        0: {'endpoint': 0x81, 'length': 8},
        1: {'endpoint': 0x82, 'length': 17},
        2: {'endpoint': 0x83, 'length': 7},
    }

    def __init__(self):
        self.interface = 1
        info = self.INTERFACES[self.interface]
        self.length = info['length']
        self.endpoint = info['endpoint']
        self.device = usb.core.find(idVendor=self.VENDOR_ID, idProduct=self.DEVICE_ID)
        self.device.reset()
        self.open_device(self.get_device(self.VENDOR_ID, self.DEVICE_ID), 1)

    @staticmethod
    def get_device(vendor_id, device_id):
        for bus in usb.busses():
            for device in bus.devices:
                if device.idVendor == vendor_id and device.idProduct == device_id:
                    return device
        raise KeyError

    @staticmethod
    def open_device(device, interface):
        handle = device.open()
        try:
            handle.detachKernelDriver(interface)
        except Exception:
            pass
        handle.claimInterface(interface)
        return handle

    def write(self, payload):
        if not isinstance(payload, bytes):
            payload = bytes(payload)
        res = self.device.ctrl_transfer(
            0x21,  # Host-to-device
            0x09,  # Set report
            0x0208,  # wValue
            self.interface,
            payload)
        assert res == len(payload)

    def _read(self):
        data = self.device.read(self.endpoint, self.length, 0)
        return data.tobytes()

    def read(self, expect=None):
        while True:
            resp = self._read()
            if expect is None:
                return resp
            inst = from_payload(resp)
            if isinstance(inst, expect):
                return inst


def dpi_int_to_raw(dpi):
    """
    dpi_index1: same as dpi_index2
    dpi_index2: (val+1)*50; sequential 00 to ff
    dpi_index3: (factor*12800)
        00: factor=0;    50 <= dpi <= 12750
        44: factor=1; 12850 <= dpi <= 25600
        88: factor=2; 25650 <= dpi <= 26000
    """
    if not (DPI_MIN <= dpi <= DPI_MAX):
        raise ValueError
    quo, rem = divmod(dpi, 50)
    if rem:
        raise ValueError('DPI must be multiple of 50')
    factor12800, factor50 = divmod(quo-1, 256)

    index2 = factor50
    index3 = factor12800 << 2 | factor12800 << 6
    return bytearray([index2, index2, index3])


def dpi_raw_to_int(raw):
    raw = bytearray(raw)
    if len(raw) != 3:
        raise ValueError
    if raw[0] != raw[1]:
        raise ValueError
    factor50 = raw[1] + 1

    nib1 = raw[2] & 0b00001111
    nib2 = raw[2] >> 4
    if nib1 != nib2:
        raise ValueError
    if nib1 != (nib1 & 0b1100):
        raise ValueError
    factor12800 = nib1 >> 2
    return (factor50*50) + (factor12800*12800)


class PulsarX2V2Mini:
    LED_EFFECTS = {
        'off',
        'breathe',
        'steady',
    }

    def __init__(self, dev):
        self.dev = dev
        self.settings = {}
        self._profile = None

    def get_power(self):
        payload = build_payload(Command.POWER)
        self.dev.write(payload)
        while True:
            resp = self.dev.read()
            if resp[1] == Command.POWER:
                break
        return parse_power_details(resp)

    def read_settings(self):
        min_addr = 0x00
        max_addr = 0xb8
        current = min_addr
        settings = {}
        while current <= (max_addr + 10):
            length = 10
            payload = build_payload(
                Command.MEM_GET,
                index04=current,
                index05=length,
            )
            self.dev.write(payload)
            resp = self.dev.read()
            assert resp[4] == current
            assert resp[5] == length
            for (k, v) in enumerate(resp[6:6+length], current):
                settings[k] = v
            current += 10
        self.settings = settings

    def read_profile(self):
        self.dev.write(RequestActiveProfilePayload())
        resp = self.dev.read(CurrentActiveProfilePayload)
        self.profile = resp.profile

    @property
    def profile(self):
        if self._profile is None:
            self.read_profile()
        return self._profile

    @profile.setter
    def profile(self, value):
        inst = SetActiveProfilePayload(value)
        self.dev.write(inst)
        resp = self.dev.read(SetActiveProfilePayload)
        assert resp.profile == inst.profile
        self._profile = inst.profile

    def restore(self):
        payload = build_payload(Command.RESTORE)
        self.dev.write(payload)
        resp = self.dev.read()
        assert resp == payload
        self.settings.clear()

    @property
    def is_on(self):
        payload = build_payload(Command.STATUS)
        self.dev.write(payload)
        while True:
            resp = self.dev.read()
            if resp[1] == Command.STATUS:
                break
        return int_to_bool(resp[6])

    @property
    def polling_rate(self):
        return inverse(PollingRateHz)[self.settings[ADDR_POLLING_RATE]]

    @polling_rate.setter
    def polling_rate(self, rate):
        val = PollingRateHz[rate]
        self._mem_set({
            ADDR_POLLING_RATE: int(val),
            ADDR_POLLING_RATE_CHECKSUM: checksum(val),
        })

    def _mem_set(self, addresses):
        length = len(addresses)
        if not (1 <= length <= 10):
            raise ValueError('must not be longer than 10')
        start_address = min(addresses)
        indexes = [
            'index06',
            'index07',
            'index08',
            'index09',
            'index10',
            'index11',
            'index12',
            'index13',
            'index14',
            'index15',
        ]
        kwargs = {
            'index04': start_address,
            'index05': length,
        }
        for index, address in zip(indexes, range(start_address, start_address+length)):
            kwargs[index] = addresses[address]

        payload = build_payload(Command.MEM_SET, **kwargs)
        assert self.is_on
        self.dev.write(payload)
        # TODO handle resp?
        resp = self.dev.read()
        self.settings.update(addresses)

    @property
    def dpi_mode(self):
        return self.settings[ADDR_DPI_MODE]

    @dpi_mode.setter
    def dpi_mode(self, value):
        if not isinstance(value, int):
            raise TypeError
        if not (DPI_MODE_MIN <= value <= DPI_MODE_MAX):
            raise ValueError
        self._mem_set({
            ADDR_DPI_MODE: value,
            ADDR_DPI_MODE_CHECKSUM: checksum(value),
        })

    @property
    def lod_mm(self):
        return self.settings[ADDR_LOD_MM]

    @lod_mm.setter
    def lod_mm(self, value):
        if not isinstance(value, int):
            raise TypeError
        if not (LOD_MM_MIN <= value <= LOD_MM_MAX):
            raise ValueError
        self._mem_set({
            ADDR_LOD_MM: value,
            ADDR_LOD_MM_CHECKSUM: checksum(value),
        })

    @property
    def debounce_time(self):
        return self.settings[ADDR_DEBOUNCE_TIME]

    @property
    def motion_sync(self):
        return bool(self.settings[ADDR_MOTION_SYNC])

    @motion_sync.setter
    def motion_sync(self, enabled):
        value = Bool(enabled)
        self._mem_set({
            ADDR_MOTION_SYNC: value,
            ADDR_MOTION_SYNC_CHECKSUM: checksum(value)
        })

    @property
    def lod_ripple(self):
        return bool(self.settings[ADDR_LOD_RIPPLE])

    @lod_ripple.setter
    def lod_ripple(self, enabled):
        value = Bool(enabled)
        self._mem_set({
            ADDR_LOD_RIPPLE: value,
            ADDR_LOD_RIPPLE_CHECKSUM: checksum(value)
        })

    @property
    def angle_snapping(self):
        return bool(self.settings[ADDR_ANGLE_SNAPPING])

    @angle_snapping.setter
    def angle_snapping(self, enabled):
        value = Bool(enabled)
        self._mem_set({
            ADDR_ANGLE_SNAPPING: value,
            ADDR_ANGLE_SNAPPING_CHECKSUM: checksum(value)
        })

    @property
    def led_effect(self):
        return LEDEffect(self.settings[ADDR_LED_EFFECT])

    @led_effect.setter
    def led_effect(self, value):
        raw = LEDEffect(value)
        self._mem_set({
            ADDR_LED_EFFECT: raw,
            ADDR_LED_EFFECT_CHECKSUM: checksum(raw),
        })

    @property
    def led_brightness(self):
        return self.settings[ADDR_LED_BRIGHTNESS]

    @led_brightness.setter
    def led_brightness(self, value):
        if not isinstance(value, int):
            raise TypeError
        if LED_BRIGHTNESS_MIN <= value <= LED_BRIGHTNESS_MAX:
            raise ValueError
        self._mem_set({
            ADDR_LED_BRIGHTNESS: value,
            ADDR_LED_BRIGHTNESS_CHECKSUM: checksum(value),
        })

    @property
    def led_breathe_speed(self):
        return self.settings[ADDR_LED_BREATHE_SPEED]

    @property
    def autosleep_time(self):
        return self.settings[ADDR_AUTOSLEEP_TIME] * 10

    @property
    def led_enabled(self):
        return bool(self.settings[ADDR_LED_ENABLED])

    @led_enabled.setter
    def led_enabled(self, enabled):
        value = Bool(enabled)
        self._mem_set({
            ADDR_LED_ENABLED: value,
            ADDR_LED_ENABLED_CHECKSUM: checksum(value)
        })

    def get_dpi(self, mode):
        addrs = ADDR_MODE[mode]
        return dpi_raw_to_int(
            bytearray([
                self.settings[addrs.dpi_index1],
                self.settings[addrs.dpi_index2],
                self.settings[addrs.dpi_index3],
            ])
        )

    def set_dpi(self, mode, dpi):
        raw = dpi_int_to_raw(dpi)
        addrs = ADDR_MODE[mode]
        self._mem_set({
            addrs.dpi_index1: raw[0],
            addrs.dpi_index2: raw[1],
            addrs.dpi_index3: raw[2],
            addrs.dpi_checksum: checksum(*raw),
        })

    @property
    def dpi(self):
        return self.get_dpi(self.dpi_mode)

    @dpi.setter
    def dpi(self, value):
        return self.set_dpi(self.dpi_mode, value)

    @property
    def dpi_mode_count(self):
        return self.settings[ADDR_DPI_MODE_CT]

    def get_led_color(self, mode):
        addrs = ADDR_MODE[mode]
        return int_to_color(
            addrs.led_color_r,
            addrs.led_color_g,
            addrs.led_color_b,
        )

    @property
    def led_color(self):
        return self.get_led_color(self.dpi_mode)

    def set_led_color(self, mode, color):
        addrs = ADDR_MODE[mode]
        r, g, b = color_to_int(color)
        self._mem_set({
            addrs.led_color_r: r,
            addrs.led_color_g: g,
            addrs.led_color_b: b,
            addrs.led_color_checksum: checksum(r+g+b),
        })

    @led_color.setter
    def led_color(self, color):
        self.set_led_color(self.dpi_mode, color)


@dataclasses.dataclass
class ModeAddresses:
    dpi_index1: int
    dpi_index2: int
    dpi_index3: int
    dpi_checksum: int
    led_color_r: int
    led_color_g: int
    led_color_b: int
    led_color_checksum: int


ADDR_MODE = [
    ModeAddresses(
        ADDR_MODE0_DPI_INDEX1,
        ADDR_MODE0_DPI_INDEX2,
        ADDR_MODE0_DPI_INDEX3,
        ADDR_MODE0_DPI_CHECKSUM,
        ADDR_MODE0_LED_COLOR_R,
        ADDR_MODE0_LED_COLOR_G,
        ADDR_MODE0_LED_COLOR_B,
        ADDR_MODE0_LED_COLOR_CHECKSUM),
    ModeAddresses(
        ADDR_MODE1_DPI_INDEX1,
        ADDR_MODE1_DPI_INDEX2,
        ADDR_MODE1_DPI_INDEX3,
        ADDR_MODE1_DPI_CHECKSUM,
        ADDR_MODE1_LED_COLOR_R,
        ADDR_MODE1_LED_COLOR_G,
        ADDR_MODE1_LED_COLOR_B,
        ADDR_MODE1_LED_COLOR_CHECKSUM),
    ModeAddresses(
        ADDR_MODE2_DPI_INDEX1,
        ADDR_MODE2_DPI_INDEX2,
        ADDR_MODE2_DPI_INDEX3,
        ADDR_MODE2_DPI_CHECKSUM,
        ADDR_MODE2_LED_COLOR_R,
        ADDR_MODE2_LED_COLOR_G,
        ADDR_MODE2_LED_COLOR_B,
        ADDR_MODE2_LED_COLOR_CHECKSUM),
    ModeAddresses(
        ADDR_MODE3_DPI_INDEX1,
        ADDR_MODE3_DPI_INDEX2,
        ADDR_MODE3_DPI_INDEX3,
        ADDR_MODE3_DPI_CHECKSUM,
        ADDR_MODE3_LED_COLOR_R,
        ADDR_MODE3_LED_COLOR_G,
        ADDR_MODE3_LED_COLOR_B,
        ADDR_MODE3_LED_COLOR_CHECKSUM),
]


def pretty_json(data):
    return json.dumps(data, indent=2, sort_keys=True)


def _parser_set(args):
    dev = Device()
    x2v2 = PulsarX2V2Mini(dev)

    if args.restore:
        x2v2.restore()

    x2v2.read_settings()

    if args.polling_rate is not None:
        x2v2.polling_rate = args.polling_rate

    if args.dpi_mode is not None:
        x2v2.dpi_mode = args.dpi_mode

    if args.led_brightness is not None:
        x2v2.led_brightness = args.led_brightness

    if args.led_color is not None:
        x2v2.led_color = args.led_color

    if args.motion_sync is not None:
        match args.motion_sync:
            case 'off':
                x2v2.motion_sync = False
            case 'on':
                x2v2.motion_sync = True

    if args.lod_ripple is not None:
        match args.lod_ripple:
            case 'off':
                x2v2.lod_ripple = False
            case 'on':
                x2v2.lod_ripple = True

    if args.angle_snapping is not None:
        match args.angle_snapping:
            case 'off':
                x2v2.angle_snapping = False
            case 'on':
                x2v2.angle_snapping = True

    if args.led_effect is not None:
        match args.led_effect:
            case 'off':
                x2v2.led_enabled = False
            case 'steady':
                x2v2.led_effect = LEDEffect.STEADY
                x2v2.led_enabled = True
            case 'breathe':
                x2v2.led_effect = LEDEffect.BREATHE
                x2v2.led_enabled = True

    if args.dpi is not None:
        x2v2.dpi = args.dpi

    if args.profile:
        pass

    info = {}

    power = x2v2.get_power()
    info['power'] = {
        'connected': power.power_connected,
        'battery_percent': power.battery_percentage,
        'battery_millivolts': power.battery_millivoltage,
    }
    modes = []
    for i, mode in enumerate(range(x2v2.dpi_mode_count)):
        modes.append({
            'dpi_mode': i,
            'led_color': x2v2.get_led_color(mode),
            'dpi': x2v2.get_dpi(mode),
        })

    settings = {
        'dpi_modes': modes,
        'active_profile': x2v2.profile,
        'active_dpi_mode': x2v2.dpi_mode,
        'angle_snapping_enabled': x2v2.angle_snapping,
        'autosleep_seconds': x2v2.autosleep_time,
        'debounce_milliseconds': x2v2.debounce_time,
        'lod': {
            'mm': x2v2.lod_mm,
            'ripple_enabled': x2v2.lod_ripple,
        },
        'motion_sync_enabled': x2v2.motion_sync,
        'polling_rate_hz': x2v2.polling_rate,
    }
    led = {
        'enabled': x2v2.led_enabled,
    }
    if x2v2.led_enabled:
        led['led_effect']
        settings['LED Color'] = x2v2.led_color
        if x2v2.led_effect == LEDEffect.BREATHE:
            effect = 'breathe'
            led['breathe_speed'] = x2v2.led_breathe_speed
        elif x2v2.led_effect == LEDEffect.STEADY:
            effect = 'steady'
            led['brightness'] = x2v2.led_brightness
    else:
        effect = None
    led['effect'] = effect
    settings['led'] = led
    info.update(settings)
    print(pretty_json(info))


def color_to_int(value):
    value = value.removeprefix('#')
    return (
        int(value[0:2], 16),
        int(value[2:4], 16),
        int(value[4:6], 16),
    )


def int_to_color(r, g, b):
    return f'#{r:02x}{g:02x}{b:02x}'


def _parser_color(value):
    color_to_int(value)
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dpi', type=int)
    parser.add_argument('--dpi-mode', type=int)
    parser.add_argument('--led-brightness', type=int)
    parser.add_argument('--led-color', type=_parser_color)
    parser.add_argument('--led-effect', choices=['off', 'steady', 'breathe'])
    parser.add_argument('--motion-sync', choices=['on', 'off'])
    parser.add_argument('--lod-ripple', choices=['on', 'off'])
    parser.add_argument('--angle-snapping', choices=['on', 'off'])
    parser.add_argument('--polling-rate', type=int, choices=PollingRateHz)

    # does not fail when profile does not exist
    parser.add_argument('--profile', type=int, help=argparse.SUPPRESS)
                        #help='switch the active profile')

    parser.add_argument('--restore', action='store_true',
                        help='restore factory-default settings')
    args = parser.parse_args()

    _parser_set(args)


if __name__ == '__main__':
    main()
