from dbus_next.aio import MessageBus
from dbus_next import BusType
import os

class PowerMonitor:
    def __init__(self, before_sleep, after_wakeup) -> None:
        self.before_sleep = before_sleep
        self.after_wakeup = after_wakeup
        self.manager = None
        self.fd = None
        
    async def enable(self):
        if not self.manager:
            # connect to manager interface of systemd-logind
            dbus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
            introspection = await dbus.introspect('org.freedesktop.login1', '/org/freedesktop/login1')
            proxy = dbus.get_proxy_object("org.freedesktop.login1", "/org/freedesktop/login1", introspection)
            self.manager = proxy.get_interface('org.freedesktop.login1.Manager')
        # set callback to trigger when systemd wants to put the system to sleep,
        # and when it wakes back up
        self.manager.on_prepare_for_sleep(self.sleep_callback)
        # acquire a wake lock (session inhibitor; systemd will wait for us before actually suspending the system)
        await self.take_wake_lock()

    async def disable(self):
        # disable the callback
        self.manager.off_prepare_for_sleep(self.sleep_callback)
        # release the wake lock (allowing systemd to proceed with going to sleep)
        await self.release_wake_lock()

    async def take_wake_lock(self):
        # we receive the wake lock in form of a file descriptor passed via dbus
        self.fd = await self.manager.call_inhibit("sleep", "LaunchPy", "Suspending APC Mini", "delay")

    async def release_wake_lock(self):
        # we inform systemd about releasing the wake lock simply by closing the file descriptor
        os.close(self.fd)

    async def sleep_callback(self, state):
        if state:
            # system about to sleep
            await self.before_sleep()
            await self.release_wake_lock()
        else:
            # system just woke up
            await self.after_wakeup()
            await self.take_wake_lock()