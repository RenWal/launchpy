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

from time import sleep

import mido

from apc import APCMini, ButtonArea
from multiplexer import APCMultiplexer
from plugins.demo import DemoPlugin
from plugins.gnome import GnomeWorkspacePlugin
from plugins.pulse import PulsePlugin

APC_PORT = "APC MINI:APC MINI MIDI 1 20:0"

PLUGIN_REGISTRY = [
    (PulsePlugin, "Pulse mixer", ButtonArea.MATRIX | ButtonArea.HORIZONTAL),
    (GnomeWorkspacePlugin, "Gnome workspace switcher", ButtonArea.VERTICAL)
]

def wait_keyboard_interrupt():
    try:
        while 1:
            sleep(1)
    except KeyboardInterrupt:
        pass

def run_plugins():
    with mido.open_ioport(APC_PORT) as midiport:
        apc = APCMini(midiport)
        mult = APCMultiplexer(apc)
        for clazz, name, areas in PLUGIN_REGISTRY:
            plugin = clazz(name)
            mult.register(areas, plugin)
        wait_keyboard_interrupt()
        mult.shutdown()
        apc.reset()

if __name__ == "__main__":
    run_plugins()
