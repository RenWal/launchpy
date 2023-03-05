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

from mido import Message, open_ioport
from mido.ports import IOPort

from apc import APCMini, ButtonArea, ButtonID
from multiplexer import AbstractAPCPlugin, APCMiniProxy

# Provides a virtual MIDI port to talk to the APC Mini.
# This can be useful if you want to multiplex the APC to multiple softwares,
# (for this, just instantiate this plugin multiple times with different names,
# each will give you one virtual MIDI port)
# or if you want to run LaunchPy plugins in parallel with a MIDI software.
# You could also use this to write external plugins in a language of your choice,
# which then interact with LaunchPy through pure MIDI.
# Please note that the SHIFT key is not passed through, since it's used to switch
# between plugins in the multiplexer.
class MidiPassthroughPlugin(AbstractAPCPlugin):
    areas = ButtonArea.MATRIX | ButtonArea.HORIZONTAL | ButtonArea.VERTICAL

    def __init__(self, name: str):
        super().__init__(name)
        self.port = None

    def on_register(self, apc_proxy: APCMiniProxy):
        super().on_register(apc_proxy)

        self.port : IOPort = open_ioport(name=self.name, virtual=True)
        self.port.input.callback = self.handle_message
    
    def on_unregister(self):
        self.port.input.callback = None
        
        super().on_unregister()
    
    # forward hardware events to the virtual MIDI port

    def on_btn_press(self, btn: ButtonID):
        btn_idx = btn.to_idx()
        msg = Message("note_on", note=btn_idx)
        self.port.send(msg)
    
    def on_btn_release(self, btn: ButtonID):
        btn_idx = btn.to_idx()
        msg = Message("note_off", note=btn_idx)
        self.port.send(msg)

    def on_fader_change(self, fader: int, value: float, synthetic: bool = False) -> None:
        f_idx = APCMini.fader_to_id(fader)
        value_i = int(value*127)
        msg = Message("control_change", control=f_idx, value=value_i)
        self.port.send(msg)

    # forward messages from the virtual MIDI port to the hardware
    def handle_message(self, msg):
        if msg.type == "note_on":
            btn_idx = msg.note
            if ButtonID.idx_valid(btn_idx):
                state = msg.velocity
                self.set_button(btn_idx, state)
            else:
                print("Received out-of-range note, dropping:", msg)    
        else:
            print("Received unsupported MIDI message, dropping:", msg)
