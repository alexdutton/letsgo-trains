from unittest import TestCase

from trains.routeing import Router
from trains.track import Straight, Points
from trains.train import Train, TrackPoint


class RouteingTestCase(TestCase):
    def test_branch(self):
        straight, points, branch_straight, mainline_straight = \
            Straight(), Points(), Straight(), Straight()
        straight.anchors['out'] += points.anchors['in']
        points.anchors['branch'] += branch_straight.anchors['in']
        points.anchors['out'] += mainline_straight.anchors['in']

        router = Router()
        choices = router.route(Train(length=100),
                               TrackPoint(straight, 'in', 4),
                               TrackPoint(branch_straight, 'in', 10))
        print(choices)

    def test_branch_with_converge(self):
        straight, points_one, points_two, final_straight = \
            Straight(), Points(), Points(), Straight()
        straight.anchors['out'] += points_one.anchors['in']
        points_one.anchors['branch'] += points_two.anchors['branch']
        points_one.anchors['out'] += points_two.anchors['out']
        points_two.anchors['in'] += final_straight.anchors['in']

        router = Router()
        choices = router.route(Train(length=100),
                               TrackPoint(straight, 'in', 4),
                               TrackPoint(final_straight, 'in', 10))
        print(choices)

