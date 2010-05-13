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

import datetime
import logging
import pickle

from google.appengine.api import memcache
from google.appengine.ext import db
from google.appengine.ext import deferred

from core import models
from core import service_factory
from core import timezone_helper
from core import utils


_ACCESS_POINTS_INFO_KEY_PREFIX = 'access_points_info'
_USER_LOCATIONS_MEMCACHE_KEY = 'user_locations_from_access_points'
_CONFERENCE_ROOMS_RUN_KEY_NAME = 'conference_rooms_run_key_name'


def RemoveOldConferenceRooms(run_id):
  """Delete old access points that aren't available through rooms info service.

  Args:
    run_id: The room collection process run id for which this removal process
        step belongs to.
  """
  # If the run_id is no longer active just return success.
  config_value = _GetConferenceRoomRunConfigValue()
  if config_value['run_id'] != run_id:
    logging.info('Expired run_id? run=%s,datastore=%s', run_id,
                 config_value['run_id'])
    return

  run_start_time = config_value['run_start_time']

  query = models.AccessPoint.all()
  utils.AddFilter(query, 'last_modified <', run_start_time)
  utils.AddFilter(query, 'type =', utils.AccessPointType.ROOM)
  utils.AddFilter(query, 'deleted =', 0)

  # TODO(user): Lets be more careful in deleting access points.
  # We might have to send emails warning the deletion of the rooms.
  
  for access_point in query:
    access_point.Delete()

  # Make sure eventually we load this information into the access points info.
  deferred.defer(UpdateAccessPointsInfo, utils.AccessPointType.ROOM)


def StartRoomsSync(run_id, batch_size=40):
  """Start workflow to sync models.AccessPoints with RoomInfoService rooms.

  Starts workflow to read rooms from RoomInfoService and sync with access point
  entities in the datastore. First rooms are read in batches and written to
  datastore. Second old access points that aren't returned by RoomInfoService
  are deleted.

  Args:
    run_id: Unique str id representing the workflow.
    batch_size: int number of rooms queries in a batch and written to datastore.
  """
  _SyncConferenceRooms(run_id, 0, batch_size)


def CreateConferenceRoomRunConfig(run_id):
  """Creates and stores a conference room run config entity.

  Args:
    run_id: str unique id to be associated with this run config.
  """
  config_value = {'run_id': run_id,
                  'run_start_time': datetime.datetime.now()}
  config_value_str = pickle.dumps(config_value)
  run_entity = models.Configuration(key_name=_CONFERENCE_ROOMS_RUN_KEY_NAME,
                                    config_key=_CONFERENCE_ROOMS_RUN_KEY_NAME,
                                    config_value=config_value_str)
  run_entity.put()


def _SyncConferenceRooms(run_id, start_offset, batch_size):
  """StartRoomsSync work flow implementation.

  Args:
    run_id: Unique str id representing the workflow.
    start_offset: int, zero indexed start offset of the rooms to sync.
    batch_size: int number of rooms to fetch at a time starting at start_offset.
  """
  logging.info('Entering _SyncConferenceRooms')

  # If the run_id is no longer active just return success.
  config_value = _GetConferenceRoomRunConfigValue()
  if config_value['run_id'] != run_id:
    logging.info('Expired run_id? run=%s,datastore=%s', run_id,
                 config_value['run_id'])
    return

  num_rooms_written = StoreConferenceRoomsAsAccessPoints(
      start_offset, batch_size)

  if num_rooms_written:  # There might be more rooms.
    deferred.defer(_SyncConferenceRooms, run_id,
                   start_offset+num_rooms_written, batch_size)
  else:  # All the rooms have been loaded.
    deferred.defer(RemoveOldConferenceRooms, run_id)

  logging.info('Exiting _SyncConferenceRooms')


def StoreConferenceRoomsAsAccessPoints(start_offset, batch_size):
  """Queries RoomInfoService for rooms and stores them as access points.

  Args:
    start_offset: The int offset after which the rooms should be queried from.
    batch_size: Int number of rooms to fetch.

  Returns:
    Int number of access points written.
  """
  room_service = service_factory.GetRoomInfoService()
  room_info_list = room_service.GetRoomInfoMulti(start_offset, batch_size)

  # Create/Overwrite models.AccessPoints entities for room info.
  db.put([_CreateAccessPointFromRoomInfo(r) for r in room_info_list])

  return len(room_info_list)


def _CreateAccessPointFromRoomInfo(room_info):
  """Creates models.AccessPoint entity for the given room info."""

  key_name = 'room_%s' % room_info.room_id

  tags = room_info.country_city.split('-')  # us-nyc.
  tags = tags[::-1]  # nyc, us. nyc is the 'display tag'.
  if len(tags) != 2:  # Unknown format.
    logging.warning('Unknown country-city format = %s, room_id = %s',
                    room_info.country_city, room_info.room_id)

  timezone = timezone_helper.GetTimezoneForLocation(room_info.country_city)
  if not timezone:
    # Default to UTC.
    timezone = 'UTC'
    logging.warning('Can not lookup timezone for %s', room_info.country_city)

  return models.AccessPoint(key_name=key_name, deleted=0,
                            type=utils.AccessPointType.ROOM,
                            uri=room_info.name, rules=[], tags=tags,
                            location=room_info.location,
                            calendar_email=room_info.calendar_email,
                            timezone=utils.Timezone(timezone))


def _GetConferenceRoomRunConfigValue():
  """Load and return conference room collection run information.

  Returns:
    A dict with keys run_id' and 'run_start_time'. Value for 'run_id' is the
        current run str identifier. Value for 'run_start_time' is the datetime
        at which the current run started.
  """
  run_config = models.Configuration.get_by_key_name(
      _CONFERENCE_ROOMS_RUN_KEY_NAME
  )
  config_value = pickle.loads(str(run_config.config_value))

  return config_value


def UpdateAccessPointsInfo(access_point_type):
  """Builds and stores access points info in a models.Configuration object.

  Args:
    access_point_type: utils.AccessPointType type of access points to load.

  Returns:
    Dict with keys 'keys', 'uris', 'timezone_names'. Values are arrays of string
    keys, uris and timezone names. For example: return_value['uris'][5],
    return_value['key'][5] are the uri and key of the same access point.
  """
  logging.info('Entering UpdateAccessPointsInfo')

  last_uri = None
  batch_query_size = 1000
  retrieved_count = batch_query_size
  access_points = []

  while retrieved_count == batch_query_size:
    logging.info('Querying for access points with uri > %s, batch size = %d',
                 last_uri, batch_query_size)

    query = db.Query(models.AccessPoint)
    utils.AddFilter(query, 'type =', access_point_type)
    if last_uri:
      utils.AddFilter(query, 'uri >', last_uri)
    query.order('uri')

    query_fetch = query.fetch(batch_query_size)
    retrieved_count = len(query_fetch)
    if query_fetch: last_uri = query_fetch[-1].uri
    access_points.extend(query_fetch)

  access_points_info = {
      'keys': [str(ap.key()) for ap in access_points],
      'uris': [ap.uri for ap in access_points],
      'timezone_names': [ap.timezone.name for ap in access_points],
      'tags': [ap.tags for ap in access_points],
  }

  # Store access points info in datastore config.
  key_name = _GetAccessPointInfoConfigKeyName(access_point_type)

  config_entity = models.Configuration(
      key_name=key_name, config_key='', config_value='',
      config_binary_value=pickle.dumps(access_points_info, 2))

  config_entity.put()

  logging.info('Exiting UpdateAccessPointsInfo. %s access points loaded',
               len(access_points))
  return access_points_info


def _GetAccessPointInfoConfigKeyName(access_point_type):
  return '%s_%s' % (_ACCESS_POINTS_INFO_KEY_PREFIX, access_point_type)


def GetAccessPointsInfo(access_point_type):
  """Gets access points info object for a given type of access point.

  Args:
    access_point_type: utils.AccessPointType type of access points to get.

  Returns:
    The data provided by UpdateAccessPointsInfo if available else None if not
    able to provide the access points info.
  """
  logging.info('Entering GetAccessPointsInfo.')

  key_name = _GetAccessPointInfoConfigKeyName(access_point_type)
  key = db.Key.from_path(models.Configuration.kind(), key_name)

  config_entity = db.get(key)
  if config_entity is None:
    logging.debug('Access points info config is not present')
    result = UpdateAccessPointsInfo(access_point_type)
  else:
    logging.debug('Trying to deserialize access points info from config.')
    result = pickle.loads(config_entity.config_binary_value)

  logging.info('Exiting GetAccessPointsInfo.')
  return result


def GetRoomLocations():
  """Returns country-city location strings for all rooms.

  Returns:
    List of sorted country-city locations. Example ['US-MTV', 'US-NYC',...]
  """
  user_locations = memcache.get(_USER_LOCATIONS_MEMCACHE_KEY)
  if user_locations is None:  # Memcache miss.
    access_points_info = GetAccessPointsInfo(utils.AccessPointType.ROOM)

    user_locations = ['-'.join(tags[::-1]).upper()
                      for tags in access_points_info['tags'] if tags]
    user_locations = list(set(user_locations))
    user_locations = sorted(user_locations)

    # Store in memcache with expiration set to a day.
    memcache.set(_USER_LOCATIONS_MEMCACHE_KEY, user_locations, time=24*60*60)

  return user_locations

