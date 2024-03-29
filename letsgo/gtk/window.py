import logging
import os
import time

from gi.repository import Gio, Gtk, GLib, Gdk

from letsgo.control import Controller, controller_classes
from letsgo.gtk.control import gtk_controller_classes
from letsgo.track import Anchor

from letsgo.layout_parser import get_parser_for_filename, parser_classes

from letsgo.layout_serializer import get_serializer_for_filename, serializer_classes

from letsgo.gtk.layout_drawingarea import LayoutDrawer

from letsgo.gtk.configure_dialog import ConfigureDialog

from letsgo.gtk.layout import LayoutListBox

from letsgo.gtk.trains import TrainListBox

from letsgo import signals
from letsgo.layout import Layout

from letsgo.gtk.utils import get_builder
from letsgo.pieces import FlippablePiece, Piece

logger = logging.getLogger(__name__)


class LayoutWindow(Gtk.ApplicationWindow):
    def __new__(cls):
        builder = get_builder()
        self = builder.get_object("layout-window")
        self.__class__ = cls
        self.builder = builder
        return self

    def __init__(self):
        self.set_title("Let's Go! Trains")

        self.layout_area = self.builder.get_object("layout")
        self.layout = Layout()

        self.builder.get_object("menu-button").set_menu_model(self.create_menu())

        self.create_actions()
        self.connect_signals()

        # Force disable all actions
        self.on_selection_changed(self.layout, None)

        self.current_filename = None
        self.saved_epoch = self.layout.epoch

        signals.tick.connect(self.layout.tick)
        # self.topham_hatt = TophamHatt(self.layout)
        # signals.tick.connect(self.topham_hatt.tick)

        self.controller_add_menu = Gio.Menu()
        for name, controller_cls in sorted(
            controller_classes.items(), key=lambda pair: pair[1].label
        ):
            self.controller_add_menu.append(
                controller_cls.label, f"win.controller-add::{name}"
            )
        self.builder.get_object("controller-add-button").set_menu_model(
            self.controller_add_menu
        )

        self.controller_box = self.builder.get_object("controller-box")
        self.train_listbox = TrainListBox(self.layout, self.builder)
        self.layout_listbox = LayoutListBox(self.layout, self.builder)
        self.configure_dialog = ConfigureDialog(self.layout, self.builder)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect(
            "activate",
            lambda action, parameter: self.builder.get_object("about-dialog").run(),
        )
        self.builder.get_object("about-dialog").connect(
            "delete-event", self.hide_about_dialog
        )
        self.builder.get_object("about-dialog").connect(
            "response", self.hide_about_dialog
        )
        self.add_action(about_action)

        self.connect("delete-event", self.on_delete_event)

        self.layout_drawer = LayoutDrawer(self.layout_area, self.layout)

        self.layout.start()
        # self.last_tick = time.time()
        # GLib.timeout_add(30, self.send_tick)

    def create_actions(self):
        self.actions = {
            # Layout actions
            "layout-new": Gio.SimpleAction.new("layout-new", None),
            "layout-open": Gio.SimpleAction.new("layout-open", None),
            "layout-save": Gio.SimpleAction.new("layout-save", None),
            "layout-save-as": Gio.SimpleAction.new("layout-save-as", None),
            "layout-details": Gio.SimpleAction.new("layout-details", None),
            # Piece actions
            "piece-flip": Gio.SimpleAction.new("piece-flip", None),
            "piece-rotate": Gio.SimpleAction.new(
                "piece-rotate", GLib.VariantType.new("i")
            ),
            # Anchor actions
            "anchor-split": Gio.SimpleAction.new("anchor-split", None),
            # Selection actions
            "selection-delete": Gio.SimpleAction.new("selection-delete", None),
            # Controller actions
            "controller-add": Gio.SimpleAction.new(
                "controller-add", GLib.VariantType.new("s")
            ),
            "controller-remove": Gio.SimpleAction.new(
                "controller-remove", GLib.VariantType.new("s")
            ),
            "about": Gio.SimpleAction.new("about", None),
        }
        self.actions["controller-remove"].set_enabled(True)
        for action in self.actions.values():
            self.add_action(action)

    def connect_signals(self):
        self.connect("window-state-event", self.on_window_state_event)
        self.actions["layout-new"].connect("activate", self.on_layout_new)
        self.actions["layout-open"].connect("activate", self.on_layout_open)
        self.actions["layout-details"].connect("activate", self.on_configure_clicked)
        self.actions["layout-save"].connect("activate", self.on_layout_save)
        self.actions["layout-save-as"].connect("activate", self.on_layout_save_as)
        self.actions["piece-flip"].connect("activate", self.on_piece_flip)
        self.actions["anchor-split"].connect("activate", self.on_anchor_split)
        self.actions["selection-delete"].connect("activate", self.on_selection_delete)
        self.actions["controller-add"].connect("activate", self.on_controller_add)
        self.actions["controller-remove"].connect("activate", self.on_controller_remove)
        signals.selection_changed.connect(self.on_selection_changed)
        signals.controller_added.connect(self.on_controller_added)
        signals.controller_removed.connect(self.on_controller_removed)
        self.connect("destroy-event", self.on_destroy)

    def on_controller_add(self, action, parameter):
        controller = controller_classes[parameter.get_string()](layout=self.layout)
        self.layout.add_controller(controller)

    def on_controller_remove(self, action, parameter):
        self.layout.remove_controller(self.layout.controllers[parameter.get_string()])

    def on_controller_added(self, sender, controller: Controller):
        gtk_controller_cls = gtk_controller_classes[type(controller).entrypoint_name]
        gtk_controller = gtk_controller_cls(controller)
        self.controller_box.pack_start(gtk_controller, False, False, 0)
        # self.controller_box.pack_start(Gtk.Separator(), False, False, 0)
        self.controller_box.show_all()

    def on_controller_removed(self, sender, controller: Controller):
        for gtk_controller in self.controller_box.get_children():
            if gtk_controller.controller == controller:
                gtk_controller.destroy()

    def on_destroy(self, *args):
        self.layout.stop()

    def create_menu(self):
        menu = Gio.Menu()
        menu.append("Layout details", "win.layout-details")
        menu.append("Save _as…", "win.layout-save-as")
        menu.append("About", "win.about")
        return menu

    def on_layout_new(self, action, parameter):
        self.layout.clear()

    def on_window_state_event(self, widget, event):
        return
        self.application.settings.set_int(
            "window-state", event.new_window_state & self.WINDOW_STATE_TO_SAVE
        )

    def hide_about_dialog(self, dialog, *args):
        dialog.hide()
        return True

    def on_selection_changed(self, sender, selection):
        self.actions["piece-flip"].set_enabled(isinstance(selection, FlippablePiece))
        self.actions["piece-rotate"].set_enabled(isinstance(selection, Piece))
        self.actions["anchor-split"].set_enabled(isinstance(selection, Anchor))
        self.actions["selection-delete"].set_enabled(
            isinstance(selection, Piece)
            or (isinstance(selection, Anchor) and len(selection) == 1)
        )

    def on_configure_clicked(self, action, parameter):
        if not self.configure_dialog.get_visible():
            self.configure_dialog.show()

    def on_delete_event(self, widget: Gtk.Window, event: Gdk.Event) -> bool:
        """Should be called before the current layout is abandoned, either by closing or opening a new layout.

        :return: True if the current action should be cancelled, otherwise False, in line with signal propagation"""
        if self.layout.epoch == self.saved_epoch:
            return False

        if self.current_filename:
            layout_name = f' "{os.path.basename(self.current_filename)}"'
        else:
            layout_name = ""

        dialog = Gtk.MessageDialog(parent=self, modal=True, destroy_with_parent=True)

        dialog.set_markup(
            f'<span weight="bold" size="larger">Save changes to layout{layout_name} before closing?</span>'
        )
        dialog.format_secondary_text(
            "If you don't save, changes will be permanently lost."
        )

        close_without_saving_button = dialog.add_button(
            "Close _without Saving", Gtk.ResponseType.NO
        )
        dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button(
            "_Save" if self.current_filename else "_Save As…", Gtk.ResponseType.YES
        )

        close_without_saving_button.get_style_context().add_class(
            Gtk.STYLE_CLASS_DESTRUCTIVE_ACTION
        )

        dialog.set_default_response(Gtk.ResponseType.YES)

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            return self.on_layout_save()

        return response == Gtk.ResponseType.CANCEL

    # File loading and saving

    def on_layout_open(self, action, parameter):
        file_chooser = Gtk.FileChooserNative.new(
            "Open layout", self, Gtk.FileChooserAction.OPEN, "_Open", "_Cancel"
        )

        supported_file_filter = Gtk.FileFilter()
        supported_file_filter.set_name("All supported files")
        file_chooser.add_filter(supported_file_filter)

        for parser_cls in parser_classes:
            file_filter = Gtk.FileFilter()
            file_filter.set_name(
                f"{parser_cls.name} layout ({parser_cls.file_extension})"
            )
            supported_file_filter.add_pattern("*" + parser_cls.file_extension)
            file_filter.add_pattern("*" + parser_cls.file_extension)
            file_chooser.add_filter(file_filter)

        file_filter = Gtk.FileFilter()
        file_filter.set_name("All files")
        file_filter.add_pattern("*")
        file_chooser.add_filter(file_filter)

        if file_chooser.run() == Gtk.ResponseType.ACCEPT:
            self.load_from_filename(file_chooser.get_filename())

    def load_from_filename(self, filename):
        parser = get_parser_for_filename(filename)
        if parser:
            self.layout.clear()
            with open(filename, "rb") as f:
                parser.parse(f, self.layout)
            self.current_filename = filename
            self.saved_epoch = self.layout.epoch
        else:
            logger.warning("No parser for file %s", filename)

    def on_layout_save(self, *args, **kwargs):
        if not self.current_filename:
            return self.on_layout_save_as()

        serializer = get_serializer_for_filename(self.current_filename)
        if not serializer:
            return self.on_layout_save_as()

        with open(self.current_filename, "wb") as fp:
            serializer.serialize(fp, self.layout)
            self.saved_epoch = self.layout.epoch

        return False

    def on_layout_save_as(self, *args, **kwargs):
        file_chooser = Gtk.FileChooserNative.new(
            "Save layout", self, Gtk.FileChooserAction.SAVE, "_Save", "_Cancel"
        )

        file_chooser.set_do_overwrite_confirmation(True)
        if self.current_filename:
            file_chooser.set_filename(self.current_filename)
        else:
            file_chooser.set_current_name("layout.lgl")

        for serializer_cls in serializer_classes:
            file_filter = Gtk.FileFilter()
            file_filter.set_name(
                f"{serializer_cls.name} layout ({serializer_cls.file_extension})"
            )
            file_filter.add_pattern("*" + serializer_cls.file_extension)
            file_chooser.add_filter(file_filter)

        if file_chooser.run() == Gtk.ResponseType.ACCEPT:
            filename = file_chooser.get_filename()
            serializer = get_serializer_for_filename(filename)
            if serializer:
                with open(filename, "wb") as fp:
                    serializer.serialize(fp, self.layout)
                self.current_filename = filename
                self.saved_epoch = self.layout.epoch
            else:
                logger.warning("No parser for file %s", filename)

            return False
        else:
            return True

    # Currently unused
    def on_piece_added(self, sender, piece):
        if isinstance(piece, BasePoints):
            grid = Gtk.Grid()
            drawing_area = Gtk.DrawingArea()
            drawing_area.set_size_request(30, 30)
            grid.attach(drawing_area, 0, 0, 1, 2)
            label = Gtk.Label()
            label.set_text(piece.label.title())
            label.set_halign(Gtk.Align.START)
            grid.attach(label, 1, 0, 1, 1)
            switch = Gtk.Switch()
            switch.connect("notify::active", self.on_control_switch_activated, piece)
            switch.set_active(piece.state == "branch")
            grid.attach(switch, 1, 1, 1, 1)
            configure = Gtk.Button.new_from_icon_name(
                "preferences-other", Gtk.IconSize.MENU
            )
            grid.attach(configure, 2, 0, 1, 2)
            # self.control_listbox.add(grid)

    def on_control_switch_activated(self, switch, gparam, points):
        points.state = "branch" if switch.get_active() else "out"

    def on_piece_flip(self, action, parameter):
        self.layout_drawer.flip_selection()

    def on_anchor_split(self, action, parameter):
        self.layout_drawer.split_selection()

    def on_selection_delete(self, action, parameter):
        self.layout_drawer.delete_selection()

    def send_tick(self):
        this_tick = time.time()
        signals.tick.send(
            self.layout, time=this_tick, time_elapsed=this_tick - self.last_tick
        )
        self.last_tick = this_tick
        return True
