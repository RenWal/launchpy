# configure your LaunchPy instance here
from apc import ButtonArea
from plugins.pulse import PlacementMode
import re

# set None to attempt auto-discovery
# you only need to set this explicitly if you have connected more than one APC Mini
# APC_PORT = "APC MINI:APC MINI MIDI 1 20:0"
APC_PORT = None

PLUGINS = [
    ("plugins.pulse.PulsePlugin", "Pulse mixer", ButtonArea.MATRIX | ButtonArea.HORIZONTAL),
    ("plugins.gnome.GnomeWorkspacePlugin", "Gnome workspace switcher", ButtonArea.VERTICAL),
    #("plugins.demo.DemoPlugin", "Demo plugin", ButtonArea.MATRIX | ButtonArea.HORIZONTAL),
]

# "False" will assign the faders right-to left (useful if you have the APC to the
# left of your keyboard)
PULSE_SORT_REVERSE = False

PULSE_PLACEMENT_MODE = PlacementMode.FILL

# ignore-lists for sinks, and application names of sink inputs
# (entries can be strings or compiled regex patterns)
PULSE_IGNORE_SINKS = [
    "PulseEffects(mic)",
]
PULSE_IGNORE_STREAMS = [
    re.compile("^speech-dispatcher-.+"),
]