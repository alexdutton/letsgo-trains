from __future__ import annotations

import threading
from typing import Optional

from letsgo.registry_meta import WithRegistry

__all__ = ["Controller", "SensorController", "TrainController"]


class BinaryControl:
    pass


class Controllable:
    _controller = None
    _controller_kwargs = None

    @property
    def controller(self):
        return self._controller

    @property
    def controller_kwarg(self):
        return self._controller_kwargs

    def set_controller(self, controller: Optional[Controller], **kwargs):
        if self._controller:
            raise ValueError("Controller must be unset first")
        if controller:
            self._controller = controller
            self._controller_kwargs = kwargs
        else:
            self._controller = None
            self._controller_kwargs = None


class Controller(WithRegistry):
    entrypoint_group = "letsgo.controller"
    label: str

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.device_present = threading.Event()

    def start(self):
        raise NotImplemented

    def stop(self):
        raise NotImplemented


class SensorController(Controller):
    def register_sensor(self, sensor, *, index: int, **params):
        raise NotImplemented


class TrainController(Controller):
    def register_train(self, train, mac_address):
        raise NotImplemented
