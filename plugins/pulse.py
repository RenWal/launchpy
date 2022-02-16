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

import threading
import traceback
from enum import Enum, IntEnum, IntFlag, auto
from operator import neg
from queue import SimpleQueue
from time import time

import pulsectl
from apc import APCMini, ButtonArea, ButtonID, ButtonState
from multiplexer import AbstractAPCPlugin, APCMiniProxy
from pulsectl.pulsectl import PulseIndexError
from sortedcontainers import SortedDict, SortedSet


class Balance(IntEnum):
    FULL_LEFT = -2
    BIAS_LEFT = -1
    CENTER = 0
    BIAS_RIGHT = 1
    FULL_RIGHT = 2

class Fader:
    def __init__(self, index: int, stream: int, sink: int, sink_id: int, channels: int, \
        volume: float = 0, muted: bool = False, balance: Balance = Balance.CENTER) -> None:
        self.index = index
        self.stream = stream
        self.sink = sink
        self.sink_id = sink_id
        self.channels = channels
        self.volume = volume
        self.volume_desync = False # flag for when the HW fader does no longer match the SW fader (because something else changed the volume in Pulse)
        self.muted = muted
        self.balance = balance

    def __str__(self) -> str:
        return f"Fader {self.index} -> {self.stream} ({self.channels}CH, {self.volume})"

# Keeps track of the faders currently bound to Pulse streams and controls the order
# in which faders are assigned. The fader below the SHIFT button is not used, since
# it does not have the rectangular button column above it.
# One can extend PhysicalMixer to make this fader do something useful, like
# controlling your microphone volume.
class FaderPool:

    class AllocMode(Enum):
        # keep adding faders at the end of the deck, only fill gaps
        # when no space at the end
        APPEND = auto()
        # insert fader at first free position at the beginning
        FILL = auto()

        # note that "beginning" = right and "end" = left unless you set
        # sort_reverse below

    def __init__(self) -> None:
        # "False" will assign the faders right-to left (useful if you have the APC to the
        # left of your keyboard)
        self.sort_reverse = False
        self.alloc_mode = self.AllocMode.FILL
        
        if self.sort_reverse:
            self.free = SortedSet(range(APCMini.N_FADERS-1), key=neg)
            self.used = SortedDict(neg)
        else:
            self.free = SortedSet(range(APCMini.N_FADERS-1)) # don't use the master fader
            self.used = SortedDict()
        
        self.last_released = (None, 0)
        self.used = dict()
        self.stream_map = dict()
        self.sinks = []

    # picks the next free physical fader, maps it to the stream and returns the
    # fader instance reflecting it
    def acquire(self, stream_index: int, sink: int, sink_id: int, channels: int, muted: bool) -> Fader:
        if not self.free:
            return None

        free_index = None
        if self.last_released[0] is not None:
            # hack to not reset the position of a fader that briefly disappeared
            # (some browser-based media players do this whenever the next song starts)
            delta = time() - self.last_released[1]
            if delta < 2:
                free_index = self.last_released[0]
                self.free.remove(free_index)
                self.last_released = (None, 0)
        if free_index is None:
            free_index = self._get_next_free()
        if free_index is None:
            return None

        fader = Fader(free_index, stream_index, sink, sink_id, channels, muted=muted)
        self.used[free_index] = fader
        self.stream_map[stream_index] = fader
        return fader

    def _get_next_free(self):
        if self.alloc_mode == self.AllocMode.APPEND:
            step = 1 if self.sort_reverse else -1
            for i in self.used:
                print(i)
                next_index = i+step
                if next_index in self.free:
                    print("hit")
                    break
            else:
                next_index = 0 if self.sort_reverse else (APCMini.N_FADERS-2)
            self.free.remove(next_index)
            return next_index
        elif self.alloc_mode == self.AllocMode.FILL:
            return self.free.pop()

        # you can override this to design custom fader selection logic
        return None

    def for_stream(self, stream_index: int) -> Fader:
        return self.stream_map.get(stream_index)

    def at(self, fader_index: int) -> Fader:
        return self.used.get(fader_index)

    def get_used_faders(self) -> list[Fader]:
        return list(self.used.values())

    def is_used(self, fader_index: int) -> bool:
        return fader_index in self.used

    def swap(self, source_index: int, target_index: int) -> None:
        source_fader = self.at(source_index)
        target_fader = self.at(target_index)
        if source_fader is None or target_fader is None:
            raise Exception("Both indices need to be occupied")
        self.used[source_index] = target_fader
        self.used[target_index] = source_fader
        source_fader.index = target_index
        target_fader.index = source_index

    def move(self, source_index: int, target_index: int) -> None:
        if self.is_used(target_index):
            raise Exception("Can't move to occupied fader index")
        fader = self.at(source_index)
        if fader is None:
            raise Exception("Can't move from unoccupied fader index")
        self.used.pop(source_index)
        self.used[target_index] = fader
        self.free.add(source_index)
        self.free.remove(target_index)
        fader.index = target_index

    # un-maps the fader from the stream and frees the physical fader
    def release(self, fader: Fader) -> None:
        self.stream_map.pop(fader.stream)
        self.used.pop(fader.index)
        self.free.add(fader.index)
        self.last_released = (fader.index, time())

# Defines what each of the physical buttons and faders do. This class translates
# button presses and fader movements into useful events to control the Pulse
# software mixer, and translates changes to the Pulse sinks and streams into
# light states for the illuminated buttons.
class PhysicalMixer:

    MAX_SINK_BTNS = 5

    class Area(IntFlag):
        MUTE    = 0b001
        BALANCE = 0b010
        SINK    = 0b100
        ALL     = 0b111

    class MixerEventType(Enum):
        FADER_MOVE = auto()
        FADER_EJECT = auto()
        FADER_REMAP = auto()
        FADER_MUTE = auto()
        FADER_SINK = auto()
        FADER_BALANCE = auto()

    class MixerEvent:
        def __init__(self, etype, index: int, value = None):
            self.type = etype
            self.index = index
            self.value = value
        
        def __str__(self) -> str:
            return f"MixerEvent/{self.type.name} on {self.index} [{self.value}]"

    def __init__(self, apc_proxy: APCMiniProxy, event_queue: SimpleQueue) -> None:
        self.apc_proxy = apc_proxy
        self.event_queue = event_queue
        self.sink_mute_flags = []
        self.sink_count = 0
        self.remap_source = None
        self.ignore_release = set()

    def _submit(self, event: MixerEvent):
        self.event_queue.put_nowait(event)

    def set_sinks(self, sink_flags: list[bool]) -> None:
        self.sink_mute_flags = sink_flags * 1 # clone
        self.sink_count = len(sink_flags)

    ### software -> hardware ###

    # sets the colors of the buttons above that fader according to
    # what the stream is doing (i.e., its sink selection and mute status)
    def sync_buttons(self, fader: Fader, areas = None) -> None:
        if areas is None:
            areas = self.Area.ALL

        if areas & self.Area.BALANCE:
            blink = 1 if fader.volume_desync else 0 # adds 1 to the button state, which will cause the button to blink
            if fader.channels != 2:
                self.apc_proxy.set_button(APCMini.MATRIX_OFFSET+fader.index, ButtonState.GREEN+blink)
                self.apc_proxy.set_button(APCMini.MATRIX_OFFSET+fader.index+8, ButtonState.OFF)
            else:
                bal = fader.balance
                if bal == Balance.CENTER:
                    colors = [ButtonState.GREEN]*2
                else:
                    colors = [ButtonState.GREEN, ButtonState.YELLOW if abs(bal) == 1 else ButtonState.RED]
                    if bal < 0:
                        colors = reversed(colors)
                for i,c in enumerate(colors):
                        self.apc_proxy.set_button(APCMini.MATRIX_OFFSET+fader.index+8*i, c+blink)

        if areas & self.Area.SINK:
            for i in range(min(self.MAX_SINK_BTNS, self.sink_count)):
                btn_id = 8*(i+3)+fader.index # leave 3 rows at the bottom free
                is_assigned = (i == fader.sink)
                if is_assigned:
                    self.apc_proxy.set_button(APCMini.MATRIX_OFFSET+btn_id, ButtonState.RED_BLINK if self.sink_mute_flags[i] else ButtonState.GREEN)
                else:
                    self.apc_proxy.set_button(APCMini.MATRIX_OFFSET+btn_id, ButtonState.RED if self.sink_mute_flags[i] else ButtonState.YELLOW)
            for i in range(self.sink_count, self.MAX_SINK_BTNS):
                btn_id = 8*(i+3)+fader.index
                self.apc_proxy.set_button(APCMini.MATRIX_OFFSET+btn_id, ButtonState.OFF)
                
        if areas & self.Area.MUTE:
            self.apc_proxy.set_button(APCMini.HORIZONTAL_OFFSET+fader.index, ButtonState.BLINK if fader.muted else ButtonState.ON)

    def clear_buttons(self, fader: Fader) -> None:
        for i in range(8):
            btn_id = 8*i+fader.index
            self.apc_proxy.set_button(APCMini.MATRIX_OFFSET+btn_id, ButtonState.OFF)
        self.apc_proxy.set_button(APCMini.HORIZONTAL_OFFSET+fader.index, ButtonState.OFF)

    ### hardware -> software ###

    def get_fader_position(self, fader_index: int) -> float:
        phys_position = self.apc_proxy.faders[fader_index]
        if phys_position is None:
            phys_position = 0
        return phys_position

    def on_fader_change(self, fader_index, value):
        self._submit(self.MixerEvent(self.MixerEventType.FADER_MOVE, fader_index, value=value))

    def on_btn_press(self, btn):
        if btn.area == ButtonArea.MATRIX:
            (row, col) = divmod(btn.ordinal, 8)
            if row == 2: # 3rd lowest button in column
                self.apc_proxy.set_button(APCMini.MATRIX_OFFSET+btn.ordinal, ButtonState.RED)
        elif btn.area == ButtonArea.HORIZONTAL:
            if self.remap_source is None:
                self.remap_source = btn
            else:
                self._submit(self.MixerEvent(self.MixerEventType.FADER_REMAP, btn.ordinal, value=self.remap_source.ordinal))
                self.ignore_release.add(btn)
                self.ignore_release.add(self.remap_source)
                self.remap_source = None

    def on_btn_release(self, btn):
        if btn.area == ButtonArea.MATRIX:
            (row, col) = divmod(btn.ordinal, 8)
            if row < 2:
                direction = (row == 1)
                self._submit(self.MixerEvent(self.MixerEventType.FADER_BALANCE, col, value=direction))
            elif row == 2: # eject button (3rd lowest button in column)
                self._submit(self.MixerEvent(self.MixerEventType.FADER_EJECT, col))
            elif row >= 3: # sink select buttons (topmost 5 buttons in column)
                sink = row-3
                if sink > self.sink_count-1:
                    return
                self._submit(self.MixerEvent(self.MixerEventType.FADER_SINK, col, value=sink))
        elif btn.area == ButtonArea.HORIZONTAL:
            if self.remap_source == btn:
                self.remap_source = None
            if btn in self.ignore_release:
                self.ignore_release.remove(btn)
                return
            self._submit(self.MixerEvent(self.MixerEventType.FADER_MUTE, btn.ordinal))

# Workaround to properly fetch all events from Pulse without
# having long-running Pulse callbacks (Note that two Pulse
# instances are required in this plugin, where the EventLoop
# has one to issue commands to Pulse and the PulseWatcher
# has one to receive events. Both are, by design of pulsectl,
# mutually exclusive on a single instance, and exiting the
# event listener to execute a command will lead to lost events
# and hence inconsistent state.)
class PulseWatcher(threading.Thread):
    def __init__(self, event_queue) -> None:
        super().__init__(name="Pulse event watcher")
        self.event_queue = event_queue
    
    def _on_pulse_event(self, e):
        self.event_queue.put_nowait(e)

    def end(self) -> None:
        if self.pulse is not None:
            self.pulse.event_listen_stop()
        self.join()

    def run(self) -> None:
        with pulsectl.Pulse() as pulse:
            self.pulse = pulse
            pulse.event_mask_set('sink_input', 'sink', 'source') 
            pulse.event_callback_set(self._on_pulse_event)
            pulse.event_listen()
            self.pulse = None
        self.event_queue.put(None) # termination signal to consumer

# Receives events from Pulse and from the APC and generates inputs
# to the PhysicalMixer and to Pulse accordingly. Using the common event
# queue, this serves as the central synchronization point.
class EventLoop(threading.Thread):

    def __init__(self, event_queue: SimpleQueue, fader_pool: FaderPool, pulse: pulsectl.Pulse, physical_mixer: PhysicalMixer) -> None:
        super().__init__(name="PulseMixer event loop")
        self.sinks = []
        self.sinks_muted = []
        self.mic_sources = []
        self.event_queue = event_queue
        self.fader_pool = fader_pool
        self.pulse = pulse
        self.physical_mixer = physical_mixer
        self.physical_mixer.set_sinks(self.sinks_muted)
        self.reload_sinks()
        self.reload_mic()

    @staticmethod
    def _calc_volume(fader: Fader) -> list[float]:
        value = fader.volume
        bal = fader.balance
        chans = fader.channels
        if chans == 2 and bal != 0:
            attenuation = (0.5 if abs(bal) == 1 else 0)
            vals = [attenuation*value, value]
            if bal < 0:
                vals = list(reversed(vals))
        else:
            vals = [value]*chans
        return vals
    
    @classmethod
    def _make_volume_object(cls, fader: Fader) -> pulsectl.PulseVolumeInfo:
        vals = cls._calc_volume(fader)
        return pulsectl.PulseVolumeInfo(vals, 1)

    def reload_sink_mute(self, sink_id: int) -> None:
        try:
            pulse_sink = self.pulse.sink_info(sink_id)
        except PulseIndexError:
            return
        try:
            sink_index = self.sinks.index(sink_id)
        except ValueError:
            return # we're not displaying that sink
        self.sinks_muted[sink_index] = pulse_sink.mute
        self.physical_mixer.set_sinks(self.sinks_muted)
        for fader in self.fader_pool.get_used_faders():
            self.physical_mixer.sync_buttons(fader, areas=self.physical_mixer.Area.SINK)
    
    def reload_sinks(self) -> None:
        print("reloading sinks")
        pulse_sinks = sorted(self.pulse.sink_list(), key=lambda psi: psi.description)
        self.sinks = [s.index for s in pulse_sinks]
        self.sinks_muted = [s.mute for s in pulse_sinks]
        self.physical_mixer.set_sinks(self.sinks_muted)
        for fader in self.fader_pool.get_used_faders():
            # HACK: Since in the fader we only save the sink index, i.e. the index into our
            # self.sinks, we need to update this by comparing the old and new sink lists.
            try:
                new_sink = self.sinks.index(fader.sink_id)
            except ValueError:
                new_sink = None
            fader.sink = new_sink
            self.physical_mixer.sync_buttons(fader, areas=self.physical_mixer.Area.SINK)

    def reload_mic(self) -> None:
        print("reloading mic source")
        pulse_sources = filter(lambda psi: psi.monitor_of_sink == 0xffffffff, self.pulse.source_list()) # without monitors
        self.mic_sources = [s.index for s in pulse_sources]
    
    # TODO deduplicate all of the "if fader is None" stubs

    def bind_fader(self, stream_index: int) -> None:
        try:
            input_info = self.pulse.sink_input_info(stream_index)
        except pulsectl.PulseIndexError:
            return # rare case where stream is gone before we get to process it
        sink_index = self.sinks.index(input_info.sink)
        fader = self.fader_pool.acquire(stream_index, sink_index, input_info.sink, \
            input_info.channel_count, input_info.mute)
        if fader is None:
            return # no more free faders
        self.physical_mixer.sync_buttons(fader)
        volume = self.physical_mixer.get_fader_position(fader.index)
        fader.volume = volume
        # force Pulse's stream volume to match the physical fader's position
        pulse_volume = self._make_volume_object(fader)
        try:
            self.pulse.sink_input_volume_set(stream_index, pulse_volume)
        except pulsectl.PulseOperationFailed:
            pass

    # reflect a change made using the software mixer to the hardware
    # (e.g., when you mute a stream using pavucontrol, the mute button
    # above the affected fader on the APC needs to start flashing)
    def refresh_fader(self, stream_index: int) -> None:
        fader = self.fader_pool.for_stream(stream_index)
        if fader is None:
            return # fader not mapped
        try:
            input_info = self.pulse.sink_input_info(stream_index)
        except pulsectl.PulseIndexError:
            return # rare case where stream is gone before we get to process it
        sink_index = self.sinks.index(input_info.sink)
        
        vol = input_info.volume.values
        vol_expect = self._calc_volume(fader)
        fader.volume_desync = (sum(abs(a-b) for a,b in zip(vol, vol_expect)) > 0.01)

        fader.sink_id = input_info.sink
        fader.sink = sink_index
        fader.muted = input_info.mute
        
        self.physical_mixer.sync_buttons(fader)
    
    def release_fader(self, stream_index: int) -> None:
        fader = self.fader_pool.for_stream(stream_index)
        if fader is None:
            return # stream had no fader (old streams, ejected, overflowed)
        self.physical_mixer.clear_buttons(fader)
        self.fader_pool.release(fader)

    def handle_pulse(self, e: pulsectl.PulseEventInfo) -> None:
        if e.facility == pulsectl.PulseEventMaskEnum.sink:
            if e.t in [pulsectl.PulseEventTypeEnum.new, pulsectl.PulseEventTypeEnum.remove]:
                self.reload_sinks()
            elif e.t == pulsectl.PulseEventTypeEnum.change:
                self.reload_sink_mute(e.index)
        elif e.facility == pulsectl.PulseEventMaskEnum.sink_input:
            if e.t == pulsectl.PulseEventTypeEnum.new:
                self.bind_fader(e.index)
            elif e.t == pulsectl.PulseEventTypeEnum.remove:
                self.release_fader(e.index)
            elif e.t == pulsectl.PulseEventTypeEnum.change:
                self.refresh_fader(e.index)
        elif e.facility == pulsectl.PulseEventMaskEnum.source:
            if e.t in [pulsectl.PulseEventTypeEnum.new, pulsectl.PulseEventTypeEnum.remove]:
                self.reload_mic()
                # force Pulse's stream volume to match the physical fader's position
                volume = self.physical_mixer.get_fader_position(APCMini.N_FADERS-1)
                self.update_volume(APCMini.N_FADERS-1, volume)


    def update_volume(self, fader_index: int, volume: float = None) -> None:
        if fader_index == APCMini.N_FADERS-1: # rightmost fader is mic fader
            vol = pulsectl.PulseVolumeInfo(volume, 1)
            for s in self.mic_sources:
                try:
                    self.pulse.source_volume_set(s, vol)
                except PulseIndexError:
                    return
        else:
            fader = self.fader_pool.at(fader_index)
            if fader is None: # physical fader not mapped
                return
            if volume is not None:
                fader.volume = volume
            pulse_volume = self._make_volume_object(fader)
            try:
                self.pulse.sink_input_volume_set(fader.stream, pulse_volume)
            except pulsectl.PulseOperationFailed:
                pass

    def toggle_mute(self, fader_index: int) -> None:
        fader = self.fader_pool.at(fader_index)
        if fader is None: # physical fader not mapped
            return
        fader.muted = not fader.muted
        try:
            self.pulse.sink_input_mute(fader.stream, fader.muted)
        except pulsectl.PulseOperationFailed:
            pass
        self.physical_mixer.sync_buttons(fader, areas=self.physical_mixer.Area.MUTE)

    def remap_faders(self, target: int, source: int) -> None:
        target_fader = self.fader_pool.at(target)
        source_fader = self.fader_pool.at(source)
        if source_fader is not None:
            if target_fader is not None:
                self.fader_pool.swap(source, target)
                source_fader.volume = self.physical_mixer.get_fader_position(target)
                target_fader.volume = self.physical_mixer.get_fader_position(source)
                self.physical_mixer.sync_buttons(source_fader)
                self.physical_mixer.sync_buttons(target_fader)
                self.update_volume(source)
                self.update_volume(target)
            else:
                self.physical_mixer.clear_buttons(source_fader)
                self.fader_pool.move(source, target)
                self.physical_mixer.sync_buttons(source_fader) # fader has updated index here
                source_fader.volume = self.physical_mixer.get_fader_position(target)
                self.update_volume(target)
        # else ignore

    def switch_sink(self, fader_index: int, sink_index: int) -> None:
        fader = self.fader_pool.at(fader_index)
        if fader is None: # physical fader not mapped
            return
        fader.sink = sink_index
        sink = self.sinks[sink_index]
        fader.sink_id = sink
        try:
            self.pulse.sink_input_move(fader.stream, sink)
        except pulsectl.PulseOperationFailed:
            return
        self.physical_mixer.sync_buttons(fader, self.physical_mixer.Area.SINK)

    def sub_handle_balance(self, fader_index: int, direction: bool) -> None:
        fader = self.fader_pool.at(fader_index)
        if fader is None: # physical fader not mapped
            return
        # upper button only allowed for stereo streams
        if not direction or fader.channels == 2:
            if fader.volume_desync:
                    self.update_volume(fader_index) # re-sync
            else:
                self.change_balance(fader, direction)

    def change_balance(self, fader: Fader, direction: bool) -> None:
        bal = fader.balance
        if direction:
            if bal == Balance.FULL_RIGHT:
                bal = Balance.CENTER
            else:
                bal+=1
        else:
            if bal == Balance.FULL_LEFT:
                bal = Balance.CENTER
            else:
                bal-=1
        fader.balance = bal

        pulse_volume = self._make_volume_object(fader)
        try:
            self.pulse.sink_input_volume_set(fader.stream, pulse_volume)
        except pulsectl.PulseOperationFailed:
            return
        self.physical_mixer.sync_buttons(fader, areas=self.physical_mixer.Area.BALANCE)

    # TODO deduplicate with release_fader
    def eject_fader(self, fader_index: int) -> None:
        fader = self.fader_pool.at(fader_index)
        if fader is None:
            return # stream had no fader (old streams, ejected, overflowed)
        self.physical_mixer.clear_buttons(fader)
        self.fader_pool.release(fader)

    def handle_apc(self, e: PhysicalMixer.MixerEvent) -> None:
        t = e.type
        if t == self.physical_mixer.MixerEventType.FADER_MOVE:
            self.update_volume(e.index, e.value)
        elif t == self.physical_mixer.MixerEventType.FADER_MUTE:
            self.toggle_mute(e.index)
        elif t == self.physical_mixer.MixerEventType.FADER_BALANCE:
            self.sub_handle_balance(e.index, e.value)
        elif t == self.physical_mixer.MixerEventType.FADER_SINK:
            self.switch_sink(e.index, e.value)
        elif t == self.physical_mixer.MixerEventType.FADER_REMAP:
            self.remap_faders(e.index, e.value)
        elif t == self.physical_mixer.MixerEventType.FADER_EJECT:
            self.eject_fader(e.index)
        

    def run(self) -> None:
        while True:
            e = self.event_queue.get()
            if e == None:
                self.pulse = None
                break
            if isinstance(e, pulsectl.PulseEventInfo):
                try:
                    self.handle_pulse(e)
                except Exception as e:
                    traceback.print_exc()
            elif isinstance(e, self.physical_mixer.MixerEvent):
                try:
                    self.handle_apc(e)
                except Exception as e:
                    traceback.print_exc()
            else:
                raise Exception("Invalid event type")

class PulsePlugin(AbstractAPCPlugin):
    def __init__(self, name: str):
        super().__init__(name)
        self.registered = False
    
    def on_register(self, apc_proxy: APCMiniProxy):
        super().on_register(apc_proxy)
        assert not self.registered
        self.registered = True

        self.fader_pool = FaderPool()
        self.event_queue = SimpleQueue()
        self.pulsewatch = PulseWatcher(self.event_queue)
        self.physical_mixer = PhysicalMixer(apc_proxy, self.event_queue)
        self.pulse = pulsectl.Pulse()
        self.eventloop = EventLoop(self.event_queue, self.fader_pool, self.pulse, self.physical_mixer)
        self.eventloop.start()
        self.pulsewatch.start()
        
    def on_unregister(self):
        self.pulsewatch.end()
        self.eventloop.join()
        self.pulse.close()
        super().on_unregister()

    def on_btn_press(self, btn: ButtonID) -> None:
        self.physical_mixer.on_btn_press(btn)
    def on_btn_release(self, btn: ButtonID) -> None:
        self.physical_mixer.on_btn_release(btn)
    def on_fader_change(self, fader: int, value: float, synthetic: bool = False) -> None:
        self.physical_mixer.on_fader_change(fader, value)
