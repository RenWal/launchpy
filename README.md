# launchpy
Some python stuff to interface with the Akai APC mini launchpad, and some plugins for controlling PulseAudio and Gnome workspaces using the APC

## What's this?
The APC mini is actually a controller for the Ableton Live software. However, I reckon it can be used for many more things. Unfortunately, I could not yet find a nice abstraction layer that gives me object-oriented access to the device and plugin support, rather than manually interacting with raw MIDI ports. This repo is a work in progress on filling that gap.

## I just want to run your plugins!
Head over to [INSTALL.md](./INSTALL.md) and follow the instructions. That will get you set up with LaunchPy and all the default plugins.

If you want to develop your own stuff or you're simply curious about the details of this implementation, keep reading here.

## How does this thing work?
There are multiple abstraction layers in this toolset. Which one you use depends on the complexity of your project.

### APCMini
Let's start at the bottom, in `apc.py`. Here, we find the basic hardware abstraction layer. This class knows how an APC Mini looks (what buttons does it have in which area, how do the lights and faders work, …) and how to interact with it using raw MIDI. It then allows you to manipulate the LED behind each button and provides callbacks for when a button is pressed, when it is released, and when a fader is moved.

For easy access to buttons, the APCMini class splits the hardware's layout into three ButtonAreas: The MATRIX represents the 8x8 button grid. The HORIZONTAL area consists of the horizontal row of round buttons and the faders. The VERTICAL area consists of the vertical row of round buttons on the right. Finally, there is the SHIFT_BUTTON area that just consists of the square SHIFT button in the lower right corner.

If you just want to build a simple application, take only this and implement a program that creates an APCMini instance and interacts with it.

### APCMultiplexer and AbstractAPCPlugin
For more convenience, we can also put a plugin layer on top of the bare APCMini. All of it is defined in `multiplexer.py`. This layer allows us to have multiple pieces of code bound to the same APC hardware. For granular control, the multiplexer treats the APC's three zones (see above) separately.

On the one hand, this allows you to better encapsulate different functionalities: In my use case, I use the button matrix, the horizontal row of round buttons plus the faders to control my PulseAudio mixer, while the vertical row of round buttons controls my Gnome desktop. Using the plugin system, I can create two plugins (see `plugins/gnome.py` and `plugins/pulse.py`) and tell the multiplexer to give them access to only those sections. The two plugins then run side-by-side.

On the other hand, you can use this to create multiple views: For example, I mainly use the PulseAudio mixer on the APC, but I can switch the button matrix to another plugin that allows me to control all (well, most of) the things in my smart home. This is essentially done using APCMiniProxy: The multiplexer automatically creates one proxy for each AbstractAPCPlugin. Each plugin interacts with its proxy like it would with the real APC. A plugin does not have to care about whether it is currently in the foreground or not. It can control its proxy at any point in time. When the multiplexer wants a plugin to come to the foreground, i.e., control the physical lights and receive button/fader events, then the multiplexer just "connects" and synchronizes that proxy to the APCMini (and "disconnects" the previous one).

Again, the three zones are treated individually. In my use case, I can switch the button matrix between the Pulse mixer and my smart home controller, while the faders always stay connected to the Pulse mixer. To cycle through the available plugins for a zone, press and hold the SHIFT button on the APC, then tap any button in that zone.

### The plugins

#### Demo Plugin
This plugin lets you play around with the lights on the APC buttons. If you want to write your own plugins, this is also the place to get you started. The plugin's code at `plugins/demo.py` contains a tutorial that explains the plugin API and some details of the capabilities of the APC.

If you want to dig deeper, look at the methods that `AbstractAPCPlugin` provides.

#### Gnome Workspace Plugin
This is a simple plugin that uses Gnome's DBus interface to switch between different workspaces using the vertical buttons on the APC. It doesn't currently update the lights on the APC though if you switch the workspace directly in Gnome. Any ideas on how to do this are welcome!

#### Pulse Plugin
Using this plugin, you can control at most 8 PulseAudio streams to at most 5 sinks/output devices at the same time. Unless you regularly exceed those limits, no configuration is required. Just start the plugin and it will pick up any new streams.

I will not go into the details of how everything in this plugin works here, but here's how the UI works:
When a stream starts playing, a bunch of buttons light up above a fader. This fader now controls the volume of that stream. The round button directly above the fader controls its mute status. If you press the button, the stream will be (un-)muted. While the stream is muted, the button flashes red.

The two buttons above that control audio balance on stereo streams. If both buttons are green, the audio levels of both channels are equal. Press the upper button once to reduce the volume on the left channel. Press again to mute the left channel. The lower button does the opposite.<br>
On mono streams, only a single button is lit. Pressing it does nothing.

Going further up, the buttons 4 to 8 in the column control the output assignment. For each output available on your system, a button lights up. The output that the stream is currently playing to is marked green. Available outputs are marked yellow. Muted outputs are marked red. If you press any of these buttons, this will move the stream to that output. (If you move your playback to a muted output, the respective button will start flashing red.)

The button lights will also react to changes you or some other software make directly in PulseAudio. For example, if you mute a stream or an output device, the mute and output buttons will blink and change color accordingly.<br>
If you change the volume of a stream, the plugin will _not_ try to revert this to the physical fader's setting. This is to prevent this plugin to start fighthing over the audio controls with other software (such as Mumble, which will try to reduce the volume on your media playback while someone is talking).<br>
To indicate to you that this has happened, the to audio balance buttons for that fader will start flashing. To reset the volume, either tap one of these buttons or just gently wiggle the fader.

With the basics out of the way, here's one more thing for people (like me) who like to customize everything: If you want to move a stream to a different fader, press and hold its mute button (the round one above the current fader) and then tap the mute button on the fader you'd like to move it to.

Finally, there is one "secret button": In each column, the third rectangular button from the bottom, serves as an eject button. Press it and the fader will be freed. While mostly used for development purposes, you can use this if there are some streams on your system that you don't want to control from your APC.

## Why did you make this?
I found myself stuck at home and figured that my home office setup just hasn't got enough macro keys. Also, physical volume sliders for PulseAudio are pretty nice, so I can switch between video calls more swiftly when I need to attend more than one call at once. (Just things that tend to happen when you develop online seminar software …)

## TODOs
- Find out how to read the fader positions on startup. Right now you need to wiggle each slider such that launchpy learns its value through MIDI events. That's a little annoying. (_If anyone knows and wants to share the exact protocol in use here -- Ableton seems to be sending some proprietary messages -- I'd be very happy to hear from you_)

(This is strictly a hobby / free time project. Stuff will happen as I find time for it.)

## Where do I find more details on the APC?
Here's a chart of the button mapping:
https://github.com/TomasHubelbauer/akai-apc-mini
This person used raw USB messages to interact with the APC mini, which I think is not necessary since the device speaks mostly standard MIDI, and Python can handle that pretty well. However, the button mapping is still correct and helped me develop this a lot.

---

This software is licensed under the [GNU General Public License, Version 3](./LICENSE).
