from apc import APCMini, ButtonArea, ButtonID, ButtonState
from dasbus.connection import SessionMessageBus
from multiplexer import APCMiniProxy, AbstractAPCPlugin


class GnomeWorkspacePlugin(AbstractAPCPlugin):
    def __init__(self, name: str):
        super().__init__(name)

    ACTIVATE_WORKSPACE_JS = "global.workspace_manager.get_workspace_by_index({}).activate(global.get_current_time());"

    def init_dbus(self):
        bus = SessionMessageBus()
        self.gnome_proxy = bus.get_proxy("org.gnome.Shell", "/org/gnome/Shell")
    
    def on_register(self, apc_proxy: APCMiniProxy):
        super().on_register(apc_proxy)
        self.init_dbus()
        self.prev_workspace = None
        print("Reg done")
    
    def on_unregister(self):
        return super().on_unregister()

    def activate_workspace(self, i):
        self.gnome_proxy.Eval(self.ACTIVATE_WORKSPACE_JS.format(i))

    def on_btn_press(self, btn: ButtonID):
        assert btn.area == ButtonArea.VERTICAL
        self.activate_workspace(btn.ordinal)
        if self.prev_workspace is not None:
            self.set_button(self.prev_workspace, ButtonState.OFF)
        next_button_id = btn.ordinal+APCMini.VERTICAL_OFFSET
        self.set_button(next_button_id, ButtonState.GREEN)
        self.prev_workspace = next_button_id
