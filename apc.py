# launchpy, a Python binding and plugins for the Akai APC mini launchpad
# Copyright (C) 2023 RenWal
# 
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

import time
from enum import IntEnum, IntFlag
from threading import Lock
from typing import Iterable, Tuple, Union

from mido import Message
from mido.ports import IOPort


# these are the the numerical values expected by the APC,
# do not modify
class ButtonState(IntEnum):
    OFF          = 0
    # for round buttons that have just one color
    ON           = 1
    BLINK        = 2
    # for 3-color button matrix
    GREEN        = 1
    GREEN_BLINK  = 2
    RED          = 3
    RED_BLINK    = 4
    YELLOW       = 5
    YELLOW_BLINK = 6

    def toggle(self, color: ButtonState) -> ButtonState:
        if self == self.OFF:
            return color
        return self.OFF

    def blink(self, should_blink: bool) -> ButtonState:
        if self == self.OFF:
            return self.OFF
        if self.value & 1 and should_blink:
            return ButtonState(self.value+1)
        if not (self.value & 1) and not should_blink:
            return ButtonState(self.value-1)
        return ButtonState(self)

    @property
    def blinking(self):
        return not (self.value & 1) and not self == self.OFF

class ButtonArea(IntFlag):
    MATRIX       = 0b0001
    HORIZONTAL   = 0b0010
    VERTICAL     = 0b0100
    SHIFT_BUTTON = 0b1000

    @classmethod
    def split_flags(cls, areas):
        return [area for area in cls if area & areas]

class ButtonID:
    def __init__(self, area: ButtonArea, ordinal: Union[int, Tuple[int, int]]):
        self.area = area
        if isinstance(ordinal, tuple):
            assert self.area == ButtonArea.MATRIX, "Coordinate notation only allowed for matrix buttons"
            # matrix coords (column, row) to matrix index
            ordinal = ordinal[1]*8 + ordinal[0]
        self.ordinal = ordinal

    def __eq__(self, o: object) -> bool:
        if not isinstance(o, self.__class__):
            return False
        return self.area == o.area and self.ordinal == o.ordinal

    def __hash__(self) -> int:
        return hash((self.area, self.ordinal))

    def __repr__(self) -> str:
        if self.area == ButtonArea.MATRIX:
            col, row = self.matrix_coords
            return f"{self.area.name}[{col},{row}]"
        return f"{self.area.name}[{self.ordinal}]"
    
    @property
    def matrix_coords(self):
        if self.area != ButtonArea.MATRIX:
            raise ValueError("Not a matrix button")
        return divmod(self.ordinal, 8)[::-1]

    @classmethod
    def from_idx(cls, idx: int):
        if idx > APCMini.SHIFT_OFFSET:
            return None
        if idx == APCMini.SHIFT_OFFSET:
            return cls(ButtonArea.SHIFT_BUTTON, 0)
        if idx >= APCMini.VERTICAL_OFFSET:
            return cls(ButtonArea.VERTICAL, idx - APCMini.VERTICAL_OFFSET)
        if idx >= APCMini.HORIZONTAL_OFFSET:
            return cls(ButtonArea.HORIZONTAL, idx - APCMini.HORIZONTAL_OFFSET)
        if idx >= APCMini.MATRIX_OFFSET:
            return cls(ButtonArea.MATRIX, idx - APCMini.MATRIX_OFFSET)
        raise ValueError("Index invalid")

    def to_idx(self) -> int:
        if self.area == ButtonArea.SHIFT_BUTTON:
            if self.ordinal != 0:
                raise ValueError("Ordinal out of range")
            return self.ordinal + APCMini.SHIFT_OFFSET
        if self.area == ButtonArea.VERTICAL:
            if self.ordinal not in range(APCMini.N_VERTICAL):
                raise ValueError("Ordinal out of range")
            return self.ordinal + APCMini.VERTICAL_OFFSET
        if self.area == ButtonArea.HORIZONTAL:
            if self.ordinal not in range(APCMini.N_HORIZONTAL):
                raise ValueError("Ordinal out of range")
            return self.ordinal + APCMini.HORIZONTAL_OFFSET
        if self.area == ButtonArea.MATRIX:
            if self.ordinal not in range(APCMini.N_MATRIX):
                raise ValueError("Ordinal out of range")
            return self.ordinal + APCMini.MATRIX_OFFSET
        raise ValueError("Area invalid")

class APCMini:
    FADER_OFFSET      = 48
    N_FADERS          = 9
    MATRIX_OFFSET     = 0
    DIM_MATRIX        = 8
    N_MATRIX          = DIM_MATRIX**2
    HORIZONTAL_OFFSET = 64
    N_HORIZONTAL      = 8
    VERTICAL_OFFSET   = 82
    N_VERTICAL        = 8
    SHIFT_OFFSET      = 98

    # sysex messages reverse engineered by comparing to the protocol specification of
    # the advanced version of this device (APC Mini MK2)

    SYSEX_DEVICE_ENQUIRY = (
        0x7E, # Non-realtime
        0x00, # channel (always 0)
        0x06, # Inquiry Message
        0x01, # Inquiry Request
    )

    @property
    def sysex_introduction(self):
        return (
            self.manufacturer_id,
            self.system_exclusive_device_id,
            self.product_model_id,
            0x60, # MSG type
            0x00, # MSB of packet length
            0x04, # LSB of packet length
            0x00, # Application ID
            0x00, # Application major version
            0x00, # Application minor version
            0x00, # Application patch level
        )

    button_matrix_indices = list(range(MATRIX_OFFSET, MATRIX_OFFSET+N_MATRIX))
    horizontal_buttons_indices = list(range(HORIZONTAL_OFFSET, HORIZONTAL_OFFSET+N_HORIZONTAL))
    vertical_buttons_indices = list(range(VERTICAL_OFFSET, VERTICAL_OFFSET+N_VERTICAL))
    shift_button = [SHIFT_OFFSET]
    area_button_indices = {
        ButtonArea.MATRIX: button_matrix_indices,
        ButtonArea.HORIZONTAL: horizontal_buttons_indices,
        ButtonArea.VERTICAL: vertical_buttons_indices,
        ButtonArea.SHIFT_BUTTON: shift_button
    }

    def __init__(self, ioport: IOPort):
        self._ioport = ioport

        self.light_state = {x:ButtonState.OFF for x in self.all_button_indices}
        self.faders = [None] * self.N_FADERS

        self.cb_button_pressed = None
        self.cb_button_released = None
        self.cb_fader_value = None
        self.send_lock = Lock()

        self.manufacturer_id = None
        self.product_model_id = None
        self.system_exclusive_device_id = None

        self._handshake()
    
    # Experimental method to swap out the underlying port,
    # can be used to reconnect after the underlying MIDI port
    # was closed (USB reset during sleep, etc.).
    # It's up to the caller to ensure you connect back to the
    # correct device!
    def reset_port(self, ioport: IOPort):
        old_cb = self._ioport.input.callback
        with self.send_lock:
            self._ioport = ioport
            self._ioport.input.callback = old_cb
    
    def _handshake(self):
        # suspend callbacks
        old_cb = self._ioport.input.callback
        self._ioport.input.callback = None

        # not doing this might result in messages not being in the buffer yet
        time.sleep(0.05)
        self._flush()

        # send device enquiry to learn device ID (needed to build introduction message)
        enquiry_response = self._sysex(self.SYSEX_DEVICE_ENQUIRY)

        self.manufacturer_id = enquiry_response[4]
        self.product_model_id = enquiry_response[5]
        self.system_exclusive_device_id = enquiry_response[12]
        self.software_version = (
            enquiry_response[8]<<8 + enquiry_response[9], # major version
            enquiry_response[10]<<8 + enquiry_response[11], # minor version
        )
        self.serial = enquiry_response[13:17]
        print("Device ID: ", "-".join(map(hex, (self.manufacturer_id, self.product_model_id, self.system_exclusive_device_id))))
        print("Serial:", "-".join(map(str, self.serial)))
        print("Firmware:", ".".join(map(str, self.software_version)))

        if (self.manufacturer_id, self.product_model_id, self.system_exclusive_device_id) != (0x47, 0x28, 0x7F):
            print("WARNING: Encountered a different device ID than what the developer's device had.")
            print("This is interesting! Please test, and report your findings to the developer!")
        
        # send introduction message to query fader status
        introduction_response = self._sysex(self.sysex_introduction)

        # initialize fader values
        fader_status = introduction_response[6:15]
        self.faders = [f/127 for f in fader_status]

        # resume callbacks
        self._ioport.input.callback = old_cb
    
    def _flush(self):
        while self._ioport.poll():
            pass

    def _sysex(self, data):
        self._send(Message("sysex", data=data))
        response = self._ioport.receive()
        if response.type != "sysex":
            raise ValueError("Invalid response received")
        return response.data

    @property
    def all_button_indices(self, only_with_light: bool = False) -> Iterable[int]:
        yield from self.button_matrix_indices
        yield from self.horizontal_buttons_indices
        yield from self.vertical_buttons_indices
        if not only_with_light:
            yield from self.shift_button

    def reset(self, force: bool = True) -> None:
        for b in self.all_button_indices:
            self.set_button(b, ButtonState.OFF, force=force)

    def resync(self) -> None:
        # use this when the hardware was reset (this can happen when a
        # system goes to standby and the USB ports are configured to
        # power down during sleep) to bring the LEDs back in sync with
        # what the software believes them to be showing
        self.set_all_buttons(self.light_state.items(), force=True)
        # TODO we might want to re-query the fader states here
    
    def set_button(self, button: Union[int, ButtonID], state: ButtonState, force: bool = False) -> None:
        # there seems to be some limitation, be it in mido/rtmidi or in
        # the APC mini itself, that drops MIDI messages coming at a very
        # high rate
        if isinstance(button, ButtonID):
            button = button.to_idx()
        if force or self.light_state[button] != state:
            self._send(Message('note_on', note=button, velocity=state))
        self.light_state[button] = state

    def get_button(self, button: Union[int, ButtonID]) -> ButtonState:
        if isinstance(button, ButtonID):
            button = button.to_idx()
        return self.light_state[button]
   
    def enable_events(self) -> None:
        self._ioport.input.callback = self._event_callback

    def disable_events(self) -> None:
        self._ioport.input.callback = None

    @classmethod
    def id_to_fader(cls, fader_id: int) -> int:
        return fader_id - cls.FADER_OFFSET

    def _send(self, msg: Message):
        with self.send_lock:
            self._ioport.send(msg)
    
    def _event_callback(self, msg):
        if msg.type == "note_on":
            if callable(self.cb_button_pressed):
                self.cb_button_pressed(ButtonID.from_idx(msg.note))
        elif msg.type == "note_off":
            if callable(self.cb_button_released):
                self.cb_button_released(ButtonID.from_idx(msg.note))
        elif msg.type == "control_change":
            fader_id = self.id_to_fader(msg.control)
            float_val = msg.value/127
            self.faders[fader_id] = float_val
            if callable(self.cb_fader_value):
                self.cb_fader_value(fader_id, float_val)
        else:
            assert 0

    def get_area_light_state(self, area: ButtonArea) -> dict[int, ButtonState]:
        return { b:self.get_button(b) for b in self.get_area_buttons(area) }

    @classmethod
    def get_area_buttons(cls, area: ButtonArea) -> list[int]:
        return cls.area_button_indices[area]

    def set_all_buttons(self, btn_map: Iterable, force: bool = False):
        for b,s in btn_map:
            self.set_button(b, s, force)
