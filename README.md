# launchpy
Some python stuff to interface with the Akai APC mini launchpad

# What's this?
The APC mini is actually a controller for the Ableton Live software. However, I reckon it can be used for many more things. Unfortunately, I could not yet find a nice abstraction layer that gives me object-oriented access to the device, rather than manually interacting with raw MIDI ports. This repo is a work in progress on filling that gap.

# Why did you make this?
I found myself stuck at home and figured that my home office setup just hasn't got enough macro keys. Also, physical volume sliders for PulseAudio are pretty nice, so I can switch between video calls more swiftly when I need to attend more than one call at once. (The code for this is not released yet, but it's really quite easy to get working using the `pulsectl` module)

# Where do I find more details on the APC?
Here's a chart of the button mapping:
https://github.com/TomasHubelbauer/akai-apc-mini
This person used raw USB messages to interact with the APC mini, which I think is not necessary since the device speaks mostly standard MIDI, and Python can handle that pretty well. However, the button mapping is still correct and helped me develop this a lot.
