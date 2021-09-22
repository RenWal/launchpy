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
