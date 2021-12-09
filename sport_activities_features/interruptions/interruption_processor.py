from datetime import timedelta

import overpy
from dotmap import DotMap
from geopy import distance

from sport_activities_features.interruptions.exercise import TrackSegment
from sport_activities_features.interruptions.exercise_event import EventType, EventStats, ExerciseEvent, \
    EventDetailType, EventLocation, EventDetail
from sport_activities_features.interruptions.overpass import Overpass, CoordinatesBox


class InterruptionProcessor():
    def __init__(self, time_interval=60, min_speed=2,
                 overpass_api_url="https://lz4.overpass-api.de/api/interpreter"):
        """
        Args:
            time_interval: Record x seconds before and after the event
            min_speed: Speed threshold for the event to trigger (min_speed = 2 -> trigger if speed less than 2km/h)
            overpass_api_url: Overpass API url, self host if you want to make a lot of requests
        """
        self.time_interval = time_interval
        self.min_speed = min_speed
        self.overpass_api_url = overpass_api_url

    def __determine_event_type(self, event_stats: EventStats, lines: [TrackSegment]):
        """
        :param event_stats:
        :param lines:
        :return: Returns Enum if this ia a event of the start, end or actual interruption.
        """
        if event_stats.index_start == 0:
            return EventType.EXERCISE_START
        elif event_stats.index_end >= len(lines) - 1:
            return EventType.EXERCISE_STOP
        else:
            return EventType.EXERCISE_PAUSE

    def __data_to_lines(self, tcx_data) -> [TrackSegment]:
        lines: [TrackSegment] = []
        for i in range(len(tcx_data['positions'])):
            if (i != 0):
                point_a = DotMap()
                point_b = DotMap()
                point_a.latitude = tcx_data['positions'][i - 1][0]
                point_a.longitude = tcx_data['positions'][i - 1][1]
                point_a.time = tcx_data['timestamps'][i - 1]

                point_b.latitude = tcx_data['positions'][i][0]
                point_b.longitude = tcx_data['positions'][i][1]
                point_b.time = tcx_data['timestamps'][i]

                if len(tcx_data['altitudes']) == len(tcx_data['positions']):
                    point_a.elevation = tcx_data['altitudes'][i - 1]
                    point_b.elevation = tcx_data['altitudes'][i]

                if len(tcx_data['heartrates']) == len(tcx_data['positions']):
                    point_a.heartrate = tcx_data['heartrates'][i - 1]
                    point_b.heartrate = tcx_data['heartrates'][i]

                if len(tcx_data['distances']) == len(tcx_data['positions']):
                    point_a.distance = tcx_data['distances'][i - 1]
                    point_b.distance = tcx_data['distances'][i]

                if len(tcx_data['speeds']) == len(tcx_data['positions']):
                    point_a.distance = tcx_data['speeds'][i - 1]
                    point_b.distance = tcx_data['speeds'][i]

                prev_speed = None
                if (i > 1):
                    prev_speed = lines[-1].speed
                ts = TrackSegment(point_a, point_b, prev_speed)
                lines.append(ts)

        return lines

    def events(self, lines, classify=False) -> [ExerciseEvent]:
        """
        Args:
            lines: [TrackSegment] | tcx_data | gpx_data
            classify:

        Returns:

        """
        events = self.parse_events(lines)
        if classify is True:
            classified_events = []
            for e in events:
                classified_events.append(self.classify_event(e))
            return classified_events
        return events

    def parse_events(self, lines) -> [ExerciseEvent]:
        """
        Parses all events and returns ExerciseEvent array.
        :param lines:
        :return:

        """
        stoppedTimestamp = 0
        if type(lines) is dict:
            lines = self.__data_to_lines(lines)
        eventList: [ExerciseEvent] = []
        index = 0
        while index < len(lines):
            event_stats = EventStats()
            if lines[index].speed.km < self.min_speed:
                # add event
                event = ExerciseEvent([], [], [], "", EventType.UNDEFINED)
                event_stats.index_start = index
                event_stats.timestamp_mid_start = lines[index].point_a.time
                while index < len(lines) and lines[index].speed.km < self.min_speed:
                    event.add_event(lines[index])
                    event_stats.timestamp_mid_end = lines[index].point_b.time
                    index += 1
                event_stats.index_end = index - 1
                event_stats.timestamp_mid = event_stats.timestamp_mid_start + (
                        event_stats.timestamp_mid_end - event_stats.timestamp_mid_start) / 2
                event.event_type = self.__determine_event_type(event_stats, lines)
                event_stats.timestamp_post_end = event_stats.timestamp_mid_end + timedelta(
                    seconds=(self.time_interval + 1))
                event_stats.timestamp_pre_start = event_stats.timestamp_mid_start - timedelta(
                    seconds=self.time_interval)
                # add post event
                indexPost = index
                while indexPost < len(lines) and lines[indexPost].point_a.time < event_stats.timestamp_post_end:
                    event.add_post_event(lines[indexPost])
                    indexPost += 1
                indexStartPre = 0
                while lines[indexStartPre].point_a.time < event_stats.timestamp_pre_start:
                    indexStartPre += 1
                # add pre event
                while indexStartPre < len(lines) and lines[
                    indexStartPre].point_a.time <= event_stats.timestamp_mid_start:
                    event.add_pre_event(lines[indexStartPre])
                    indexStartPre += 1
                eventList.append(event)
            index += 1
        return eventList

    def classify_event(self, event: ExerciseEvent):
        op = Overpass(self.overpass_api_url)
        event: ExerciseEvent
        box = CoordinatesBox(event=event)
        possible_intersections: overpy.Result = op.identify_intersections(event, box)
        # [intersection][point]
        (events, intersections) = (len(event.event), len(possible_intersections.nodes))
        min_distance = 1000000
        for e in range(0, events):

            for i in range(0, intersections):
                event_location = (event.event[e].point_a.latitude, event.event[e].point_a.longitude)
                intersection_location = (
                    float(possible_intersections.nodes[i].lat), float(possible_intersections.nodes[i].lon))
                calculated_distance = distance.distance(event_location, intersection_location).meters
                if (calculated_distance < 22 and calculated_distance < min_distance):
                    min_distance = calculated_distance
                    event.event_detail = EventDetail(EventLocation(longitude=possible_intersections.nodes[i].lat,
                                                                   latitude=possible_intersections.nodes[i].lon),
                                                     type=EventDetailType.INTERSECTION)
        return event
