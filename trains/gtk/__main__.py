import os
import sys
import threading
import time

import pkg_resources

import gi
import yaml

import lego_wireless
from trains.drawing import DrawnPiece
from trains.gtk.layout_drawingarea import LayoutDrawer
from trains.gtk.trains import TrainListBox
from trains.layout import Layout
from trains.topham_hatt import TophamHatt
from trains.track import TrackPiece

gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, Gio, GObject, GLib, Gdk

from .. import signals, track


class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.example.myap")

        self.builder = Gtk.Builder()
        self.builder.add_from_string(pkg_resources.resource_string('trains', 'data/trains.glade').decode())
        self.window = self.builder.get_object('main-window')

        self.status_bar: Gtk.Statusbar = self.builder.get_object('status-bar')

        self.hub_manager = lego_wireless.HubManager('hci0')
        self.hub_manager_thread = threading.Thread(target=self.hub_manager.run)

        lego_wireless.signals.hub_discovered.connect(self.hub_discovered)
        lego_wireless.signals.hub_connected.connect(self.hub_connected)
        lego_wireless.signals.hub_disconnected.connect(self.hub_disconnected)


        self.canvas = self.builder.get_object('canvas')


        self.layout_palette = self.builder.get_object('layout-palette')
        self.layout_palette.add(self.get_track_piece_toolgroup())
        self.layout_area = self.builder.get_object('layout')

        self.layout = Layout()
        signals.tick.connect(self.layout.tick)
        self.topham_hatt = TophamHatt(self.layout)
        signals.tick.connect(self.topham_hatt.tick)

        self.control_listbox = self.builder.get_object('control-listbox')
        self.train_listbox = TrainListBox(self.layout, self.builder)

        self.layout_drawer = LayoutDrawer(self.layout_area, self.layout)

        signals.piece_added.connect(self.on_piece_added, sender=self.layout)

        self.layout.load_from_yaml(yaml.safe_load(pkg_resources.resource_string('trains', 'data/layouts/stations.yaml')))

        self.last_tick = time.time()
        GObject.timeout_add(20, self.send_tick)

    def send_tick(self):
        this_tick = time.time()
        signals.tick.send(self.layout, time=this_tick, time_elapsed=this_tick - self.last_tick)
        self.last_tick = this_tick
        return True

    def on_piece_added(self, sender, piece):
        if isinstance(piece, track.Points):
            grid = Gtk.Grid()
            drawing_area = Gtk.DrawingArea()
            drawing_area.set_size_request(30, 30)
            grid.attach(drawing_area, 0, 0, 1, 2)
            label = Gtk.Label(piece.label.title())
            label.set_halign(Gtk.Align.START)
            grid.attach(label, 1, 0, 1, 1)
            switch = Gtk.Switch()
            switch.connect("notify::active", self.on_control_switch_activated, piece)
            switch.set_active(piece.state == 'branch')
            grid.attach(switch, 1, 1, 1, 1)
            configure = Gtk.Button.new_from_icon_name('preferences-other', Gtk.IconSize.MENU)
            grid.attach(configure, 2, 0, 1, 2)
            self.control_listbox.add(grid)

    def on_control_switch_activated(self, switch, gparam, points):
        points.state = 'branch' if switch.get_active() else 'out'

    def get_track_piece_toolgroup(self):
        toolitemgroup = Gtk.ToolItemGroup(label='Track')
        toolitemgroup.add(self.get_track_piece_toolitem('straight'))
        toolitemgroup.add(self.get_track_piece_toolitem('curve'))
        toolitemgroup.add(self.get_track_piece_toolitem('crossover'))
        toolitemgroup.add(self.get_track_piece_toolitem('points'))
        return toolitemgroup

    def get_track_piece_toolitem(self, name):
        tool = Gtk.ToggleToolButton.new()
        tp = TrackPiece.registry[name]()

        image = Gtk.Image.new_from_file(os.path.join(os.path.dirname(__file__), 'data', 'pieces', tp.name + '.png'))
        tool.set_label(tp.label)
        tool.get_child().set_always_show_image(True)
        tool.get_child().set_image(image)

        return tool

    def run(self, *args, **kwargs):
        self.hub_manager.start_discovery()

        self.hub_manager_thread.start()
        super().run(*args, **kwargs)

    def hub_discovered(self, sender, hub):
        pair_with_train = None
        for train in self.layout.trains:
            if hub.mac_address.lower() == train.meta.get('mac_address', '').lower():
                pair_with_train = train
                break
        else:
            for train in self.layout.trains:
                if train.meta.get('pairing'):
                    train.meta['mac_address'] = hub.mac_address
                    pair_with_train = train
                    break
        if pair_with_train:
            hub.train = pair_with_train
            hub.connect()

    def hub_connected(self, sender, hub):
        for train in self.layout.trains:
            if hub.mac_address.lower() == train.meta.get('mac_address', '').lower():
                signals.train_hub_connected.send(train, hub=hub)
                break

    def hub_disconnected(self, sender, hub):
        for train in self.layout.trains:
            if hub.mac_address.lower() == train.meta.get('mac_address', '').lower():
                signals.train_hub_disconnected.send(train, hub=hub)
                break



    # def hub_connected(self, sender, hub):
    #     hub_status_context = self.status_bar.get_context_id('hub')
    #     self.status_bar.push(hub_status_context, 'Hub connected')
    #     self.train_box.pack_end(TrainEntry(hub), False, False, 0)
    #
    # def hub_disconnected(self, sender, hub):
    #     hub_status_context = self.status_bar.get_context_id('hub')
    #     self.status_bar.push(hub_status_context, 'Hub disconnected')

    def do_activate(self):
        Gtk.Application.do_activate(self)
        print(self.window)
        self.window.set_application(self)
        self.window.show_all()
        print('here')

    def do_startup(self):
        Gtk.Application.do_startup(self)

    def do_shutdown(self):
        self.hub_manager.stop()
        self.hub_manager_thread.join()
        Gtk.Application.do_shutdown(self)


if __name__ == '__main__':
    app = Application()
    app.run(sys.argv)