import enum
import json

from gi.repository import GObject, Gtk, Gdk, GdkPixbuf
from letsgo.drawing import Colors

from letsgo.drawing_options import DrawingOptions
from letsgo.pieces import piece_classes
from letsgo.sensor import sensor_classes


class PieceColumn(enum.IntEnum):
    id = 0
    label = 1
    pixbuf = 2


class LayoutElement(Gtk.Grid):
    def __init__(self, piece, label):
        super().__init__()

        self.piece = piece

        self.drawing_area = Gtk.DrawingArea()
        self.drawing_area.set_size_request(30, 30)
        self.attach(self.drawing_area, 0, 0, 1, 3)

        self.label = Gtk.Label(label)
        self.attach(self.label, 1, 0, 1, 1)


class LayoutListBox(Gtk.IconView):
    def __new__(cls, layout, builder):
        self = builder.get_object("piece-iconview")
        self.__class__ = cls
        self.layout = layout
        self.builder = builder

        self.set_text_column(PieceColumn.label)
        self.set_pixbuf_column(PieceColumn.pixbuf)
        self.set_columns(2)

        model = Gtk.ListStore(object, str, GdkPixbuf.Pixbuf)
        self.set_model(model)

        self.populate()

        self.enable_model_drag_source(
            Gdk.ModifierType.BUTTON1_MASK, [], Gdk.DragAction.COPY
        )
        self.connect("drag-data-get", self.on_drag_data_get)
        self.drag_source_add_text_targets()

        return self

    def on_drag_data_get(self, widget, drag_context, data, info, time):
        selected_path = self.get_selected_items()[0]
        selected_iter = self.get_model().get_iter(selected_path)

        cls = self.get_model().get_value(selected_iter, PieceColumn.id)
        data.set_text(
            json.dumps(
                {
                    "entrypoint_group": cls.entrypoint_group,
                    "entrypoint_name": cls.entrypoint_name,
                }
            ),
            -1,
        )

    def populate(self):
        drawing_options = DrawingOptions(
            offset=(0, 0),
            scale=3,
            rail_color=Colors.dark_bluish_gray.rgb,
            sleeper_color=Colors.tan.rgb,
        )

        for piece_id, piece_cls in sorted(
            piece_classes.items(), key=lambda id_cls: id_cls[1].layout_priority
        ):
            piece = piece_cls(layout=None)
            # pixbuf = Gtk.IconTheme.get_default().load_icon('help-about', 16, 0)
            image = piece.get_icon_surface(drawing_options)
            pixbuf = Gdk.pixbuf_get_from_surface(
                image, 0, 0, image.get_width(), image.get_height()
            )
            self.get_model().append([piece_cls, piece.label, pixbuf])

        for sensor_id, sensor_cls in sorted(
            sensor_classes.items(), key=lambda id_cls: id_cls[1].label
        ):
            self.get_model().append([sensor_cls, sensor_cls.label, None])
