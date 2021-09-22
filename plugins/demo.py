from apc import APCMini, ButtonArea, ButtonID
from multiplexer import APCMiniProxy, AbstractAPCPlugin

from threading import Thread
from time import sleep

class DemoPlugin(AbstractAPCPlugin):
    def __init__(self, name: str):
        super().__init__(name)
        self.btn_state = {x:0 for x in range(64)}
        self.stop = False
        self.runner = None

    # overrides
    
    def on_register(self, apc_proxy: APCMiniProxy):
        super().on_register(apc_proxy)
        self.runner = Thread(target=self.lightmeup, name="Demo plugin runner")
        self.runner.start()
        print("Reg done")
    
    def on_unregister(self):
        self.stop=True
        self.runner.join()
        return super().on_unregister()

    def on_btn_press(self, btn: ButtonID):
        if btn.area == ButtonArea.MATRIX:
            # toggle green light on button that was pressed
            self.btn_state[btn.ordinal] = 1-self.btn_state[btn.ordinal]
            self.set_button(btn.ordinal, self.btn_state[btn.ordinal])

    # threads

    def lightmeup(self):
        while not self.stop:
            for btn in range(APCMini.N_MATRIX):
                if self.stop: break
                self.btn_state[btn] = 1-self.btn_state[btn]
                self.set_button(btn+APCMini.MATRIX_OFFSET, self.btn_state[btn])
                sleep(1)