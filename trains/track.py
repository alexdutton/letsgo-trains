import collections
import cmath
import math
import uuid
from numbers import Number
from typing import Dict, Tuple

from trains.registry_meta import WithRegistry

Position = collections.namedtuple('Position', ('x', 'y', 'angle'))


class Anchor(dict):
    def __init__(self, *args, id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.id = id or str(uuid.uuid4())

    def __setitem__(self, key, value):
        assert key in self or len(self) < 2
        super().__setitem__(key, value)

    def __iadd__(self, other):
        # Neither anchor is already connected
        assert len(self) == 1 and len(other) == 1

        assert set(self) != set(other)
        for track_piece, anchor_name in other.items():
            track_piece.anchors[anchor_name] = self
        self.update(other)
        return self

    def next(self, piece):
        """Return the piece other than `piece` connected at this anchor"""
        for other_piece, anchor_name in self.items():
            if piece != other_piece:
                return other_piece, anchor_name
        else:
            return None, None

class TrackPiece(WithRegistry):
    registry_type = None
    anchor_names = ()
    placement = None

    def __init__(self, placement: Position=None, **kwargs):
        self.anchors = {anchor_name: Anchor({self: anchor_name})
                        for anchor_name in self.anchor_names}
        self.placement = placement
        self.claimed_by = None
        self.reservations = {}
        super().__init__(**kwargs)

    def traversals(self, anchor_from: str) -> Dict[str, Tuple[Number, bool]]:
        return {}

    def available_traversal(self, anchor_name):
        for anchor_name, (distance, available) in self.traversals(anchor_name).items():
            if available:
                return anchor_name, distance

    layout_priority = float('inf')

    @classmethod
    def get_layout_options(cls):
        return []

class Straight(TrackPiece):
    anchor_names = ('in', 'out')
    registry_type = 'straight'
    label = 'straight'

    def __init__(self, length: int=16, **kwargs):
        self.length = length
        super().__init__(**kwargs)

    def traversals(self, anchor_from):
        return {'out' if anchor_from == 'in' else 'in': (self.length, True)}

    layout_priority = 10

    @classmethod
    def get_layout_options(cls):
        return [
            {'length': 16, 'label': 'Straight'},
            {'length': 8, 'label': 'Half-straight'},
            {'length': 4, 'label': 'Quarter-straight'},
        ]


class Curve(TrackPiece):
    anchor_names = ('in', 'out')
    registry_type = 'curve'
    label = 'curve'
    ldraw_id = '53400'

    def __init__(self, radius: int=40, per_circle: int=16, direction: str='left', **kwargs):
        self.radius = radius
        self.per_circle = per_circle
        self.direction = direction
        super().__init__(**kwargs)

    def traversals(self, anchor_from):
        return {'out' if anchor_from == 'in' else 'in': (math.tau * self.radius / self.per_circle, True)}

    layout_priority = 20

    @classmethod
    def get_layout_options(cls):
        return [
            {'radius': 40, 'per_circle': 16, 'label': 'Curve'},
            {'radius': 40, 'per_circle': 32, 'label': 'Curve (half)'},
            {'radius': 24, 'per_circle': 16, 'label': 'R24 curve'},
            {'radius': 56, 'per_circle': 16, 'label': 'R56 curve'},
            {'radius': 72, 'per_circle': 32, 'label': 'R72 curve'},
        ]


def _bezier(xy1, xy2, xy3, t):
    (x1, y1), (x2, y2), (x3, y3) = xy1, xy2, xy3
    return (3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t ** 2 * x2 + t ** 3 * x3,
            3 * (1 - t) ** 2 * t * y1 + 3 * (1 - t) * t ** 2 * y2 + t ** 3 * y3)


def _distance(xy1, xy2):
    (x1, y1), (x2, y2) = xy1, xy2
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


class Points(TrackPiece):
    anchor_names = ('in', 'branch', 'out')
    registry_type = 'points'
    label = 'points'

    def __init__(self, direction: str='left', state: str='out', **kwargs):
        self.direction = direction
        self.state = state
        super().__init__(**kwargs)

        # Bezier curve control points for the branch
        self.control_points = [(16, 0), (12, 3.4)]
        self.branch_point = cmath.rect(40, math.tau * 5/16) + 48 - 24j
        self.branch_point = self.branch_point.real, self.branch_point.imag

        intermediate_branch_point_count = 1000
        intermediate_branch_lengths = []
        branch_length = 0
        for t in range(1, intermediate_branch_point_count + 1):
            branch_length += _distance(self.branch_bezier(t / intermediate_branch_point_count),
                                       self.branch_bezier((t + 1) / intermediate_branch_point_count))
            intermediate_branch_lengths.append(branch_length)

        self.branch_length = branch_length

        self.intermediate_branch_t = [0]
        for i in range(1, intermediate_branch_point_count):
            t = i / intermediate_branch_point_count
            x, y = intermediate_branch_lengths[i-1:i+1]
            if intermediate_branch_lengths[i-1] < self.branch_length * len(self.intermediate_branch_t) / 100 <= intermediate_branch_lengths[i]:
                self.intermediate_branch_t.append(t)

    def branch_bezier(self, t):
        return _bezier(*self.control_points, self.branch_point, t)

    def traversals(self, anchor_from):
        traversals = {}
        if anchor_from == 'in':
            return {
                'out': (32, self.state == 'out'),
                'branch': (self.branch_length, self.state == 'branch'),
            }
        elif anchor_from == 'out':
            return {'in': (32, True)}
        elif anchor_from == 'branch':
            return {'in': (self.branch_length, True)}

    layout_priority = 30

    @classmethod
    def get_layout_options(cls):
        return [
            {'direction': 'left', 'label': 'Points (left)'},
            {'direction': 'right', 'label': 'Points (right)'},
        ]



class Crossover(TrackPiece):
    anchor_names = ('in', 'left', 'right', 'out')
    registry_type = 'crossover'
    label = 'crossover'

    def __init__(self, length: int=16, **kwargs):
        self.length = length
        super().__init__(**kwargs)

    def traversals(self, anchor_from):
        return {self.anchor_names[3 - self.anchor_names.index(anchor_from)]: (self.length, True)}

    layout_priority = 40

    @classmethod
    def get_layout_options(cls):
        return [
            {'label': 'Crossover'},
            {'length': 8, 'label': 'Crossover (short)'},
        ]

