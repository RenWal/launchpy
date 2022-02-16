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

import importlib
from time import sleep

import mido

import settings
from apc import APCMini
from multiplexer import APCMultiplexer, AbstractAPCPlugin

class LaunchPy:

    def __init__(self, settings: settings) -> None:
        self.settings = settings
        self.port = self.settings.APC_PORT or self.autodiscover_port()

    @staticmethod
    def wait_keyboard_interrupt() -> None:
        try:
            while 1:
                sleep(1)
        except KeyboardInterrupt:
            pass

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

    def run_plugins(self) -> None:
        with mido.open_ioport(self.port) as midiport:
            apc = APCMini(midiport)
            multiplexer = APCMultiplexer(apc)

            for fqn, name, areas in self.settings.PLUGINS:
                plugin = self.instantiate_plugin(fqn, name)
                multiplexer.register(areas, plugin)

            self.wait_keyboard_interrupt()
            multiplexer.shutdown()
            apc.reset()


if __name__ == "__main__":
    lp = LaunchPy(settings)
    lp.run_plugins()
