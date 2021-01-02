import json
from typing import Any, Dict, Optional, Type, Union

import cairo
import math

import gi
import pkg_resources
from cairo import Context
from letsgo import pieces

from letsgo.pieces import FlippablePiece, Piece, piece_classes

from letsgo.drawing_options import DrawingOptions

from letsgo.drawing import Colors, hex_to_rgb
from letsgo.layout import Layout
from letsgo.sensor import Sensor
from letsgo.track import Anchor, Position
from .. import signals
from ..pieces.curve import BaseCurve, CurveDirection
from ..pieces.points import BasePoints
from ..track_point import TrackPoint
from ..trackside_item import TracksideItem

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import GObject, Gdk, Gtk


class LayoutDrawer:
    keyboard_piece_placement = {
        Gdk.KEY_q: pieces.Curve,
        Gdk.KEY_w: pieces.Straight,
        Gdk.KEY_e: lambda *, layout: pieces.Curve(
            layout=layout, direction=CurveDirection.right
        ),
        Gdk.KEY_a: pieces.LeftPoints,
        Gdk.KEY_s: pieces.Crossover,
        Gdk.KEY_d: pieces.RightPoints,
    }

    def __init__(self, drawing_area: Gtk.DrawingArea, layout):
        self.drawing_area = drawing_area
        self.drawing_area.set_can_focus(True)
        self.drawing_area.connect("draw", self.draw)

        self.drawing_area.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drawing_area.connect("drag-motion", self.on_drag_motion)
        self.drawing_area.connect("drag-data-received", self.on_drag_data_received)
        self.drawing_area.drag_dest_add_text_targets()

        self.drawing_area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.drawing_area.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.drawing_area.add_events(Gdk.EventMask.BUTTON_MOTION_MASK)
        self.drawing_area.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
        self.drawing_area.add_events(Gdk.EventMask.KEY_PRESS_MASK)
        self.drawing_area.add_events(Gdk.EventMask.SCROLL_MASK)
        self.drawing_area.add_events(Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.drawing_area.connect("button-press-event", self.mouse_press)
        self.drawing_area.connect("button-release-event", self.mouse_release)
        self.drawing_area.connect("motion-notify-event", self.mouse_motion)
        self.drawing_area.connect("key-press-event", self.on_key_press)
        self.drawing_area.connect("scroll-event", self.on_scroll)

        self.drawing_options = DrawingOptions(
            offset=(0, 0),
            scale=3,
            rail_color=Colors.dark_bluish_gray.rgb,
            sleeper_color=Colors.tan.rgb,
        )

        self.highlight_drawing_options = DrawingOptions(
            offset=self.drawing_options.offset,
            scale=self.drawing_options.scale,
            rail_color=(0.5, 0.5, 1),
            sleeper_color=(0.5, 0.5, 1),
        )

        self.selection_drawing_options = DrawingOptions(
            offset=self.drawing_options.offset,
            scale=self.drawing_options.scale,
            rail_color=(0.1, 0.1, 1),
            sleeper_color=(0.1, 0.1, 1),
        )

        self.offset_orig = None
        self.mouse_down = None
        self.layout = layout
        self.last_layout_state: Optional[Dict[str, Any]] = None

        self.highlight_item: Union[None, Piece, Anchor] = None
        self._selected_item: Union[None, Piece, Anchor] = None

        signals.tick.connect(self.tick)
        signals.layout_changed.connect(self.on_layout_changed)

    @property
    def selected_item(self):
        return self._selected_item

    @selected_item.setter
    def selected_item(self, value):
        self._selected_item = value
        signals.selection_changed.send(self.layout, selection=value)
        self.drawing_area.queue_draw()

    def tick(self, sender, time, time_elapsed):
        alloc = self.drawing_area.get_allocation()
        self.drawing_area.queue_draw_area(alloc.x, alloc.y, alloc.width, alloc.height)

    def mouse_press(self, widget, event):
        if event.button == Gdk.BUTTON_PRIMARY:
            self.drawing_area.grab_focus()
            self.selected_item = self.get_item_under_cursor(event)
            if not self.selected_item:
                self.offset_orig = self.drawing_options.offset
                self.mouse_down = event.x, event.y

    def mouse_release(self, widget, event):
        if event.button & Gdk.BUTTON_PRIMARY:
            self.offset_orig = None
            self.mouse_down = None

    def mouse_motion(self, widget, event):
        x, y = self.xy_to_layout(event.x, event.y)
        previous_highlight_item = self.highlight_item
        self.highlight_item = self.get_item_under_cursor(event)
        if self.mouse_down:
            self.drawing_options = self.drawing_options.replace(
                offset=(
                    self.offset_orig[0] + event.x - self.mouse_down[0],
                    self.offset_orig[1] + event.y - self.mouse_down[1],
                )
            )
            self.drawing_area.queue_draw()
        elif self.highlight_item != previous_highlight_item:
            self.drawing_area.queue_draw()

    def on_layout_changed(self, sender, cleared):
        self.drawing_area.queue_draw()

    def on_drag_motion(self, widget, drag_context, x, y, time):
        pass

    def on_drag_data_received(self, widget, drag_context, x, y, selection, info, time):
        try:
            data = json.loads(selection.get_text())
        except ValueError:
            return
        if not ("entrypoint_group" in data and "entrypoint_name" in data):
            return

        try:
            cls = next(
                pkg_resources.iter_entry_points(
                    data["entrypoint_group"], data["entrypoint_name"]
                )
            ).load()
        except StopIteration:
            return
        except ImportError:
            return

        x, y = self.xy_to_layout(x, y)

        if isinstance(cls, type) and issubclass(cls, Piece):
            self.place_piece(cls, x, y)
        elif isinstance(cls, type) and issubclass(cls, Sensor):
            self.place_sensor(cls, x, y)

    def place_piece(self, piece_cls: Type[Piece], x: float, y: float):
        possible_anchors = self.layout.anchors_qtree.intersect(
            (x - 8, y - 8, x + 8, y + 8)
        )
        possible_anchors = [anchor for anchor in possible_anchors if len(anchor) < 2]
        if possible_anchors:
            piece = piece_cls(layout=self.layout)
            possible_anchors[0] += piece.anchors[piece.anchor_names[0]]
        else:
            # Snap to an 8x8 grid
            x = 8 * ((x + 4) // 8)
            y = 8 * ((y + 4) // 8)
            piece = piece_cls(layout=self.layout, placement=Position(x, y, angle=0))

        self.connect_coincident_anchors(piece)
        self.layout.add_piece(piece)

    def place_sensor(self, sensor_cls: Type[Sensor], x: float, y: float):
        possible_pieces = self.layout.pieces_qtree.intersect(
            (x - 8, y - 8, x + 8, y + 8)
        )
        candidates = []
        for piece in possible_pieces:
            for in_anchor in piece.anchor_names:
                for out_anchor, (length, _) in piece.traversals(in_anchor).items():
                    offset = 0
                    try:
                        step = length / piece.sleepers
                    except AttributeError:
                        step = 4
                    while offset <= length:
                        pp = piece.point_position(
                            in_anchor=in_anchor, out_anchor=out_anchor, offset=offset
                        )
                        px, py = (
                            piece.position.x
                            + pp.x * math.cos(piece.position.angle)
                            - pp.y * math.sin(piece.position.angle),
                            piece.position.y
                            + pp.x * math.sin(piece.position.angle)
                            + pp.y * math.cos(piece.position.angle),
                        )
                        distance = math.dist((x, y), (px, py))
                        candidates.append(
                            {
                                "distance": distance,
                                "in_anchor": in_anchor,
                                "out_anchor": out_anchor,
                                "piece": piece,
                                "offset": offset,
                            }
                        )
                        offset += step
        # Always go for the closest, but prefer positions that aren't on points, and
        # which are coming from the in anchor
        candidates.sort(
            key=lambda c: (
                c["distance"],
                not isinstance(c["piece"], BasePoints),
                c["piece"].anchor_names.index(c["in_anchor"]),
            )
        )
        if candidates:
            candidate = candidates[0]
            sensor = sensor_cls(
                layout=self.layout,
                track_point=TrackPoint(
                    piece=candidate["piece"],
                    in_anchor=candidate["in_anchor"],
                    out_anchor=candidate["out_anchor"],
                    offset=candidate["offset"],
                ),
            )
            self.layout.add_sensor(sensor)

    def connect_coincident_anchors(self, piece: Piece):
        for anchor in piece.anchors.values():
            self.connect_coincident_anchor(anchor)

    def connect_coincident_anchor(self, anchor: Anchor):
        assert anchor.position
        epsilon = 0.0001
        for other_anchor in self.layout.anchors_qtree.intersect(
            (
                anchor.position.x - epsilon,
                anchor.position.y - epsilon,
                anchor.position.x + epsilon,
                anchor.position.y + epsilon,
            )
        ):
            other_anchor: Anchor
            if (
                anchor != other_anchor
                and len(anchor) == 1
                and len(other_anchor) == 1
                and anchor.position.angle_is_opposite(other_anchor.position)
            ):
                other_anchor += anchor
                break

    def flip_selection(self):
        if isinstance(self.selected_item, FlippablePiece):
            original_selected_item = self.selected_item
            self.selected_item = self.selected_item.flip()
            if self.highlight_item == original_selected_item:
                self.highlight_item = self.selected_item
            self.layout.changed()

    def split_selection(self):
        if isinstance(self.selected_item, Anchor):
            self.selected_item.split()
            self.layout.changed()

    def join_selection(self):
        if isinstance(self.selected_item, Piece):
            self.connect_coincident_anchors(self.selected_item)
            self.layout.changed()
        elif isinstance(self.selected_item, Anchor):
            self.connect_coincident_anchor(self.selected_item)
            self.layout.changed()

    def delete_selection(self):
        if isinstance(self.selected_item, Piece):
            full_anchors = [
                a for a in self.selected_item.anchors.values() if len(a) == 2
            ]
            if len(full_anchors) == 1:
                next_selected_item = full_anchors[0].next(self.selected_item)[0]
            else:
                next_selected_item = None

            self.layout.remove_piece(self.selected_item)
            if self.highlight_item == self.selected_item:
                self.highlight_item = None
            self.selected_item = next_selected_item
            self.drawing_area.queue_draw()

    def on_key_press(self, widget, event):
        if event.keyval in (Gdk.KEY_f, Gdk.KEY_F):
            self.flip_selection()
        if event.keyval in (Gdk.KEY_p, Gdk.KEY_P):
            self.split_selection()
        if event.keyval in (Gdk.KEY_j, Gdk.KEY_J):
            self.join_selection()
        if event.keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self.delete_selection()
        if (
            isinstance(self.selected_item, Piece)
            and event.keyval in self.keyboard_piece_placement
        ):
            partial_anchors = {
                n: a for n, a in self.selected_item.anchors.items() if len(a) == 1
            }
            for anchor_name in (
                self.selected_item.anchor_names[1:]
                + self.selected_item.anchor_names[:1]
            ):
                if anchor_name in partial_anchors:
                    new_piece = self.keyboard_piece_placement[event.keyval](
                        layout=self.layout
                    )
                    self.selected_item.anchors[anchor_name] += new_piece.anchors[
                        new_piece.anchor_names[0]
                    ]
                    self.connect_coincident_anchors(new_piece)
                    self.layout.add_piece(new_piece)
                    self.selected_item = new_piece
                    break

        if (
            isinstance(self.selected_item, Anchor)
            and len(self.selected_item) == 1
            and event.keyval in self.keyboard_piece_placement
        ):
            new_piece = self.keyboard_piece_placement[event.keyval](layout=self.layout)
            new_piece.anchors[new_piece.anchor_names[0]] += self.selected_item
            self.connect_coincident_anchors(new_piece)
            self.layout.add_piece(new_piece)
            if len(new_piece.anchor_names) > 1:
                self.selected_item = new_piece.anchors[new_piece.anchor_names[1]]
            else:
                self.selected_item = new_piece

    def on_scroll(self, widget, event):
        # TODO: Handle smooth scrolling
        if event.state & Gdk.ModifierType.SHIFT_MASK:
            if event.direction == Gdk.ScrollDirection.UP:
                self.drawing_options = self.drawing_options.replace(
                    scale=self.drawing_options.scale * 0.8
                )
            elif event.direction == Gdk.ScrollDirection.DOWN:
                self.drawing_options = self.drawing_options.replace(
                    scale=self.drawing_options.scale / 0.8
                )
            elif event.direction == Gdk.ScrollDirection.SMOOTH:
                scale_factor = 1.05 ** event.delta_y
                self.drawing_options = self.drawing_options.replace(
                    scale=self.drawing_options.scale * scale_factor,
                    offset=(
                        self.drawing_options.offset[0] * scale_factor,
                        self.drawing_options.offset[1] * scale_factor,
                    ),
                )
            else:
                return
        else:
            if event.direction == Gdk.ScrollDirection.UP:
                dx, dy = 0, 64 / self.drawing_options.scale
            elif event.direction == Gdk.ScrollDirection.DOWN:
                dx, dy = 0, -64 / self.drawing_options.scale
            elif event.direction == Gdk.ScrollDirection.LEFT:
                dx, dy = 64 / self.drawing_options.scale, 0
            elif event.direction == Gdk.ScrollDirection.RIGHT:
                dx, dy = -64 / self.drawing_options.scale, 0
            elif event.direction == Gdk.ScrollDirection.SMOOTH:
                dx, dy = (
                    -50 * event.delta_x,
                    -50 * event.delta_y,
                )
            else:
                return
            self.drawing_options = self.drawing_options.replace(
                offset=(
                    self.drawing_options.offset[0] + dx,
                    self.drawing_options.offset[1] + dy,
                )
            )

        self.drawing_area.queue_draw()

    def get_item_under_cursor(self, event):
        x, y = self.xy_to_layout(event.x, event.y)
        trackside_items = self.layout.trackside_items_qtree.intersect((x, y, x, y))
        if trackside_items:
            return trackside_items[0]
        anchors = self.layout.anchors_qtree.intersect((x - 2, y - 2, x + 2, y + 2))
        if anchors:
            return anchors[0]
        pieces = self.layout.pieces_qtree.intersect((x, y, x, y))
        if pieces:
            return pieces[0]

    def xy_to_layout(self, x, y):
        x = (
            x
            - self.drawing_options.offset[0]
            - self.drawing_area.get_allocated_width() / 2
        ) / self.drawing_options.scale
        y = (
            y
            - self.drawing_options.offset[1]
            - self.drawing_area.get_allocated_height() / 2
        ) / self.drawing_options.scale
        return x, y

    def draw(self, widget, cr: Context):
        width = widget.get_allocated_width()
        height = widget.get_allocated_height()

        layout_state = {
            "w": width,
            "h": height,
            "drawing_options": self.drawing_options,
            "epoch": self.layout.epoch,
        }

        if layout_state != self.last_layout_state:
            self.layout_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            layout_cr = cairo.Context(self.layout_surface)

            layout_cr.translate(
                width / 2 + self.drawing_options.offset[0],
                height / 2 + self.drawing_options.offset[1],
            )
            layout_cr.scale(self.drawing_options.scale, self.drawing_options.scale)

            self.draw_grid(layout_cr)
            self.draw_layout(self.layout, layout_cr)
            self.draw_points_labels(self.layout, layout_cr)
            self.draw_sensors(self.layout, layout_cr)
            self.last_layout_state = layout_state

        cr.set_source_surface(self.layout_surface)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Initial translation and scale
        cr.translate(
            width / 2 + self.drawing_options.offset[0],
            height / 2 + self.drawing_options.offset[1],
        )
        cr.scale(self.drawing_options.scale, self.drawing_options.scale)

        self.draw_highlight_layer(self.layout, cr)

        # self.draw_trains(self.layout, cr)

    def draw_grid(self, cr: Context):
        cr.set_line_width(1 / self.drawing_options.scale)

        for x in range(-10, 10):
            v = 0.7 if (x % 3) == 0 else 0.8
            cr.set_source_rgba(v, v, v, 0.4)
            cr.move_to(x * 32, -320)
            cr.line_to(x * 32, 320)
            cr.stroke()

        for y in range(-10, 10):
            v = 0.7 if (y % 3) == 0 else 0.8
            cr.set_source_rgba(v, v, v, 0.4)
            cr.move_to(-320, y * 32)
            cr.line_to(320, y * 32)
            cr.stroke()

    def draw_layout(self, layout: Layout, cr: Context):
        for piece in layout.pieces.values():
            self.draw_piece(piece, cr, self.drawing_options)

    def draw_highlight_layer(self, layout: Layout, cr: Context):
        if isinstance(self.highlight_item, Piece):
            self.draw_piece(self.highlight_item, cr, self.highlight_drawing_options)
        if isinstance(self.selected_item, Piece):
            self.draw_piece(self.selected_item, cr, self.selection_drawing_options)
        elif isinstance(self.selected_item, Anchor) and self.selected_item.position:
            cr.arc(
                self.selected_item.position.x,
                self.selected_item.position.y,
                3
                if any(
                    piece.placement and anchor_name == piece.anchor_names[0]
                    for piece, anchor_name in self.selected_item.items()
                )
                else 1,
                0,
                math.tau,
            )
            cr.set_source_rgb(0.2, 0.2, 1)
            cr.fill()
        elif (
            isinstance(self.selected_item, TracksideItem)
            and self.selected_item.position
        ):
            self.draw_sensor(
                self.selected_item, layout, cr, self.selection_drawing_options
            )

    def draw_piece(self, piece: Piece, cr: Context, drawing_options: DrawingOptions):
        if not piece.position:
            return

        cr.save()

        cr.translate(piece.position.x, piece.position.y)
        cr.rotate(piece.position.angle)

        piece.draw(cr, drawing_options)

        relative_positions = piece.relative_positions()

        for anchor_name, anchor in piece.anchors.items():
            # if anchor.position != piece.position + relative_positions[anchor_name] + Position(0, 0, math.pi):
            #     cr.move_to(0, 0)
            #     cr.line_to(anchor.position.x, anchor.position.y)
            #     cr.stroke()

            cr.save()

            cr.translate(
                relative_positions[anchor_name].x, relative_positions[anchor_name].y
            )
            cr.rotate(relative_positions[anchor_name].angle)

            if len(anchor) == 2:
                cr.set_source_rgb(1, 0.5, 0.5)
            else:
                cr.set_source_rgb(0.5, 1, 0.5)

            next_piece, next_anchor_name = anchor.next(piece)

            cr.arc(
                0,
                0,
                3
                if (piece.placement and anchor_name == piece.anchor_names[0])
                or (
                    next_piece
                    and next_piece.placement
                    and next_anchor_name == next_piece.anchor_names[0]
                )
                else 1,
                0,
                math.tau,
            )
            cr.fill()

            cr.restore()
        cr.restore()

    def draw_points_labels(self, layout: Layout, cr: Context):
        for i, piece in enumerate(layout.points):
            if not piece.position:
                continue
            cr.save()
            cr.set_font_size(4)
            cr.translate(
                *piece.position.as_matrix().transform_point(
                    4, -10 if piece.direction == "left" else 10
                )
            )
            cr.rectangle(-4, -4, 8, 8)
            cr.set_source_rgb(1, 1, 1)
            cr.fill_preserve()
            cr.set_source_rgb(0, 0, 0)
            cr.set_line_width(1)
            cr.stroke()
            cr.move_to(-2, 2)
            cr.show_text(str(i))
            cr.restore()

    def draw_sensors(self, layout: Layout, cr: Context):
        for sensor in layout.sensors.values():
            self.draw_sensor(sensor, layout, cr)

    def draw_sensor(
        self,
        sensor: Sensor,
        layout: Layout,
        cr: Context,
        drawing_options: DrawingOptions = None,
    ):
        if not sensor.position:
            return
        cr.save()
        cr.translate(sensor.position.x, sensor.position.y)
        cr.rotate(sensor.position.angle)

        sensor.draw(cr, drawing_options or self.drawing_options)

        cr.restore()

    def transform_track_point(self, track_point):
        px, py, angle = track_point.piece.point_position(
            track_point.anchor_name, track_point.offset
        )
        return self.piece_matrices[track_point.piece].transform_point(px, py)

    def point_back(self, track_point, distance):
        error = distance
        px, py = self.transform_track_point(track_point)
        for i in range(2):
            track_point = track_point - error
            px2, py2 = self.transform_track_point(track_point)
            new_distance = math.sqrt((px - px2) ** 2 + (py - py2) ** 2)
            error = distance - new_distance
        return track_point, (px2, py2)

    def draw_trains(self, layout: Layout, cr: Context):
        for train in layout.trains.values():
            car_start = train.position

            annotation = train.meta.get("annotation")

            for i, car in enumerate(train.cars):
                front_bogey_offset, rear_bogey_offset = car.bogey_offsets
                bogey_spacing = rear_bogey_offset - front_bogey_offset
                front_bogey_position = car_start - front_bogey_offset
                front_bogey_xy = self.transform_track_point(front_bogey_position)
                rear_bogey_position, rear_bogey_xy = self.point_back(
                    front_bogey_position, bogey_spacing
                )

                cr.save()
                cr.translate(front_bogey_xy[0], front_bogey_xy[1])
                cr.rotate(
                    math.pi
                    + math.atan2(
                        front_bogey_xy[1] - rear_bogey_xy[1],
                        front_bogey_xy[0] - rear_bogey_xy[0],
                    )
                )

                cr.set_source_rgb(*hex_to_rgb(train.meta.get("color", "#a0a0ff")))

                if i == 0 and annotation:
                    cr.move_to(0, -10)
                    cr.set_font_size(5)
                    cr.show_text(annotation)

                cr.set_line_width(4)
                cr.move_to(-front_bogey_offset, 0)
                cr.line_to(car.length - front_bogey_offset, 0)
                cr.stroke()

                cr.set_line_width(6)
                cr.move_to(1 - front_bogey_offset, 0)
                cr.line_to(car.length - front_bogey_offset - 1, 0)
                cr.stroke()

                if i == 0 and train.lights_on:
                    cr.set_source_rgba(1, 1, 0.2, 0.5)
                    for y in (-2.5, 2.5):
                        cr.move_to(-front_bogey_offset - 1, y)
                        cr.arc(
                            -front_bogey_offset - 1,
                            y,
                            10,
                            6 / 7 * math.pi,
                            math.pi * 8 / 7,
                        )
                        cr.close_path()
                        cr.fill()

                cr.restore()
                car_start = rear_bogey_position - (car.length - rear_bogey_offset + 1)
