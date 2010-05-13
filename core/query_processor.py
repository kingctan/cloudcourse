#!/usr/bin/python2.4
# Copyright 2010 Google Inc. All Rights Reserved.
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


"""Support for long running jobs that process entities returned by a query."""



import datetime
import logging
import pickle

from google.appengine.api import datastore_errors
from google.appengine.ext import db
from google.appengine.ext import deferred

from core import calendar
from core import models
from core import service_factory


SYNC_DATASTORE_ENTITIES = 'sync_datastore_entities'
SYNC_USER_SETTINGS = 'sync_user_settings'
SYNC_SCHEDULES_WITH_CALENDAR = 'sync_schedules_with_calendar'


class _QueryResultsWork(object):
  """Abstract base class for doing long duration work on query results."""
  NO_CURSOR = ''

  def __init__(self):
    self.__query_data = {}

  def Reset(self):
    """Clear the work progress information.

    Invocations to perform more work after this function is called will start
    the work over from beginning.
    """
    logging.info('Resetting work progress on %s', self._GetConfigName())
    self.__SaveProgressConfigEntity(_QueryResultsWork.NO_CURSOR)

  def PerformUnitWork(self):
    """Queries for a batch of entities and performs work.

    Returns:
      Boolean indicating if there could be more entities to work on.
    """
    query_cursor = _QueryResultsWork.NO_CURSOR
    progress_entity = self.__GetProgressConfigEntity()
    if progress_entity:
      query_cursor = progress_entity.config_value
      pickle_query_data = progress_entity.config_binary_value
      if pickle_query_data:
        self.__query_data = pickle.loads(pickle_query_data)

    # Construct query.
    work_query = self._GetQuery()

    if query_cursor != _QueryResultsWork.NO_CURSOR:
      logging.info('Setting query cursor of:%s', query_cursor)
      try:
        work_query.with_cursor(query_cursor)
      except datastore_errors.BadValueError:
        if self._IsResetOnCursorError():
          self.Reset()
        raise

    try:
      # Get entities to work on.
      entities_to_process = work_query.fetch(self._GetBatchSize())
    except datastore_errors.BadRequestError:
      if self._IsResetOnCursorError():
        self.Reset()
      raise

    # Perform work.
    more_work_pending = True
    if entities_to_process:
      logging.info('Starting to work on %d retrieved results',
                   len(entities_to_process))
      more_work_pending = self._WorkOnResults(entities_to_process)

      # Store progress.
      if more_work_pending:
        self.__SaveProgressConfigEntity(work_query.cursor())

    more_work_pending = more_work_pending and (len(entities_to_process) ==
                                               self._GetBatchSize())
    if not more_work_pending and self._IsResetOnWorkCompletion():
      self.Reset()
    return more_work_pending

  def EnqueueTasksForPendingWork(self):
    """Allow/Deny the enqueue of a new task to finish pending work."""
    return False

  def _GetQuery(self):
    """The db.Query that provides the entities to perform work on."""
    raise NotImplementedError

  def _WorkOnResults(self, entity_list):
    """Work function that performs idempotent work on the given entity list.

    Deriving classes should implement the work that needs to be done on the
    entities returned by the query in this function. Work done on each entity
    of the entity_list should be idempotent. i.e it is possible that the same
    entity is given to this function multiple times.

    Args:
      entity_list: List of db.Model that were queried in a batch for processing.

    Returns:
      False if the query should be considered as reached its end and further
      work should be suspended. Returning False will result in the cursor not
      moving on to the next set of query results and assume that no more work
      is pending at this time.
    """
    raise NotImplementedError

  def _GetConfigName(self):
    """Unique name of the configuration object tracking query progress."""
    return '%s-WorkProgress' % type(self).__name__

  def _GetBatchSize(self):
    """Number of entities to process for each unit of work."""
    return 20

  def _IsResetOnCursorError(self):
    """Restart the query from beginning when cursor bad request error occurs."""
    return False

  def _IsResetOnWorkCompletion(self):
    """Reset the cursor when it reaches the end of the query results."""
    return True

  def __GetProgressConfigEntity(self):
    """Provides the configuration that stores the query progress cursor."""
    return models.Configuration.get_by_key_name(self._GetConfigName())

  def __SaveProgressConfigEntity(self, query_cursor):
    """Stores the query progress cursor into a configuration."""
    config_name = self._GetConfigName()
    logging.info('Writing query progress config (name, cursor)=(%s, %s)',
                 config_name, query_cursor)
    self.__query_data = self.__query_data or {}
    config_binary_value = pickle.dumps(self.__query_data)
    query_progress_config = models.Configuration(
        key_name=config_name, config_key=config_name, config_value=query_cursor,
        config_binary_value=config_binary_value)
    query_progress_config.put()

  def _GetQueryData(self, key):
    """Get query data value for given key, None if not available."""
    return self.__query_data.get(key)

  def _SetQueryData(self, key, value):
    """Set query data value for given key."""
    self.__query_data[key] = value


class _SyncUserSettings(_QueryResultsWork):
  def _GetQuery(self):
    """Override base class method."""
    return models.GlearnUser.all()

  def _WorkOnResults(self, entity_list):
    """Override base class method."""
    models.GlearnUser.UpdateGlearnUserProperties(entity_list)
    db.put(entity_list)
    return True

  def EnqueueTasksForPendingWork(self):
    """Override base class method."""
    return True


class _SyncDatastoreModel(_QueryResultsWork):
  """Syncs a particular model type with an external storage/service."""
  _SYNC_LAG = 60

  def __init__(self, entity_class, *args, **kwargs):
    super(_SyncDatastoreModel, self).__init__(*args, **kwargs)
    self.__entity_class = entity_class

  def _GetConfigName(self):
    """Override base class method."""
    return '%s-DatastoreSyncProgress' % self.__entity_class.__name__

  def _GetQuery(self):
    """Override base class method."""
    return self.__entity_class.all().order('last_modified')

  def _GetBatchSize(self):
    """Override base class method."""
    return 20  # Sync 20 entities at a time.

  def _IsResetOnCursorError(self):
    """Override base class method."""
    return True  # On cursor error start sync from beginning.

  def _IsResetOnWorkCompletion(self):
    """Override base class method."""
    return False  # When cursor doesn't retrieve entities dont reset.

  def _WorkOnResults(self, entity_list):
    """Override base class method."""
    if (datetime.datetime.utcnow() - entity_list[-1].last_modified <
        datetime.timedelta(seconds=_SyncDatastoreModel._SYNC_LAG)):
      return False

    # Get the service that can write data to the external system.
    sync_service = service_factory.GetDatastoreSyncService()

    for entity in entity_list:
      sync_service.SyncEntity(entity)

    return True


class _SyncDatastoreExternal(_QueryResultsWork):
  """Syncs datastore entities with an external storage/service."""
  _model_hierarchy = [models.GlearnUser, models.Configuration,
                      models.Program, models.Activity,
                      models.AccessPoint, models.ActivitySchedule,
                      models.UserRegistration, models.ManagerApproval]

  def PerformUnitWork(self):
    """Override base class method."""
    sync_service = service_factory.GetDatastoreSyncService()
    for model_class in _SyncDatastoreExternal._model_hierarchy:
      if sync_service.IsModelSynced(model_class):
        entity_sync_work = _SyncDatastoreModel(model_class)
        more_entities_to_sync = entity_sync_work.PerformUnitWork()
        if more_entities_to_sync:
          return True

    return False

  def Reset(self):
    """Override base class method."""
    for model_class in _SyncDatastoreExternal._model_hierarchy:
      entity_sync_work = _SyncDatastoreModel(model_class)
      entity_sync_work.Reset()


class _SyncScheduleCalendar(_QueryResultsWork):
  """Syncs a schedule with google calendar."""

  _QUERY_LAST_MODIFIED = 'query_last_modified'
  _LAST_PROCESSED_TIME = 'last_processed_time'
  _SYNC_LAG = 60

  def __init__(self, *args, **kwargs):
    super(_SyncScheduleCalendar, self).__init__(*args, **kwargs)

  def _GetQuery(self):
    """Override base class method."""
    query = models.ActivitySchedule.all()
    last_modified = self._GetQueryData(
        _SyncScheduleCalendar._QUERY_LAST_MODIFIED)
    last_modified = last_modified or datetime.datetime.min
    query.filter('last_modified >=', last_modified)
    query.order('last_modified')

    return query

  def _GetBatchSize(self):
    """Override base class method."""
    return 4  # Sync 4 schedule calendars at most each time.

  def _IsResetOnCursorError(self):
    """Override base class method."""
    return True  # On cursor error start sync from beginning.

  def _IsResetOnWorkCompletion(self):
    """Override base class method."""
    return False  # When cursor doesn't retrieve entities don't reset.

  def _WorkOnResults(self, entity_list):
    """Override base class method."""
    # Not processing entities that were written in the last 1 minute since
    # this reduces the slippace we can have of entities missing in the query
    # and which will be written to the index soon.
    if (datetime.datetime.utcnow() - entity_list[-1].last_modified <
        datetime.timedelta(seconds=_SyncScheduleCalendar._SYNC_LAG)):
      return False

    for schedule in entity_list:
      logging.info('Performing a calendar sync for schedule:%s',
                   schedule.key())
      calendar.SyncScheduleCalendarEvent(schedule)
      self._SetQueryData(
          _SyncScheduleCalendar._LAST_PROCESSED_TIME, schedule.last_modified)
      logging.info('Completed calendar sync with schedule:%s',
                   schedule.key())
    return True

  def Reset(self):
    """Override base class method."""
    new_query_time = self._GetQueryData(
        _SyncScheduleCalendar._LAST_PROCESSED_TIME)
    new_query_time = new_query_time or datetime.datetime.min
    self._SetQueryData(_SyncScheduleCalendar._QUERY_LAST_MODIFIED,
                       new_query_time)
    self._SetQueryData(_SyncScheduleCalendar._LAST_PROCESSED_TIME,
                       new_query_time)

    super(_SyncScheduleCalendar, self).Reset()


def _GetQueryWorkClass(work_name):
  """Maps work names with relevant QueryWorkObject names, None if not mapped."""
  work_name_map = {
      SYNC_USER_SETTINGS: _SyncUserSettings,
      SYNC_DATASTORE_ENTITIES: _SyncDatastoreExternal,
      SYNC_SCHEDULES_WITH_CALENDAR: _SyncScheduleCalendar,
  }
  return work_name_map.get(work_name)


def PerformQueryWork(work_name):
  """Performs a possibly long running work based off a query.

  Args:
    work_name: Str name of the work that identifies the work to be done.

  Returns:
    True if more work is pending, False if there is no more work to be done.
  """
  query_work_class = _GetQueryWorkClass(work_name)
  assert query_work_class is not None
  work_instance = query_work_class()

  more_work_possible = work_instance.PerformUnitWork()
  if more_work_possible and work_instance.EnqueueTasksForPendingWork():
    deferred.defer(PerformQueryWork, work_name)
    logging.info('Deferred new task to finish remaining work.')

  return more_work_possible


def ResetQueryWork(work_name):
  """Resets query work progress config."""
  query_work_class = _GetQueryWorkClass(work_name)
  query_work_class().Reset()
