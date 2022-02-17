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

from threading import Thread
from time import sleep

from apc import APCMini, ButtonArea, ButtonID, ButtonState
from multiplexer import AbstractAPCPlugin, APCMiniProxy

# This code gives an introduction into writing your own plugins for
# LaunchPy. We assume that you have some Python knowledge already.
# It's best if you work through this from top to bottom. Step by step,
# this tutorial explains how to set plugin metadata used by the
# multiplexer, how the plugin livecycle (init - register - activate -
# deactivate - unregister - destroy) works, and what areas are. Then,
# we introduce button and fader events, or how to react to user input.
# You'll learn how to select and apply colors to buttons. Then, we'll
# briefly touch on some tips how to make your event handler code run
# smoothly. Afterwards, have a look at some more advanced API concepts if
# you like. If you're new to this, feel free to skip this section for
# now. Finally, we present a simple background task. With what you
# learned in this tutorial, you should be able to understand well what
# it does. It's a good place to start experimenting and extending this
# plugin to get a feel for how things work in practice!

class DemoPlugin(AbstractAPCPlugin):
    # Indicator for the multiplexer which areas of the APC you'll be
    # using. Your plugin can only access the specified areas.
    # You must specify HORIZONTAL if you need access to fader positions.
    areas = ButtonArea.MATRIX | ButtonArea.HORIZONTAL

    def __init__(self, name: str):
        super().__init__(name)
        self.stop = False
        self.runner = None

        self.colors = [ButtonState.GREEN]*8
        self.blink = False

    # overrides
    
    def on_register(self, apc_proxy: APCMiniProxy):
        # This MUST be first. DO NOT remove this line!
        super().on_register(apc_proxy)

        # Do whatever you need to do in order to make your plugin ready to be
        # used. Note that your plugin is not yet in the foreground (activated).

        # We'll start a simple background task. Work through the rest of this
        # tutorial IN ORDER before looking at the implementation of `light_me_up`.
        self.runner = Thread(target=self.light_me_up, name="Demo plugin runner")
        self.runner.start()
        print(f"{self.name} started up successfully")
    
    def on_unregister(self):
        # Release any resources you have acquired and make your plugin ready
        # to be destroyed. Your plugin will already be in the background, i.e.,
        # is deactivated.
        print(f"{self.name} is stopping")
        self.stop=True
        self.runner.join()
        
        # This MUST be last. DO NOT remove this line!
        super().on_unregister()

    def on_activate(self, area: ButtonArea):
        # This MUST be first. DO NOT remove this line!
        super().on_activate(area)

        # Your plugin has just received input focus on the given area. The user
        # can now interact with it. From now on, your plugin will receive button
        # presses and fader movements. Be aware that each area can have a
        # different plugin active!
        print(f"Hey there! {self.name} is now in the foreground on area {area.name}!")

    def on_deactivate(self, area: ButtonArea) -> None:
        # Your plugin has lost input focus on the given area. The user can no
        # longer interact with it and your plugin will not receive button presses
        # and fader movements. Note that you can still call `self.set_button` and
        # this will take effect the next time your plugin is activated.
        # You should consider stopping any resource-intensive tasks that are not
        # important while your plugin is in the background. Keep in mind to
        # resume them in `on_activate`!
        print(f"See you! {self.name} is no longer displaying on area {area.name}!")
        
        # This MUST be last. DO NOT remove this line!
        super().on_deactivate(area)

    def on_btn_press(self, btn: ButtonID):
        # Your plugin has just received a button press event. Note that there is
        # also a `on_btn_release` method. In this simple example, we don't go into
        # the details of `ButtonID` just yet.
        print(f"Button {btn} pressed")
        if btn.area == ButtonArea.MATRIX:
            # Get the current state of the LED of this button, rom the perspective
            # of this plugin (i.e., if your plugin is not in the foreground, you
            # can't use this to see what other plugins are doing)
            state = self.get_button(btn)
            # `toggle` returns the `OFF` state if `state` is some color. Otherwise,
            # meaning if the state *is* currently `OFF`, the specified color is
            # returned.
            state = state.toggle(self.colors[btn.matrix_coords[1]])
            # Set the LED state for this button
            self.set_button(btn, state)
        # We ignore all other areas here: Since we selected HORIZONTAL
        # as well at the top of this class, we'll also receive events for
        # the round buttons above the faders, but we don't care about them.

    def on_fader_change(self, fader: int, value: float, synthetic: bool = False) -> None:
        # A fader has just been moved. The faders are counted from left to
        # right, starting at 0. We call the fader below the SHIFT button on the
        # right the "master fader". That does not imply any functionality, it's
        # just shorter to say than "the fader that's below SHIFT".

        # The fader value ranges from 0 to 1 in 128 steps. Watch out: If a user
        # moves a fader very quickly, this method will be called 128 times in
        # a very short period of time! Therefore, this method should return
        # quickly. If you do resource-intensive things here anyway, you should
        # implement some logic to prevent overloading the CPU.

        # When your plugin is activated, you'll also instantly receive fader
        # events indicating the current position of all faders that have been
        # moved while your plugin was in the background. This allows you to
        # synchronize your plugin's internal state, if you need it. You can
        # recognize such events by the `synthetic` flag being set.

        # If your faders do semantically different things, it's good practice
        # to implement that functionality in sub-handlers.
        if fader == 8:
            self.handle_master_fader(value)
        else:
            self.handle_channel_faders(fader, value)

    # plugin logic

    def handle_channel_faders(self, fader: int, value: float) -> None:
        # More demo code! To experiment with some button states, let's set the
        # color of the buttons above each fader according to the fader's value.
        if value > 0.66:
            new_color = ButtonState.RED
        elif value > 0.33:
            new_color = ButtonState.YELLOW
        else:
            new_color = ButtonState.GREEN
        
        # launchpy won't send commands to the APC to change button color if the
        # new requested color is the same as the previously selected one. Still,
        # you should avoid hammering the `get_button` and `set_button` APIs.
        if new_color != self.colors[fader]:
            self.colors[fader] = new_color
            for i in range(8):
                # Construct an identifier for the button that we want to change.
                # For MATRIX buttons, you can use a tuple as the second argument,
                # which will then be interpreted as (column, row). For all others,
                # you just supply a single integer.
                btn = ButtonID(ButtonArea.MATRIX, (fader, i))
                # Only set the color if the LED is actually on, since this would
                # turn it on otherwise
                if self.get_button(btn) != ButtonState.OFF:
                    # `blink` is a convenience method that converts between the
                    # solid and blinking ButtonState.
                    self.set_button(btn, self.colors[fader].blink(self.blink))

        # Even more demo code! We also want to make the round button above the
        # fader blink if we move the fader close to its maximum.
        new_fader_state = ButtonState.BLINK if (value > 0.95) else ButtonState.OFF
        # Here, you can see how we create a ButtonID for a HORIZONTAL button. Note
        # that we don't use a tuple but a simple integer as the second argument.
        if self.get_button(ButtonID(ButtonArea.HORIZONTAL, fader)) != new_fader_state:
            self.set_button(ButtonID(ButtonArea.HORIZONTAL, fader), new_fader_state)


    def handle_master_fader(self, value: float) -> None:
        # And more demo code! Here, we want to have all buttons appear solid
        # if the master fader value is at most 0.5, and have them blink otherwise.
        should_blink = (value > 0.5)
        
        # Again, this method can be called A LOT! Since the loop below hits
        # the `set_button` call 64 times, you should only run it if needed
        # and exit early otherwise.
        if self.blink == should_blink: return
        self.blink = should_blink
        
        for row in range(8):
            for col in range(8):
                btn = ButtonID(ButtonArea.MATRIX, (col, row))
                # The tuple above is equivalent to this:
                #   btn = ButtonID(ButtonArea.MATRIX, col + 8*row)
                
                # ADVANCED STUFF, YOU CAN SKIP THIS:
                # For the `get_button` and `set_button` API, you can even
                # just supply an integer directly, if you so desire:
                #   btn = APCMini.MATRIX_OFFSET + col + 8*row
                # This integer then refers to the numeric index of the
                # button as specified in Akai's protocol. We call this a
                # raw index. There is also a way to convert from the raw
                # index to the ButtonID representation ...:
                #   btn = ButtonID.from_idx(APCMini.MATRIX_OFFSET + col + 8*row)
                # ... and back:
                #   idx = btn.to_idx()
                if self.get_button(btn) != ButtonState.OFF:
                    self.set_button(btn, self.colors[col].blink(self.blink))

    # threads

    def light_me_up(self):
        # A simple demo for a possible background task. Each second, we toggle
        # the LED on one button on the button matrix. You see, not all button
        # color changes need to be the result of a user interaction!
        while not self.stop:
            for i in range(APCMini.N_MATRIX):
                if self.stop: break
                btn = ButtonID(ButtonArea.MATRIX, i)
                state = self.get_button(btn)
                state = state.toggle(self.colors[i%8].blink(self.blink))
                self.set_button(btn, state)
                sleep(1)
