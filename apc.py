# launchpy, a Python binding and plugins for the Akai APC mini launchpad
# Copyright (C) 2022 RenWal
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
from enum import IntEnum, IntFlag
from typing import Iterable

from mido import Message
from mido.ports import IOPort


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

class ButtonArea(IntFlag):
    MATRIX       = 0b0001
    HORIZONTAL   = 0b0010
    VERTICAL     = 0b0100
    SHIFT_BUTTON = 0b1000

    @classmethod
    def split_flags(cls, areas):
        return [area for area in cls if area & areas]

class ButtonID:
    def __init__(self, area: ButtonArea, ordinal: int):
        self.area = area
        self.ordinal = ordinal
    def __eq__(self, o: object) -> bool:
        if not isinstance(o, self.__class__):
            return False
        return self.area == o.area and self.ordinal == o.ordinal
    def __hash__(self) -> int:
        return hash((self.area, self.ordinal))

class APCMini:
    FADER_OFFSET      = 48
    N_FADERS          = 9
    MATRIX_OFFSET     = 0
    N_MATRIX          = 8*8
    HORIZONTAL_OFFSET = 64
    N_HORIZONTAL      = 8
    VERTICAL_OFFSET   = 82
    N_VERTICAL        = 8
    SHIFT_OFFSET      = 98

    button_matrix = list(range(MATRIX_OFFSET, MATRIX_OFFSET+N_MATRIX))
    horizontal_buttons = list(range(HORIZONTAL_OFFSET, HORIZONTAL_OFFSET+N_HORIZONTAL))
    vertical_buttons = list(range(VERTICAL_OFFSET, VERTICAL_OFFSET+N_VERTICAL))
    shift_button = [SHIFT_OFFSET]
    area_buttons = {
        ButtonArea.MATRIX: button_matrix,
        ButtonArea.HORIZONTAL: horizontal_buttons,
        ButtonArea.VERTICAL: vertical_buttons,
        ButtonArea.SHIFT_BUTTON: shift_button
    }

    def __init__(self, ioport: IOPort):
        self._ioport = ioport

        self.light_state = {x:ButtonState.OFF for x in self.all_buttons}
        self.faders = [None] * self.N_FADERS

        self.cb_button_pressed = None
        self.cb_button_released = None
        self.cb_fader_value = None

    @property
    def all_buttons(self, only_with_light=False) -> Iterable[int]:
        yield from self.button_matrix
        yield from self.horizontal_buttons
        yield from self.vertical_buttons
        if not only_with_light:
            yield from self.shift_button

    def reset(self) -> None:
        for b in self.all_buttons:
            self.set_button(b, ButtonState.OFF, force=True)

    def resync(self) -> None:
        # use this when the hardware was reset (this can happen when a
        # system goes to standby and the USB ports are configured to
        # power down during sleep) to bring the LEDs back in sync with
        # what the software believes them to be showing
        self.set_all_buttons(self.light_state.items(), force=True)
    
    def set_button(self, button: int, state: ButtonState, force: bool = False) -> None:
        # there seems to be some limitation, be it in mido/rtmidi or in
        # the APC mini itself, that drops MIDI messages coming at a very
        # high rate
        if force or self.light_state[button] != state:
            self._send(Message('note_on', note=button, velocity=state))
        self.light_state[button] = state
   
    def enable_events(self) -> None:
        self._ioport.input.callback = self._event_callback

    def disable_events(self) -> None:
        self._ioport.input.callback = None

    @classmethod
    def id_to_fader(cls, fader_id: int) -> int:
        return fader_id - cls.FADER_OFFSET

    @classmethod
    def id_to_button(cls, button_id) -> ButtonID:
        if button_id > cls.SHIFT_OFFSET:
            return None
        if button_id == cls.SHIFT_OFFSET:
            return ButtonID(ButtonArea.SHIFT_BUTTON, 0)
        if button_id >= cls.VERTICAL_OFFSET:
            return ButtonID(ButtonArea.VERTICAL, button_id - cls.VERTICAL_OFFSET)
        if button_id >= cls.HORIZONTAL_OFFSET:
            return ButtonID(ButtonArea.HORIZONTAL, button_id - cls.HORIZONTAL_OFFSET)
        if button_id >= cls.MATRIX_OFFSET:
            return ButtonID(ButtonArea.MATRIX, button_id - cls.MATRIX_OFFSET)
        return None

    def _send(self, msg: Message):
        self._ioport.send(msg)
    
    def _event_callback(self, msg):
        if msg.type == "note_on":
            if callable(self.cb_button_pressed):
                self.cb_button_pressed(self.id_to_button(msg.note))
        elif msg.type == "note_off":
            if callable(self.cb_button_released):
                self.cb_button_released(self.id_to_button(msg.note))
        elif msg.type == "control_change":
            fader_id = self.id_to_fader(msg.control)
            float_val = msg.value/127
            self.faders[fader_id] = float_val
            if callable(self.cb_fader_value):
                self.cb_fader_value(fader_id, float_val)
        else:
            assert 0

    def get_area_light_state(self, area: ButtonArea) -> dict[int, ButtonState]:
        return { b:self.light_state[b] for b in self.get_area_buttons(area) }

    @classmethod
    def get_area_buttons(cls, area: ButtonArea) -> list[int]:
        return cls.area_buttons[area]

    def set_all_buttons(self, btn_map: Iterable, force: bool = False):
        for b,s in btn_map:
            self.set_button(b, s, force)
