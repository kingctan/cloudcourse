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


"""Utility and constant classes."""



# Suppress pylint invalid import order
# pylint: disable-msg=C6203
import datetime
import logging
import os
import re
import time

from django import http
from django.utils import translation
from google.appengine.api import users
from google.appengine.ext import db

import pytz
from ragendja import dbutils

from core import errors
from core import request_cache

# Email validation taken from django  (can't use directly because of import
# dependencies) contrib/auth/management/commands/createsuperuser
EMAIL_RE = re.compile(
    r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"
    r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|'
    r'\\[\001-\011\013\014\016-\177])*"'
    r')@(?:[A-Z0-9-]+\.)+[A-Z]{2,6}$', re.IGNORECASE)  # domain

# Max number of entities to fetch in a query.
# TODO(user): we should not use this anymore but instead iterate on query.
NUM_FETCH = 1000
_ = translation.ugettext


class ChoiceBase(object):
  """The base which allows classes to define string attributes choices.

  A child class can definite attributes having string values which will be
  collected using the Choices() classmethod. Helps emulate a simple string enum
  style class. The child classes can be used to extend and form a superset
  choice class.

  Example:

    class Move1D(ChoiceBase):
      LEFT='go_left'
      RIGHT='go_right'

    class Move2D(Move1D)
      FOWARD='go_forward'
      BACKWARD='go_backward'

    Move1D.Choices() == ['go_left', 'go_right']
    Move2D.Choices() == ['go_left', 'go_right', 'go_forward', 'go_backward']
  """

  @classmethod
  def Choices(cls):
    """Determines all the string valued enum choices present in a class.

    Returns:
        A set of acceptable string value choices.
    """
    attr = '_choice_attr_' + cls.__name__
    if hasattr(cls, attr):
      return getattr(cls, attr)

    choices = set()
    for (k, v) in cls.__dict__.items():
      if not k.startswith('_') and issubclass(type(v), (str, unicode)):
        choices.add(v)
    for base in cls.__bases__:
      if issubclass(base, ChoiceBase) and base is not ChoiceBase:
        choices = set.union(choices, base.Choices())
    setattr(cls, attr, choices)

    return choices


class RegistrationStatus(ChoiceBase):
  """The valid states of models.UserRegistration.status.

  Attributes:
    ENROLLED: Status that a user is enrolled and need to attend activity.
    UNREGISTERED: Status that a registered user is now unregistered.
    WAITLISTED: The user is registered but doesn't have all enroll requirements.

  Natural Transitions:
    ENROLLED -> UNREGISTERED
    WAITLISTED -> ENROLLED, UNREGISTERED
    None, UNREGISTERED -> ENROLLED, WAITLISTED

  Begin States:
    States after which a new registration cycle and time-line can be started:
    UNREGISTERED
    None
  """

  ENROLLED = 'enrolled'
  UNREGISTERED = 'unregistered'
  WAITLISTED = 'waitlisted'

  # Dictionary containing state transitions. The keys are the begin states and
  # the values are the list of states possible to transition to. The list is
  # ordered by lower to higher precedence for when different rules disagree
  # on what transition they will approve.
  VALID_TRANSITIONS = {
      None: [ENROLLED, WAITLISTED, None],
      ENROLLED: [UNREGISTERED, ENROLLED],
      UNREGISTERED: [ENROLLED, WAITLISTED, UNREGISTERED],
      WAITLISTED: [ENROLLED, UNREGISTERED, WAITLISTED],
  }

  @classmethod
  def BeginStates(cls):
    """Return states after which new registration cycle can start."""
    return [cls.UNREGISTERED, None]

  @classmethod
  def IsValidTransition(cls, begin_state, end_state):
    if begin_state == end_state:
      return True

    ret = begin_state in cls.VALID_TRANSITIONS
    ret = ret and end_state in cls.VALID_TRANSITIONS[begin_state]
    return ret


class RegistrationAttend(ChoiceBase):
  """The valid states of models.UserRegistration.attendance.

  Attributes:
    ATTENDED: Status that the user attended the activity.
    NO_SHOW: Status that an enrolled user did not come to the activity.
    UNKNOWN: The attendance status is unknown.
  """

  ATTENDED = 'attended'
  NO_SHOW = 'no_show'
  UNKNOWN = 'unknown'


class EmployeeType(ChoiceBase):
  """Represents an employee type.

  Attributes:
    EMPLOYEE: Full time regular employees.
    INTERN: Interns.
    CONTRACTOR: Contractors.
    VENDOR: Vendors.

    DISPLAY_MAP: Maps employee types to display values on forms.
  """

  EMPLOYEE = 'employee'
  INTERN = 'intern'
  CONTRACTOR = 'contractor'
  VENDOR = 'vendor'
  OTHER = 'other'

  DISPLAY_MAP = {
      EMPLOYEE: _('Employee'),
      INTERN: _('Intern'),
      CONTRACTOR: _('Contractor'),
      VENDOR: _('Vendor')}


class RegistrationConfirm(ChoiceBase):
  """Valid states of models.UserRegistration.confirmed.

  Marks UserRegistration entities confirmed by the off-line process. The offline
  process processes registration entities that are in READY state only, after
  processing they are changed to PROCESSED state or deleted if processed entity
  is an unregistration. NOT_READY is used for creating entities that we don't
  want the offline process to process.

  Attributes:
    NOT_READY: UserRegistration entity is not ready for off-line processing.
    READY: UserRegistration entity is ready for off-line processing.
    PROCESSED: Enrolled/waitlisted UserRegistration has been processed off-line.
  """

  NOT_READY = 'not_ready'
  READY = 'ready'
  PROCESSED = 'processed'


class RegistrationActive(ChoiceBase):
  """Valid states of models.UserRegistration.active.

  Only enrolled/waitlisted user registrations from which the user did not
  unregister from are marked with 'ACTIVE'. The rest are marked 'INACTIVE'. This
  hence marks all the relevant registrations that the class roster needs. The
  user registrations that are in transition(NOT_READY RegistrationConfirm state)
  are also marked 'INACTIVE' since they are irrelevant for a roster.

  Attributes:
    ACTIVE: UserRegistration entity is the most current for user,activity.
    INACTIVE: UserRegistration entity is not active.
  """

  ACTIVE = 'active'
  INACTIVE = 'inactive'


class AccessPointType(ChoiceBase):
  """Valid choices of models.AccessPoint.type.

  Attributes:
    ROOM: Physical room like NYC-4th-Lincoln Center.
    VC: Video Conference (user can dial in).
  """

  ROOM = 'room'
  VC = 'vc'


class LockData(dbutils.FakeModel):
  """A FakeModel class that can be stored in the lock entity for shared data."""

  fields = ('data',)

  def __init__(self, data):
    self.data = data


class LockModel(db.Model):
  """Model object that represents a lock.

  Attributes:
    expire_time: Time after which the lock should be considered available.
  """

  expire_time = db.DateTimeProperty(required=True)
  lock_data = dbutils.FakeModelProperty(LockData)


class DbLock(object):
  """Lock implementation using datastore transactions on LockModel entities."""

  __MAX_LOCK_MILLISECONDS = 31000
  __SLEEP_SECONDS = 0.1

  def __init__(self, lock_name, try_count=0, sleep_seconds=__SLEEP_SECONDS,
               expire_milliseconds=None):
    """Initialize a datastore lock.

    Args:
      lock_name: The string lock name that acts as lock identifier.
      try_count: The number of times to try to acquire a lock, 0 will try until
          lock is acquired.
      sleep_seconds: Seconds to sleep between failed lock acquire failures.
      expire_milliseconds: Number of milliseconds after which the lock is
          released automatically. Default is __MAX_LOCK_MILLISECONDS.
    """
    self._lock_key = db.Key.from_path(LockModel.kind(), lock_name)
    self._acquired_lock = None
    self._try_count = try_count
    self._sleep_seconds = sleep_seconds

    if expire_milliseconds is None:
      expire_milliseconds = self.__MAX_LOCK_MILLISECONDS
    self._expire_timedelta = datetime.timedelta(
        milliseconds=expire_milliseconds
    )

  def RunSynchronous(self, run_func, *args, **kwargs):
    """Runs a given function under the mutual exclusion provided by the lock."""
    try:
      self.AcquireLock()
      return run_func(*args, **kwargs)
    finally:
      self.ReleaseLock()

  def AcquireLock(self, lock_data=None):
    """Acquire a datastore lock.

    Args:
      lock_data: The data that should be stored in the lock if a new lock is
      being created.

    Returns:
      The lock data of the acquired lock if successful.

    Raises:
      LockAcquireFailure: On failure to acquire the lock.
    """
    if lock_data is None: lock_data = {}
    lock_data = LockData(lock_data)

    def TryLock():
      """Function to acquire lock within a transaction.

      Returns:
        Returns any shared data that might have been stored in the lock.
      """
      now_time = datetime.datetime.utcnow()
      expire_time = now_time + self._expire_timedelta

      lock = db.get(self._lock_key)
      if lock is None:
        lock = LockModel(key_name=self._lock_key.name(),
                         expire_time=expire_time, lock_data=lock_data)
        lock.put()
        return lock
      elif lock.expire_time < now_time:
        lock.expire_time = expire_time
        lock.put()
        return lock
      return None

    trials = 0
    self._acquired_lock = None
    while self._acquired_lock is None and (self._try_count == 0 or
                                           trials < self._try_count):
      trials += 1

      try:
        self._acquired_lock = db.run_in_transaction(TryLock)
      except db.TransactionFailedError:
        pass

      if self._acquired_lock is None:
        time.sleep(self._sleep_seconds)

    if self._acquired_lock is None:
      logging.info('failed attempt to acquire lock %s', self._lock_key.name())
      raise errors.LockAcquireFailure('Failed to acquire lock %s' %
                                      self._lock_key.name())

    return self._acquired_lock.lock_data.data

  def ReleaseLock(self, lock_data=None):
    """Release a datastore based lock and optionally save data in it."""
    if self._acquired_lock is not None:
      if lock_data is not None:
        lock_data = LockData(lock_data)

        self._acquired_lock.expire_time = datetime.datetime.min  # Force expire.
        self._acquired_lock.lock_data = lock_data
        self._acquired_lock.put()
      else:
        self._acquired_lock.delete()

# pylint: disable-msg=C6409
# Alias Lock to DbLock
Lock = DbLock


def AddFilter(query, property_filter, value):
  """Check property in property_filter exists in the model being queried.

  Args:
    query: The query instance to which the filter will be added.
    property_filter: A string filter query like 'status =' or 'status >' etc.
    value: The value that the property_filter is comparing with.
  """
  p = property_filter.split()[0]
  # pylint: disable-msg=W0212
  assert p in query._model_class.properties()
  query.filter(property_filter, value)


def GetLocalTime(dt, tz):
  """Converts a naive utc datetime to the given timezone.

  Args:
    dt: A datetime.datetime instance with no timezone information, representing
      UTC time.
    tz: A timezone to use for the conversion.

  Returns:
    The converted datetime using the given timezone.
  """
  return dt.replace(tzinfo=pytz.utc).astimezone(tz)


def GetUtcTime(dt, tz):
  """Converts from a local time to UTC using timezone translation.

  The returned time does not have any timezone information. This allows
  comparison with times coming from the datastore (which do not have timezone
  either).

  Args:
    dt: A datetime.datetime instance with no timezone information.
    tz: Timezone of the datetime.

  Returns:
    The converted datetime in UTC (with no timezone info).
  """
  #Enriches the given time with the given timezone. For example 5 pm is enriched
  #to 5 pm EST, taking into account DST.
  local_time = tz.localize(dt)
  #We convert to utc
  utc_time = local_time.astimezone(pytz.utc)
  #We remove the timezone information ( = naive time)
  return utc_time.replace(tzinfo=None)


class Timezone(object):
  """Wrapper around a string to represent a timezone.

  Having a wrapper allows the django forms to present a list of values (using
  all() classmethod).
  """

  def __init__(self, name=None):
    """Creates a new timezone instance.

    Args:
      name: Optional String for the timezone name.

    Raises:
      pytz.UnknownTimeZoneError if the given name is not valid.
    """
    if name:
      self.name = name
    else:
      self.name = 'UTC'

    #Check timezone is valid by trying to instantiate it. May raise error.
    pytz.timezone(self.name)

  @classmethod
  def all(cls):
    return [Timezone(name) for name in pytz.common_timezones]

  def __unicode__(self):
    return self.name

  def get_value_for_datastore(self):
    return self.name

  @classmethod
  def make_value_from_datastore(cls, value):
    return Timezone(value)


def GetEmailAddress(user_id):
  """Gets email address from user_id.

  Args:
    user_id: String representing user id.

  Returns:
    Email for the given user id or None if user_id is invalid.

  """
  user_id = user_id.strip()
  if '@' in user_id:
    email = user_id
  else:
    email = user_id + '@' + os.environ['AUTH_DOMAIN']

  if IsEmailValid(email):
    return email
  else:
    return None


def GetAppEngineUser(user_id):
  """Creates an appengine user from a user_id.

  Args:
    user_id: A string representing an email address or user name.

  Returns:
    An appengine users.User or None if user_id is None.
  """
  email_address = GetEmailAddress(user_id)
  if email_address:
    return users.User(email_address)
  else:
    return None


def IsEmailValid(email):
  """Checks email address validity."""
  return email and EMAIL_RE.search(email)


def ArraySplit(array_to_split, bucket_size):
  """Given an array splits it into smaller arrays of bucket_size each."""
  return [array_to_split[i:i+bucket_size]
          for i in xrange(0, len(array_to_split), bucket_size)]


def QueryIterator(query, model_class, limit=None, offset=None,
                  prefetch_count=None, next_count=None):
  """Enriches a query with control over query parameters.

  Args:
    query: a db.Query instance.
    model_class: Model class from which entities are constructed.
    limit: integer, limit for the query.
    offset: integer, offset for the query.
    prefetch_count: integer, number of results to return in the first query.
    next_count: number of results to return in subsequent next queries.

  Returns:
    Enriched query.
  """
  # use private API to do this, since there is no public API yet
  # pylint: disable-msg=W0212
  query_iter = iter(query._get_query()._Run(limit=limit, offset=offset,
                                            prefetch_count=prefetch_count,
                                            next_count=next_count))
  return db._QueryIterator(model_class, query_iter)


def GetCachedOr404(entity_key, active_only=True):
  """Gets an entity with the given key or throw 404 error.

  Tries to load the entity from the request cache, and falls back to datastore
  if not available.

  Args:
    entity_key: db.Key key of the entity.
    active_only: If true, will only return entities which are in datastore and
      active.

  Returns:
    A db.Model entity

  Raises:
    http.Http404 if not entity could be found.
  """
  entity = request_cache.GetEntitiesFromKeys([entity_key])[0]
  if entity is None:
    raise http.Http404
  elif active_only and hasattr(entity, 'deleted') and entity.deleted:
    raise http.Http404
  return entity
