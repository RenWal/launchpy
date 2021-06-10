from enum import Enum, IntEnum, auto, unique
from time import sleep

import mido
import pulsectl

APC_PORT = "APC MINI:APC MINI MIDI 1 20:0"

@unique
class ButtonState(IntEnum):
    OFF = 0
    GREEN = 1
    GREEN_BLINK = 2
    RED = 3
    RED_BLINK = 4
    YELLOW = 5
    YELLOW_BLINK = 6

class ButtonArea(Enum):
    BUTTON_MATRIX = auto()
    HORIZONTAL = auto()
    VERTICAL = auto()
    SHIFT_BUTTON = auto()

class APCMini:
    FADER_OFFSET = 48
    N_FADERS = 9
    MATRIX_OFFSET = 0
    N_MATRIX = 8*8
    HORIZONTAL_OFFSET = 64
    N_HORIZONTAL = 8
    VERTICAL_OFFSET = 82
    N_VERTICAL = 8
    SHIFT_OFFSET = 98

    def __init__(self, ioport: mido.ports.IOPort):
        self._ioport = ioport

        self.button_matrix = list(range(self.N_MATRIX))
        self.horizontal_buttons = [self.HORIZONTAL_OFFSET+x for x in range(self.N_HORIZONTAL)]
        self.vertical_buttons = [self.VERTICAL_OFFSET+x for x in range(self.N_VERTICAL)]
        self.shift_button = self.SHIFT_OFFSET
        self.light_state = {x:ButtonState.OFF for x in self.all_buttons}
        self.faders = {x:None for x in range(self.N_FADERS)}

        self.cb_button_pressed = None
        self.cb_button_released = None
        self.cb_fader_value = None

    @property
    def all_buttons(self, only_with_light=False):
        yield from self.button_matrix
        yield from self.horizontal_buttons
        yield from self.vertical_buttons
        if not only_with_light:
            yield self.shift_button

    def reset(self):
        for b in self.all_buttons:
            self.set_button(b, ButtonState.OFF)
    
    def set_button(self, button: int, state: ButtonState):
        # there seems to be some limitation, be it in mido/rtmidi or in
        # the APC mini itself, that drops MIDI messages coming at a very
        # high rate
        self._send(mido.Message('note_on', note=button, velocity=state))
   
    def enable_events(self):
        self._ioport.input.callback = self._event_callback

    def disable_events(self):
        self._ioport.input.callback = None

    def id_to_fader(self, fader_id):
        return fader_id - self.FADER_OFFSET

    def id_to_button(self, button_id):
        if button_id > self.SHIFT_OFFSET:
            return None
        if button_id == self.SHIFT_OFFSET:
            return (ButtonArea.SHIFT_BUTTON, 0)
        if button_id >= self.VERTICAL_OFFSET:
            return (ButtonArea.VERTICAL, button_id - self.VERTICAL_OFFSET)
        if button_id >= self.HORIZONTAL_OFFSET:
            return (ButtonArea.HORIZONTAL, button_id - self.HORIZONTAL_OFFSET)
        if button_id >= self.MATRIX_OFFSET:
            return (ButtonArea.BUTTON_MATRIX, button_id - self.MATRIX_OFFSET)
        return None

    def _send(self, msg: mido.Message):
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

## implement your callbacks here ##

def on_btn_press(btn):
    print(btn, "pressed")

def on_btn_release(btn):
    print(btn, "released")

def on_fader_change(fader, value):
    print("Fader", fader, "moved:", value)

####

def wait_keyboard_interrupt():
    try:
        while 1:
            sleep(1)
    except KeyboardInterrupt:
        pass

with mido.open_ioport(APC_PORT) as midiport:
    apc = APCMini(midiport)
    apc.reset()
    sleep(0.2) # APC doesn't like getting too many MIDI requests in a row
    apc.cb_button_pressed = on_btn_press
    apc.cb_button_released = on_btn_release
    apc.cb_fader_value = on_fader_change
    apc.enable_events()
    print("events on")
    wait_keyboard_interrupt()
    apc.disable_events()
    print("events off")
