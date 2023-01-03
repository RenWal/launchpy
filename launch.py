#!/usr/bin/env python3

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

import asyncio
import importlib
from time import sleep

import mido
from mido.ports import IOPort

import settings
from apc import APCMini
from multiplexer import AbstractAPCPlugin, APCMultiplexer
from powerevents import PowerMonitor



class LaunchPy:

    def __init__(self, settings: settings) -> None:
        self.settings = settings
        self.portname: str = self.settings.APC_PORT or self.autodiscover_port()

    @staticmethod
    def autodiscover_port() -> str:
        ports = mido.get_output_names()
        try:
            return next(p for p in ports if "APC MINI" in p)
        except StopIteration as e:
            raise RuntimeError("APC Mini MIDI interface not found") from e

    @staticmethod
    def instantiate_plugin(fqn: str, name: str) -> AbstractAPCPlugin:
        (path, clazz) = fqn.rsplit(".", maxsplit=1)
        module = importlib.import_module(path)
        plugin = getattr(module, clazz)
        return plugin(name)
    
    def run(self) -> None:
        print("LaunchPy starting")
        loop = asyncio.get_event_loop()
        try:
            asyncio.ensure_future(self.mainloop(), loop=loop)
            # waits for keyboard interrupt; don't replace this with a simple sleep()
            # since the PowerMonitor uses asyncio to listen to the system message bus
            loop.run_forever()
        except KeyboardInterrupt:
            pass
        loop.run_until_complete(self.cleanup())
        print("LaunchPy shutdown")

    async def mainloop(self) -> None:
        self.port = mido.open_ioport(self.portname)
        self.apc = APCMini(self.port)
        self.multiplexer = APCMultiplexer(self.apc)

        print("Initializing plugins")
        for fqn, name, areas in self.settings.PLUGINS:
            plugin = self.instantiate_plugin(fqn, name)
            self.multiplexer.register(areas, plugin)
        print("All plugins loaded")

        if settings.ENABLE_STANDBY_SUPPORT:
            # blank APC when system goes to sleep, unblank on resume
            async def before_sleep():
                print("blanking before sleep")
                self.multiplexer.blank(True)
            async def after_wakeup():
                print("blanking unblanking after wakeup")
                self.multiplexer.blank(False)
            
            # power monitor will connect to systemd-logind and trigger the
            # two callbacks specified above as necessary
            self.power_monitor = PowerMonitor(before_sleep, after_wakeup)
            await self.power_monitor.enable()
            print("Standby-aware mode enabled")

    async def cleanup(self):
        if settings.ENABLE_STANDBY_SUPPORT:
            await self.power_monitor.disable()
        self.multiplexer.shutdown()
        self.apc.reset()
        self.port.close()

if __name__ == "__main__":
    lp = LaunchPy(settings)
    lp.run()
