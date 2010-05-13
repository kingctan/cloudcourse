#!/usr/bin/python2.4
# Copyright 2009 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Module to manage retrieval of access points."""

import logging

from django.utils import simplejson

from core import service_interfaces

_ROOMS_JSON_FILE = 'core/data/rooms.json'


class _JsonRoomInfoService(service_interfaces.RoomInfoService):
  """Json rooms file based room info service."""

  def GetRoomInfoMulti(self, start_offset, num_rooms):
    """Overriding RoomInfoService method."""
    rooms = self._GetRoomsFromJsonFile(_ROOMS_JSON_FILE,
                                       start_offset, num_rooms)
    return [self._CreateRoomInfo(room) for room in rooms]

  def _GetRoomsFromJsonFile(self, json_file_name, start_offset, num_rooms):
    """Gets rooms from json data file.

    Args:
      json_file_name: str rooms json data file.
      start_offset: int offset of the first room.
      num_rooms: int number of rooms to read.

    Example room information dict:
      {
       "id":"121",
       "name":"Room XYZ",
       "email":"google.com_XXX@resource.calendar.google.com",
       "loc":"Mountain View",
       "c-c":"US-MTV"
      }

    Returns:
      A list of room information dicts as shown above.
    """
    logging.info('Reading %d rooms, starting at offset %d', num_rooms,
                 start_offset)
    f = open(json_file_name, 'r')
    json_room_list = simplejson.loads(f.read())
    json_room_list = json_room_list[start_offset:start_offset+num_rooms]

    logging.info('Returning %d rooms from local file', len(json_room_list))
    return json_room_list

  def _CreateRoomInfo(self, room):
    """Create a service_interfaces.RoomInfo from the json room data.

    Args:
      room: A room data as returned by _GetRoomsFromJsonFile.

    Returns:
      A new service_interfaces.RoomInfo instance.
    """
    name = room['name']
    country_city = room['c-c'].split('-')  # us-nyc-chel.
    country_city = country_city[:2]  # us, nyc.
    assert len(country_city) == 2
    country_city = '-'.join(country_city)  # 'us-nyc'

    calendar_email = room['email']
    location = room['loc']
    if not location:
      logging.error('No location for room [%s]', name)

    return service_interfaces.RoomInfo(
        room_id=room['id'], name=name,
        country_city=country_city, calendar_email=calendar_email,
        location=location)
