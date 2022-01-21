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

from collections import deque
from threading import RLock

from apc import APCMini, ButtonArea, ButtonID, ButtonState

# TODO Think about the locking mechanism. Right now, for each event, we lock the
# entire multiplexer. However, this is only really needed when registering/
# unregistering plugins. Much of this could be narrowed down to locking only one
# specific plugin (as long as this plugin is also locked when the entire multiplexer
# is locked).

# A virtual APCMini device that plugins can always access, no matter if they are
# currently in the foreground or not. Bringing some area of plugin to the foreground
# will sync up the button lights of this virtual device with the physical one.
# Virtual faders will be updated as long as the horizontal area is in the foreground.
class APCMiniProxy:
    
    faders = None

    def __init__(self, host: APCMini, areas: ButtonArea, light_map: dict[ButtonArea, dict[int, ButtonState]], faders: list[float] = None) -> None:
        self.host = host
        self.areas = areas
        self.enabled_areas = 0
        self.light_map = light_map
        if faders:
            self.faders = faders * 1 # clone

    def sync_faders(self) -> set[int]:
        changed = set()
        if self.faders is None: return changed

        faders = self.host.faders
        for i in range(len(self.faders)):
            if self.faders[i] != faders[i]:
                changed.add(i)
                self.faders[i] = faders[i]
        return changed

    def update_fader(self, fader: int, value: float) -> None:
        if self.faders is None: return # ignore if no fader support
        assert fader in range(len(self.faders))
        self.faders[fader] = value

    @classmethod
    def make_blank(cls, apc: APCMini, areas: ButtonArea) -> APCMiniProxy:
        states = dict()
        for area in ButtonArea.split_flags(areas):
            buttons = APCMini.get_area_buttons(area)
            states[area] = { btn:ButtonState.OFF for btn in buttons }
        faders = apc.faders if (areas & ButtonArea.HORIZONTAL) else None
        return cls(apc, areas, states, faders)

    def set_button(self, buttonID: int, state: ButtonState) -> None:
        area = APCMini.id_to_button(buttonID).area
        assert area & self.areas, "Plugin attempted to write to non-registered button"
        self.light_map[area][buttonID] = state
        if self.is_area_enabled(area):
            self.host.set_button(buttonID, state)

    def enable_areas(self, areas: ButtonArea) -> None:
        assert (self.areas & areas) == areas, "Attempted to enable non-registered area"
        self.enabled_areas |= areas
        lights = dict()
        for area in ButtonArea.split_flags(areas):
            lights.update(self.light_map[area])
        self.host.set_all_buttons(lights.items())

    def disable_areas(self, areas: ButtonArea) -> None:
        assert (self.areas & areas) == areas, "Attempted to disable non-registered area"
        self.enabled_areas &= ~areas

    def is_area_enabled(self, area: ButtonArea) -> None:
        return (self.enabled_areas & area) == area

class AbstractAPCPlugin:
    def __init__(self, name: str) -> None:
        self.name = name
    
    def __repr__(self) -> None:
        return self.name

    # convenience method
    def set_button(self, buttonID: int, state: ButtonState) -> None:
        self.apc_proxy.set_button(buttonID, state)

    def on_register(self, apc_proxy: APCMiniProxy) -> None:
        self.apc_proxy = apc_proxy
    
    def on_unregister(self) -> None:
        self.apc_proxy = None

    # Called when the plugin comes to the foreground on some area.
    # After this point up to on_deactivate, all button presses and
    # fader changes are relayed to this plugin. All light changes
    # are sent to the hardware.
    def on_activate(self, area: ButtonArea) -> None:
        pass
    
    # Called when the plugin goes to the background on some area.
    # After this point up to on_activate, fader values are frozen
    # and button presses will not be relayed. The plugin is free to
    # change the lights on any buttons, however, this will only
    # affect the hardware in the moment the plugin comes back to
    # the foreground.
    def on_deactivate(self, area: ButtonArea) -> None:
        pass
    
    # event callbacks (only called while plugin is in foreground)
    
    def on_btn_press(self, btn: ButtonID) -> None:
        pass
    def on_btn_release(self, btn: ButtonID) -> None:
        pass

    # Synthetic fader events are those that are fired in the moment that the plugin
    # comes to the foreground on ButtonArea.HORIZONTAL for all faders that have
    # changed while the plugin was in the background.
    # If you want to keep the old fader values until the user actually touches the
    # fader while the plugin is in foreground, you can just ignore these events
    # (but keep in mind that self.apc_proxy.faders) reflects the physical position
    # anyway!)
    def on_fader_change(self, fader: int, value: float, synthetic: bool = False) -> None:
        pass

# Allows multiple plugins to share the same APCMini. The plugins can access 3 distinct
# areas: The button matrix, the vertical round buttons to the right, and the fader bank
# including the round button above each fader.
# Each area can be used by one plugin at a time, while other plugins are in the background.
# Also, each area is assigned independently to a plugin, so you can have the button matrix
# connected to plugin A, while the faders are used by plugin B.
# TO CYCLE THROUGH PLUGINS FOR AN AREA hold the SHIFT button (the one on the APC, not on
# your keyboard) and then tap any button on that area. This will bring the next plugin to
# the foreground, in a round-robin fashion. (Note that this means that the SHIFT button is
# unavailable in the plugins!)
class APCMultiplexer:

    def __init__(self, apc: APCMini) -> None:
        self.switch_scene_arm = False
        self.plugin_lock = RLock()
        self.apc = apc
        self.area_plugins = {
            # faders are always bound to whoever has the horizontal buttons area
            ButtonArea.HORIZONTAL: deque(),
            ButtonArea.VERTICAL: deque(),
            ButtonArea.MATRIX: deque()
        }
        self.plugin_proxies: dict[AbstractAPCPlugin, APCMiniProxy] = dict()
        self.plugin_areas: dict[AbstractAPCPlugin, ButtonArea] = dict()

        apc.disable_events()
        apc.reset()
        apc.cb_button_pressed = self._on_btn_press
        apc.cb_button_released = self._on_btn_release
        apc.cb_fader_value = self._on_fader_change
        apc.enable_events()

    def register(self, areas: ButtonArea, plugin: AbstractAPCPlugin) -> None:
        with self.plugin_lock:
            self._create_plugin_data(plugin, areas)
            proxy = self.plugin_proxies[plugin]
            plugin.on_register(proxy)
            for area in ButtonArea.split_flags(areas):
                if len(self.area_plugins[area]) == 1:
                    proxy.enable_areas(area)
                    plugin.on_activate(area)
        area_names = ' '.join([a.name for a in ButtonArea.split_flags(areas)])
        print(f"Registered {plugin.name} on areas {area_names}")

    def _create_plugin_data(self, plugin, areas):
        self.plugin_areas[plugin] = areas
        self.plugin_proxies[plugin] = APCMiniProxy.make_blank(self.apc, areas)
        for area in ButtonArea.split_flags(areas):
            self.area_plugins[area].append(plugin)

    def shutdown(self) -> None:
        for plugin in list(self.plugin_areas.keys()): # ensure list is copied, since unregister() modifies it
            self.unregister(plugin)

    def unregister(self, plugin: AbstractAPCPlugin) -> None:
        with self.plugin_lock:
            areas = self.plugin_areas[plugin]
            proxy = self.plugin_proxies[plugin]
            for area in ButtonArea.split_flags(areas):
                if self.area_plugins[area][0] == plugin:
                    plugin.on_deactivate(area)
                    proxy.disable_areas(area)
            plugin.on_unregister()
            self._delete_plugin_data(plugin, areas)
        print(f"Unregistered {plugin.name}")

    def _delete_plugin_data(self, plugin, areas):
        for area in ButtonArea.split_flags(areas):
            self.area_plugins[area].remove(plugin)
        self.plugin_proxies.pop(plugin)
        self.plugin_areas.pop(plugin)

    def next_scene(self, area: ButtonArea) -> None:
        with self.plugin_lock:
            area_plugins = self.area_plugins[area]
            if len(area_plugins) > 1:
                active_plugin = area_plugins[0]
                self._disable_plugin_area(area, active_plugin)
                
                self.area_plugins[area].rotate(1)
                next_plugin = area_plugins[0]
                self._enable_plugin_area(area, next_plugin)
                print("Activated", next_plugin)

    def _disable_plugin_area(self, area, plugin):
        plugin.on_deactivate(area)
        self.plugin_proxies[plugin].disable_areas(area)

    def _enable_plugin_area(self, area, plugin):
        proxy = self.plugin_proxies[plugin]
        proxy.enable_areas(area)
        plugin.on_activate(area)
        if area & ButtonArea.HORIZONTAL:
            # pull physical fader values into virtual APC
            changed_faders = proxy.sync_faders()
            # synthesize fader move events to make plugin aware of fader changes
            for fader_id in changed_faders:
                plugin.on_fader_change(fader_id, self.apc.faders[fader_id], synthetic=True)
    
    def _on_btn_press(self, btn: APCMini.ButtonID) -> None:
        if btn.area == ButtonArea.SHIFT_BUTTON:
            self.switch_scene_arm = True
        elif self.switch_scene_arm:
            self.next_scene(btn.area)
        else:
            with self.plugin_lock:
                if self.area_plugins[btn.area]:
                    self.area_plugins[btn.area][0].on_btn_press(btn)

    def _on_btn_release(self, btn: APCMini.ButtonID) -> None:
        if btn.area == ButtonArea.SHIFT_BUTTON:
            self.switch_scene_arm = False
        elif not self.switch_scene_arm:
            with self.plugin_lock:
                if self.area_plugins[btn.area]:
                    self.area_plugins[btn.area][0].on_btn_release(btn)

    def _on_fader_change(self, fader: int, value: float) -> None:
        with self.plugin_lock:
            if self.area_plugins[ButtonArea.HORIZONTAL]:
                foreground_plugin = self.area_plugins[ButtonArea.HORIZONTAL][0]
                foreground_plugin.on_fader_change(fader, value)
                self.plugin_proxies[foreground_plugin].update_fader(fader, value)
