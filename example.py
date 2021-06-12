from __future__ import annotations

from collections import deque
from enum import Enum, IntEnum, auto, unique
from time import sleep

import mido

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
    MATRIX = auto()
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
    
    class ButtonID:
        def __init__(self, area: ButtonArea, ordinal: int):
            self.area = area
            self.ordinal = ordinal

    def __init__(self, ioport: mido.ports.IOPort):
        self._ioport = ioport

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
            yield from self.shift_button

    def reset(self):
        for b in self.all_buttons:
            self.set_button(b, ButtonState.OFF)
    
    def set_button(self, button: int, state: ButtonState):
        # there seems to be some limitation, be it in mido/rtmidi or in
        # the APC mini itself, that drops MIDI messages coming at a very
        # high rate
        self._send(mido.Message('note_on', note=button, velocity=state))
        self.light_state[button] = state
   
    def enable_events(self):
        self._ioport.input.callback = self._event_callback

    def disable_events(self):
        self._ioport.input.callback = None

    def id_to_fader(self, fader_id: int) -> int:
        return fader_id - self.FADER_OFFSET

    def id_to_button(self, button_id) -> ButtonID:
        if button_id > self.SHIFT_OFFSET:
            return None
        if button_id == self.SHIFT_OFFSET:
            return self.ButtonID(ButtonArea.SHIFT_BUTTON, 0)
        if button_id >= self.VERTICAL_OFFSET:
            return self.ButtonID(ButtonArea.VERTICAL, button_id - self.VERTICAL_OFFSET)
        if button_id >= self.HORIZONTAL_OFFSET:
            return self.ButtonID(ButtonArea.HORIZONTAL, button_id - self.HORIZONTAL_OFFSET)
        if button_id >= self.MATRIX_OFFSET:
            return self.ButtonID(ButtonArea.MATRIX, button_id - self.MATRIX_OFFSET)
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

    def get_area_light_state(self, area: ButtonArea) -> dict[int, ButtonState]:
        return { b:self.light_state[b] for b in self.get_area_buttons(area) }

    @classmethod
    def get_area_buttons(cls, area: ButtonArea) -> list[int]:
        return cls.area_buttons[area]

    def set_all_buttons(self, btn_map: dict[int, ButtonState]):
        for b,s in btn_map:
            self.set_button(b, s)


class SavedState:
    def __init__(self, light_map: dict[int, ButtonState]):
        self.light_map = light_map
    
    @classmethod
    def from_device(cls, apc: APCMini, area: ButtonArea):
        return cls(apc.get_area_light_state(area))

    @classmethod
    def make_blank(cls, area: ButtonArea):
        return cls({ btn:ButtonState.OFF for btn in APCMini.get_area_buttons(area) })

    def __iter__(self):
        return iter(self.light_map.items())

class AbstractAPCPlugin:
    def __init__(self, name: str):
        self.name = name
        self.set_button = None

    def on_register(self, setbtn_callback: function):
        self.set_button = setbtn_callback
    def on_unregister(self):
        self.set_button = None

    def on_activate(self):
        pass
    def on_deactivate(self):
        pass
    def on_btn_press(self, btn: APCMini.ButtonID):
        pass
    def on_btn_release(self, btn: APCMini.ButtonID):
        pass
    def on_fader_change(self, fader: int, value: float):
        pass

class APCMultiplexer:
    def __init__(self, apc: APCMini):
        self.apc = apc
        self.areas = {
            # faders are always bound to whoever has the horizontal buttons area
            ButtonArea.HORIZONTAL: deque(),
            ButtonArea.VERTICAL: deque(),
            ButtonArea.MATRIX: deque()
        }
        self.plugin_states = { area:dict() for area in self.areas.keys() }
        apc.disable_events()
        apc.reset()
        apc.cb_button_pressed = self._on_btn_press
        apc.cb_button_released = self._on_btn_release
        apc.cb_fader_value = self._on_fader_change
        apc.enable_events()

    def register(self, area: ButtonArea, plugin: AbstractAPCPlugin):
        assert plugin not in self.plugin_states[area].keys()
        plugin.on_register(lambda b, s: self._set_button(plugin, b, s))
        self.plugin_states[area][plugin] = SavedState.make_blank(area)
        self.areas[area].append(plugin)

    def unregister(self, area: ButtonArea, plugin: AbstractAPCPlugin):
        self.areas[area].remove(plugin)
        self.plugin_states[area].pop(plugin)
        plugin.on_unregister()

    def _set_button(self, caller: AbstractAPCPlugin, buttonID: int, state: ButtonState):
        area = self.apc.id_to_button(buttonID).area
        assert caller in self.plugin_states[area], "Plugin tried to write to button out of its scope"
        self.apc.set_button(buttonID, state)

    def next_scene(self, area: ButtonArea):
        area_plugins = self.areas[area]
        print("next", area_plugins)
        if len(area_plugins) > 1:
            area_state = SavedState.from_device(self.apc, area)
            active_plugin = area_plugins[0]
            self.plugin_states[area][active_plugin] = area_state
            active_plugin.on_deactivate()
            
            self.areas[area].rotate(1)
            next_plugin = area_plugins[0]
            next_area_state = self.plugin_states[area][next_plugin]
            self.apc.set_all_buttons(next_area_state)
            next_plugin.on_activate()
            print("Activated", next_plugin)
    
    def _on_btn_press(self, btn: APCMini.ButtonID):
        if btn.area == ButtonArea.SHIFT_BUTTON:
            self.next_scene(ButtonArea.MATRIX)
        else:
            if self.areas[btn.area]:
                self.areas[btn.area][0].on_btn_press(btn)

    def _on_btn_release(self, btn: APCMini.ButtonID):
        if btn.area != ButtonArea.SHIFT_BUTTON:
            if self.areas[btn.area]:
                self.areas[btn.area][0].on_btn_release(btn)

    def _on_fader_change(self, fader: int, value: float):
        if self.areas[ButtonArea.HORIZONTAL]:
            self.areas[ButtonArea.HORIZONTAL][0].on_fader_change(fader, value)

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

def test():
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

class DemoPlugin(AbstractAPCPlugin):
    def __init__(self, name: str):
        super().__init__(name)
        self.btn_state = {x:0 for x in range(64)}
    
    def __repr__(self):
        return self.name

    def on_btn_press(self, btn: APCMini.ButtonID):
        assert btn.area == ButtonArea.MATRIX
        # toggle green light on button that was pressed
        self.btn_state[btn.ordinal] = 1-self.btn_state[btn.ordinal]
        self.set_button(btn.ordinal, self.btn_state[btn.ordinal])

def test_plugins():
    with mido.open_ioport(APC_PORT) as midiport:
        apc = APCMini(midiport)
        mult = APCMultiplexer(apc)
        mult.register(ButtonArea.MATRIX, DemoPlugin("A"))
        mult.register(ButtonArea.MATRIX, DemoPlugin("B"))
        wait_keyboard_interrupt()

if __name__ == "__main__":
    test_plugins()