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


"""Models."""



# Suppress pylint invalid import order
# pylint: disable-msg=C6203

import logging
import settings

from django.utils import translation
from google.appengine.api import users
from google.appengine.ext import db
import pytz
from ragendja import dbutils
from ragendja.auth import google_models

# Invalid warning re. unused import on rules
# pylint: disable-msg=W0611
from core import errors
from core import processors
from core import request_cache
from core import rules
from core import service_factory
from core import timezone_helper
from core import utils

# Suppress pylint const name warnings.
# pylint: disable-msg=C6409
_Active = utils.RegistrationActive
_Attend = utils.RegistrationAttend
_Confirm = utils.RegistrationConfirm

_Status = utils.RegistrationStatus
_AccessPoint = utils.AccessPointType

_ = translation.ugettext


class GlearnUser(google_models.User):
  """A user for the application.

  Attributes:
    timezone: The user preferred timezone.
    course_creator: The user has course creator privileges.
    location: The country-city code of the user, useful to find nearby courses.
  """
  timezone = dbutils.FakeModelProperty(utils.Timezone,
                                       default=utils.Timezone('US/Pacific'))
  course_creator = db.IntegerProperty(default=1)
  location = db.StringProperty(default='US-MTV')

  @classmethod
  def GetGlearnUserFromCache(cls, email):
    """Retrieves a user by email.

    This methods uses a cache for the current request.
    Args:
      email: string email of user.

    Returns:
      models.GlearnUser.
    """
    glearn_user = request_cache.GetObjectFromCache(email)
    if not glearn_user:
      glearn_user = cls.FromAppengineUser(users.User(email))
      if glearn_user:
        request_cache.CacheObject(glearn_user.user.email(), glearn_user)

    return glearn_user

  @classmethod
  def get_djangouser_for_user(cls, user):
    """Overrides method from ragendja.auth.google_models.GoogleUserTraits.

    Notable changes:
      - cache user object in request

    Args:
      user: Appengine user

    Returns:
      A models.GlearnUser.
    """
    django_user = cls.GetGlearnUserFromCache(user.email())

    if not django_user:
      django_user = cls.create_djangouser_for_user(user)
      django_user.is_active = True

    user_put = False
    if django_user.user != user:
      django_user.user = user
      user_put = True
    user_id = user.user_id()
    if django_user.user_id != user_id:
      django_user.user_id = user_id
      user_put = True

    if getattr(settings, 'AUTH_ADMIN_USER_AS_SUPERUSER', True):
      is_admin = users.is_current_user_admin()
      if (django_user.is_staff != is_admin or
          django_user.is_superuser != is_admin):
        django_user.is_superuser = django_user.is_staff = is_admin
        user_put = True

    if not django_user.is_saved() or user_put:
      django_user.put()

    return django_user

  @classmethod
  def create_djangouser_for_user(cls, user):
    """Overriding method used to instantiate user who logs in for first time.

    Args:
      user: users.User for whom a GlearnUser is being created for.

    Returns:
      A GlearnUser or derived class instance.
    """
    logging.info('create_djangouser_for_user for first time user %s', user)
    return cls.CreateUsers([user])[0]

  @classmethod
  def CreateUsers(cls, appengine_users):
    """Creates GlearnUsers from appengine users.

    Args:
      appengine_users: list of users.User.

    Returns:
      A list of GlearnUsers.
    """
    logging.info('Creating users %s', appengine_users)
    glearn_users = [cls(user=user, user_id=user.user_id())
                    for user in appengine_users]
    GlearnUser.UpdateGlearnUserProperties(glearn_users)
    return glearn_users

  @classmethod
  def UpdateGlearnUserProperties(cls, glearn_users):
    """Get the user properties relevant to the given GlearnUsers list.

    Update datastore glearnUser entities with data from user info service.

    Args:
      glearn_users: List of models.GlearnUser objects whose properties will be
         updated.
    """
    email_list = [glearn_user.user.email() for glearn_user in glearn_users]

    try:
      user_service = service_factory.GetUserInfoService()
      person_map = user_service.GetUserInfoMulti(email_list)
    # Suppress pylint catch Exception
    # pylint: disable-msg=W0703
    except errors.ServiceCriticalError, exception:
      logging.error('[%s] %s', type(exception), exception)
      person_map = {}

    for glearn_user in glearn_users:
      user_email = glearn_user.user.email()
      person_info = person_map.get(user_email)
      if person_info:
        glearn_user.location = person_info.country_city
        timezone = timezone_helper.GetTimezoneForLocation(glearn_user.location)
        glearn_user.timezone = utils.Timezone(timezone)
        logging.info('Timezone, location is %s and %s for %s',
                     timezone, glearn_user.location, user_email)
      else:
        logging.warning('Could not retrieve timezone for %s',
                        glearn_user.user.email())

  def CanCreateProgram(self):
    """Returns True if a user can create a program."""
    return self.course_creator or self.is_staff  # Superuser or creator.

  def CanEditProgram(self, program):
    """Returns True if a user can edit a given program."""
    if self.is_staff: return True  # Superuser can edit everything.

    user = self.appengine_user
    return (user == program.owner or user in program.contact_list or
            user in program.facilitator_list)

  def CanCreateActivity(self, program):
    """Returns True if a user can create new activity under a program."""
    return program.public_activity_creation or self.CanEditProgram(program)

  def CanEditActivity(self, activity):
    """Returns True if a user can edit a given activity."""
    if self.is_staff: return True  # Superuser can edit everything.

    user = self.appengine_user
    if self.CanEditProgram(activity.parent()):
      return True
    elif user == activity.owner:
      return True
    else:
      # Instructors can edit activity
      for schedule in activity.ActivitySchedulesQuery():
        if user in schedule.primary_instructors:
          return True
    return False

  def CanEditManagerApproval(self, approval):
    """Returns True if a user can edit a given ManagerApproval."""
    if self.is_staff: return True  # Superuser can edit everything.
    return self.appengine_user == approval.manager

  def GetLocalTime(self, dt):
    """Converts a naive datetime to the local user time.

    This method should be called on any time coming from datastore before
    displaying it to the end user.

    Args:
      dt: A datetime.datetime instance with no timezone information.

    Returns:
      The converted datetime using the appropriate timezone.
    """
    return utils.GetLocalTime(dt, self.GetTimeZone())

  def GetUtcTime(self, dt):
    """Converts from a user local time to UTC using timezone translation.

    This method should be called  on any user-input time to translate it
    to UTC before using it internally.
    For example:
      User has EST timezone and selects 3pm when creating a schedule.
      Calling this method will return 8 pm (since 3 pm EST = 8 pm UTC).

    Args:
      dt: A datetime.datetime instance with no timezone information.

    Returns:
      The converted datetime in UTC.
    """
    assert dt.tzinfo is None
    return utils.GetUtcTime(dt, self.GetTimeZone())

  def GetTimeZone(self):
    """Returns the pytz.timezone of a user."""

    return pytz.timezone(self.timezone.name)

  def GetCityCode(self):
    try:
      return self.location.split('-')[1]
    except IndexError:
      return 'MTV'

  @property
  def appengine_user(self):
    """Property to access the user property in GlearnUser."""
    return self.user

  @classmethod
  def GetOrCreateUser(cls, email, create=False):
    """Retrieves and optionally creates a user from/in the datastore.

    Args:
      email: The user email address.
      create: If True, tries to create and store a new GlearnUser entity with
        the given email when not able to retrieve from datastore.

    Returns:
      A GlearnUser entity or None if not found/invalid.
    """
    return cls.GetOrCreateUsers([email], create)[email]

  @classmethod
  def GetOrCreateUsers(cls, emails, create=False):
    """Retrieves and optionally creates users from/in the datastore.

    Args:
      emails: Str list of user email addresses.
      create: If True, tries to create and store a new GlearnUser entity with
        the given emails when not able to retrieve from datastore.

    Returns:
      A dictionary of {email: user} where user is a GlearnUser entity or None
      if not found/invalid.
    """
    logging.info('Entering GetOrCreateUsers for %s', emails)
    glearn_users = {}
    to_be_created = []
    emails_to_lookup = []

    # Build list of appengine users to lookup in datastore
    for email in set(emails):
      if utils.IsEmailValid(email):
        emails_to_lookup.append(email)
      else:
        glearn_users[email] = None

    # Break down queries in batches of 30 (limit 30 subqueries)
    users_bucket = utils.ArraySplit(emails_to_lookup, 30)
    for bucket in users_bucket:
      appengine_users = [users.User(email) for email in bucket]
      glearn_users_query = cls.FromAppengineUsers(appengine_users)
      # Find missing users and create them
      emails_found = []
      for glearn_user in glearn_users_query.fetch(30):
        emails_found.append(glearn_user.email)
        glearn_users[glearn_user.email] = glearn_user
      # For users not found, we need to create them
      missing_emails = set(bucket) - set(emails_found)
      to_be_created.extend([users.User(email) for email in missing_emails])

    # We create the users which need to be created
    if create and to_be_created:
      created_users = cls.CreateUsers(to_be_created)
      db.put(created_users)
      for user, glearn_user in zip(to_be_created, created_users):
        glearn_users[user.email()] = glearn_user
      logging.info('Created %s new users', created_users)
    return glearn_users

  @classmethod
  def FromAppengineUser(cls, appengine_user):
    """Query the appropriate GlearnUser given a user.User."""
    query = db.Query(cls)
    utils.AddFilter(query, 'user =', appengine_user)
    return query.get()

  @classmethod
  def FromAppengineUsers(cls, appengine_users):
    """Query the appropriate GlearnUser given a user.User."""
    query = db.Query(cls)
    utils.AddFilter(query, 'user in', appengine_users)
    return query

  def get_and_delete_messages(self):
    """Overrides django method. We do not use the messages framework."""
    return []


class _BaseModel(db.Model):
  """Base class which adds utilities."""
  # Suppress pylint invalid inheritance from object
  # pylint: disable-msg=C6601

  class Meta:
    abstract = True

  def GetKey(self, prop_name):
    """Return the reference property key without a datastore fetch."""
    return getattr(self.__class__, prop_name).get_value_for_datastore(self)


class _AuditedModel(_BaseModel):
  """Base class which adds audit properties to a model.

  Attributes:
    owner: The user who owns the entity.
    creation_time: Date when entity was created.
    last_modified: The date and time of last modification for the entity.
    last_modified_by: The user who last edited/modified the program.
  """

  # Suppress pylint invalid inheritance from object
  # pylint: disable-msg=C6601
  class Meta:
    abstract = True

  owner = db.UserProperty(required=True)
  creation_time = db.DateTimeProperty(auto_now_add=True)
  last_modified = db.DateTimeProperty(auto_now=True)
  last_modified_by = db.UserProperty(required=True)


class _DeletedHierarchyModel(_AuditedModel):
  """Base class for objects that need to support delayed deletion.

  Entities cannot be deleted right away when deleting them causes system to be
  inconsistent. This base class adds another state for an entity that
  differentiates a deleted state from a 'to be deleted' state.

  Attributes:
    deleted: An integer to indicate if the entity is deleted.
    to_be_deleted: An integer to indicate if the entity is going to be deleted.
  """

  # Suppress pylint invalid inheritance from object
  # pylint: disable-msg=C6601
  class Meta:
    abstract = True

  deleted = db.IntegerProperty(default=0)
  to_be_deleted = db.IntegerProperty(default=0)

  def _GetChildrenQuery(self):
    """Provides an iterator of child _DeletedHierarchyModel instances.

    Should provide the list of entities that the current entity considers as
    direct children in the hierarchy. These children entities should belong
    to the same entity group since they are operated on in transactions.

    For Example: Programs contain activities which contain activity schedules.
    The Program class can thus return the list of activities that it considers
    active as its children. And the activities can in turn provide the schedules
    as their children. This provides a way to traverse the full hierarchy and
    change attributes.

    Returns:
      An iterator of _DeletedHiearchyModel child entities.

    Raises:
      AbstractMethod: for default implementation
    """
    raise errors.AbstractMethod

  def DeleteUnsafeAndWrite(self, request_user):
    """Mark the hierarchy as deleted and update in datastore.

    Args:
      request_user: users.User requesting the modification.

    Returns:
      The list of entities that are marked as deleted.
    """
    write_list = self.SetHierarchyAttribute('deleted', 1, request_user)
    db.put(write_list)
    return write_list

  def MarkToBeDeletedUnsafeAndWrite(self, request_user):
    """Mark the hierarchy as to be deleted and update in datastore.

    Args:
      request_user: users.User requesting the modification.

    Returns:
      The list of entities that are marked as to be deleted.
    """
    write_list = self.SetHierarchyAttribute('to_be_deleted', 1, request_user)
    db.put(write_list)
    return write_list

  def SetHierarchyAttribute(self, attribute_name, attribute_value,
                            request_user):
    """Set the attribute value in the hierarchy.

    Args:
      attribute_name: Name of the model attribute to change.
      attribute_value: Value to set the model attribute to.
      request_user: users.User requesting the modification.

    Returns:
      The list of _DeletedHierarchyModel entities that were updated.
    """
    setattr(self, attribute_name, attribute_value)
    self.last_modified_by = request_user
    entity_write_list = [self]

    query = self._GetChildrenQuery()
    entity_list = [entity for entity in query]
    for entity in entity_list:
      assert isinstance(self, _DeletedHierarchyModel)
      entity_write_list.extend(entity.SetHierarchyAttribute(
          attribute_name, attribute_value, request_user))

    return entity_write_list

  def StoreDeleteTaskConfig(self, request_user):
    """Stores a config entry indicating that the program should be deleted.

    Entities like Program, Activity that have user registrations associated with
    them are not deleted right away and are deleted in the background. Storing
    this config entry is an indication to the background process on what entity
    needs to be deleted.

    Args:
      request_user: users.User requesting the modification.
    Returns:
      The created Configuration entity.
    """

    config_key = 'configuration_delete_entity_task'
    config_value = '%s,%s' % (self.key(), request_user.email())
    config = Configuration(parent=self, config_key=config_key,
                           config_value=config_value)
    config.put()
    return config


class _ModelRule(object):
  """Base class with helper methods for models which can have rules."""

  def GetRule(self, rule_name):
    """Gets the given rule from activity rules.

    Args:
      rule_name: Name of rule.

    Returns:
      The rules.RuleConfig or None if not found.
    """
    for rule in self.rules:
      if rule_name == rule.rule_name:
        return rule

    return None


class Program(_DeletedHierarchyModel, _ModelRule):
  """A grouping of learning entities.

  At a high level a program is a collection of activities and the rules that
  determine the completion a particular knowledge it represents.
  A program can be composed of either child programs or activities, not both.

  Example: Program 'Java 101' may include child programs 'OO Programming', and
  'Java Language Specification', and a rule that both of them should be
  completed in that order. The program 'OO Programming' can be composed of
  activities 'March OO Programming' and 'January OO Prog Video' and a common
  completion rule that just one of them is required to complete the program
  'OO Programming'.

  Attributes:
    name: A string that identifies the program uniquely.
    description: Optional text to describe the program.
    contact_list: List of users who have program edit permissions and are shown
        in the contact information of a program detail page.
    facilitator_list: List of users who help set up the program.
    rules: A list of rules that are validated when registering, unregistering
        for an activity under the program or certifying for the program based on
        activities that are completed. Registration rules for example can limit
        the number of program activities that can be taken, certification rules
        can specify the number of programs/activities and their order required
        for completion of the program.
    program_tags: String list of tags associated with this program.
    public_activity_creation: Boolean indicating if any user of the system can
        create a new activity under a program. Used for programs that want the
        flexibility to allow anyone to schedule and teach a session.
    visible: Integer indicating programs setting for visibility. If this flag is
        set to False then the program and the activities underneath it are
        invisible.
  """

  name = db.StringProperty(required=True)
  description = db.TextProperty()
  contact_list = db.ListProperty(users.User)
  facilitator_list = db.ListProperty(users.User)
  rules = dbutils.FakeModelListProperty(rules.RuleConfig, default=[])
  program_tags = db.StringListProperty(default=[])
  public_activity_creation = db.BooleanProperty(default=False)
  visible = db.IntegerProperty(default=1)

  def ActivitiesQuery(self, keys_only=False):
    """Build query to get activities under the program."""

    return Program.ActivitiesQueryFromKey(self.key(), keys_only=keys_only)

  @staticmethod
  def ActivitiesQueryFromKey(program_key, keys_only=False):
    """Build query to get activities under the program.

    Args:
      program_key: Program db.Key to query activities under.
      keys_only: Boolean if only keys should be returned by the query.

    Returns:
      Query object that provides the requested Activities or db.Keys.
    """

    query = db.Query(Activity, keys_only=keys_only)
    query.ancestor(program_key)
    utils.AddFilter(query, 'deleted =', 0)

    return query

  def _GetChildrenQuery(self):
    """Overrides parent method."""

    return self.ActivitiesQuery()

  def __unicode__(self):
    return unicode(self.name)

  def ActivitySchedulesQuery(self):
    """Build query to get activity schedules under the program."""

    query = db.Query(ActivitySchedule)
    query.ancestor(self)
    utils.AddFilter(query, 'deleted =', 0)

    return query

  def RegistrationsQuery(self):
    """Build query to get registrations for activities of a program."""

    query = db.Query(UserRegistration)
    utils.AddFilter(query, 'program =', self)
    return query

  @staticmethod
  def GetSearchableProgramsQuery():
    """Query programs that can be searched."""
    program_query = Program.all()
    utils.AddFilter(program_query, 'visible =', 1)
    utils.AddFilter(program_query, 'deleted =', 0)

    return program_query


class Configuration(db.Model):
  """Configuration data store key and text/binary data.

  Can be used for configuration of any kind. For example rules that are
  configured at a global scope applicable for any program.

  Attributes:
    config_key: A string identifier for identifying the configuration.
    config_value: Optional text configuration value.
    config_binary_value: Optional binary configuration value.
    last_modified: The date and time of last modification for the entity.
  """

  config_key = db.StringProperty()
  config_value = db.TextProperty()
  config_binary_value = db.BlobProperty()
  last_modified = db.DateTimeProperty(auto_now=True)


class Activity(_DeletedHierarchyModel, _ModelRule):
  """A program learning experience event that can be registered to as a unit.

  A learning experience that one can register to and which imparts the
  knowledge or information represented by a program. For example an instructor
  led class that teaches Python is an activity. The different classes that
  all teach the same thing fall under the same parent program.

  Attributes:
    name: A string that identifies the activity under a program uniquely.
    start_time: The lower start time of all ActivitySchedule associated with
        this activity.
    end_time: The greater end time of all ActivitySchedule associated with this
        activity.
    rules: A list of rules that are validated when registering/unregistering
        for the activity. Example - 'No more than 20 people in an activity'.
    access_point_tags: Intersection of all schedule access point tags cached.
    reserve_rooms: A boolean indicating if we should attempt to reserve
        conference rooms for the activity schedules under this activity.
    visible: Integer indicating activities preference for visibility. Activity
        is visible only iff activity.visible and program.visible are True.
  """

  # Suppress pylint invalid inheritance from object
  # pylint: disable-msg=C6601
  class Meta:
    verbose_name = _('Activity')
    verbose_name_plural = _('Activities')

  name = db.StringProperty(required=True)
  start_time = db.DateTimeProperty()
  end_time = db.DateTimeProperty()
  rules = dbutils.FakeModelListProperty(rules.RuleConfig, default=[])
  access_point_tags = db.StringListProperty(default=[])
  reserve_rooms = db.BooleanProperty(default=True)
  visible = db.IntegerProperty(default=1)

  def GetAccessPoints(self):
    aps = []
    for activity in self.ActivitySchedulesQuery():
      aps.extend(activity.access_points)
    return aps

  def ActivitySchedulesQuery(self):
    """Build query to get schedules under an activity."""
    return Activity.SchedulesQueryFromActivityKey(self.key())

  def _GetChildrenQuery(self):
    """Overrides parent method."""
    return self.ActivitySchedulesQuery()

  @staticmethod
  def GetLock(activity_key):
    """Gets a lock for this activity.

    Args:
      activity_key: models.Activity db.Key or string key representing the
      activity.

    Returns:
      A lock utils.Lock.
    """
    return utils.Lock(str(activity_key))

  @classmethod
  def SchedulesQueryFromActivityKey(cls, activity_key):
    """Build query to get the schedules under an activity given activity_key."""
    query = db.Query(ActivitySchedule)
    if isinstance(activity_key, basestring):
      activity_key = db.Key(activity_key)
    query.ancestor(activity_key)
    utils.AddFilter(query, 'deleted =', 0)

    return query

  def RegistrationsQuery(self, keys_only=False):
    """Build query to get registrations under an activity."""
    query = db.Query(UserRegistration, keys_only=keys_only)
    return query.filter('activity =', self)

  @staticmethod
  def OrphanedActivities():
    program_set = set(db.Query(Program, keys_only=True))
    activities = db.Query(Activity)

    orphan_activities = []
    for activity in activities:
      if activity.parent_key() not in program_set:
        orphan_activities.append(activity)

    return orphan_activities

  def __unicode__(self):
    return unicode(self.name)

  def MaxCapacity(self):
    """Maximum number of allowed people based on rule config properties.

    Returns:
      The maximum number of people that will be allowed by an instantiated rule.
      Returns None when not able to determine such a capacity.
    """
    max_by_activity_rule = self.GetRule(rules.RuleNames.MAX_PEOPLE_ACTIVITY)
    if max_by_activity_rule:
      return max_by_activity_rule.parameters.get('max_people', None)
    return None


class AccessPoint(_BaseModel):
  """Represents learning access entities like Rooms, VC, SCORM URLs etc,.

  Attributes:
    type: A category string indicating the type the access entity like 'room',
        'web url', 'vc', 'telephone', 'scorm url'. Could be physical or virtual.
    uri: A string containing the access point resource identifier.
    location: A string representing the geographical location of the room.
        This is usually a city (e.g. Mountain View).
    tags: List of strings that help categorize access points. The
        first tag is a special display tag. The display tag can represent the
        access point when full uri detail is not needed. For example a display
        tag of 'NYC' may be sufficient when we want to know where the activity
        is being held.
    calendar_email: String email of resource in google calendar. Used for
        inviting the access point to events and blocking the time slot.
    rules: List of rules to be validated against this access point for
        registration. Example-'max 50 people', 'only VPs' etc.
    deleted: Integer 1 if deleted, 0 if an active access point.
    timezone: Timezone in which this room is located.

  Example:
    type = room; uri = nyc/9th avenue/4th floor/Lincoln Center
    type = vc ;  uri = 3-565-2639
  """

  type = db.CategoryProperty(required=True, choices=_AccessPoint.Choices())
  uri = db.StringProperty(required=True)
  location = db.StringProperty()
  tags = db.StringListProperty()
  calendar_email = db.StringProperty(indexed=False)
  rules = dbutils.FakeModelListProperty(rules.RuleConfig)
  last_modified = db.DateTimeProperty(auto_now=True)
  deleted = db.IntegerProperty(default=0)
  timezone = dbutils.FakeModelProperty(utils.Timezone,
                                       default=utils.Timezone('UTC'))

  def GetTimeZone(self):
    """Returns the pytz.timezone for that access point."""
    return pytz.timezone(self.timezone.name)

  @classmethod
  def GetAccessPointFromKeys(cls, keys):
    """Returns a list of access points given a list of keys.

    Args:
      keys: A list of access point keys.

    Returns:
      A list of models.AccessPoint or None elements.
    """
    return db.get(keys)

  @classmethod
  def GetAccessPointFromUri(cls, uri):
    """Returns the access point which matches given URI.

    Args:
      uri: URI of the access point to retrieve.

    Returns:
      Relevant access point or None.
    """
    query = db.Query(cls).filter('uri = ', uri)
    #TODO(user): we return the first one. need to do better job here.
    #How to handle duplicates, can we store twice similar numbers like
    #321-1234 and 3211243 etc.
    return query.get()

  def Delete(self):
    """Deletes the access point."""
    self.deleted = 1
    self.put()

  def __unicode__(self):
    return unicode(self.uri)


class ActivitySchedule(_DeletedHierarchyModel):
  """Time slot, instructors and access points of an activity.

  An activity can have multiple activity schedules. Activity schedules are
  implicitly ordered by start_time and form the continuation of the
  activity, the user is expected to attend ALL schedules of an activity.

  Each schedule must have an Activity as a parent.

  Attributes:

    start_time: Date and time when the schedule starts.
    end_time: Date and time when the schedule ends.
    access_points: List of access points used to attend/access the activity.
    access_points_secondary: List of secondary access points, instructors do not
        attended in secondary access points. Can be used to digitally access the
        instruction through them.
    access_point_tags: List of string tags that are a union of the access
        point tags under the schedule. Copied for query performance. Access
        point type is also included as a tag. The first tag should be used for
        display as the primary tag for this schedule.
    primary_instructors: List of users who are the primary instructors.
    primary_instructors_accesspoint: List of access points for each of the
        primary_instructors as a 1-1 mapping.
    secondary_instructors: List of users who have the same access permissions as
        the primary instructors and aren't displayed for student searches.
    calendar_edit_href: Edit URL of the calendar event for the schedule.
    notes: Arbitraty text input for this schedule.
  """
  start_time = db.DateTimeProperty(required=True)
  end_time = db.DateTimeProperty(required=True)
  access_point_tags = db.StringListProperty()
  access_points = dbutils.KeyListProperty(AccessPoint)
  access_points_secondary = dbutils.KeyListProperty(AccessPoint)
  primary_instructors = db.ListProperty(users.User)
  primary_instructors_accesspoint = dbutils.KeyListProperty(AccessPoint)
  #Not indexing secondary instructors because we don't want to search them.
  secondary_instructors = db.ListProperty(users.User, indexed=False)
  calendar_edit_href = db.URLProperty()
  notes = db.TextProperty()

  def __unicode__(self):
    return unicode(self.start_time)

  def _GetChildrenQuery(self):
    """Overrides parent method."""
    return []

  @property
  def activity(self):
    return self.parent()

  @property
  def activity_key(self):
    return self.parent_key()

  @staticmethod
  def ActiveSchedulesQuery():
    """Build query to get all schedules that aren't deleted."""

    query = db.Query(ActivitySchedule)
    utils.AddFilter(query, 'deleted =', 0)

    return query

  def GetAllAccessPoints(self):
    """Returns a set of primary and secondary access points."""
    return set(self.access_points).union(self.access_points_secondary)

  def ValidateInstance(self):
    """Validate the current schedule instance and return errors if any.

    This method should be called just before writing the instance to the
    datastore.

    Returns:
      A dictionary with items (property_name, string_errors_list). It is empty
      when no validation errors occurred. The property_name is the name of the
      entity property on which validation error occurred.
    """

    errors_dict = {}

    # Check access_points are valid.
    ap_list = db.get(self.access_points)
    if None in ap_list:
      errors_dict['access_points'] = [_('Access Points not found')]

    return errors_dict

  @staticmethod
  def OrphanedActivitySchedules():
    """Get all activity schedules that have activity missing."""

    activity_set = set(db.Query(Activity, keys_only=True))

    orphan_schedules = []
    schedules = db.Query(ActivitySchedule)
    for schedule in schedules:
      activity_key = schedule.activity_key
      if activity_key not in activity_set:
        orphan_schedules.append(schedule)

    return orphan_schedules


class ManagerApproval(_BaseModel):
  """Information about manager approval used by ManagerApproval rule.

  Attributes:
    candidate: users.User who needs the approval to attend an activity.
    manager: users.User who needs to approve.
    activity: Activity the candidate is trying to attend.
    program: Program of the activity.
    nominator: users.User who is trying to register candidate for the activity.
    queue_time: The models.Registration.queue_time for the registration that has
        initiated the workflow for manager approval.
    last_update_time: The last time when the approval was updated.
    approved: Boolean to indicate if the manager approved this request.
    manager_decision: Boolean that indicates if manager took an action.
  """

  candidate = db.UserProperty(required=True)
  manager = db.UserProperty(required=True)
  activity = db.ReferenceProperty(Activity, required=True)
  program = db.ReferenceProperty(Program, required=True)
  nominator = db.UserProperty(required=True)
  queue_time = db.DateTimeProperty(auto_now_add=True)
  last_update_time = db.DateTimeProperty(auto_now=True)
  approved = db.BooleanProperty(required=True)
  manager_decision = db.BooleanProperty(required=True, default=False)

  @staticmethod
  def GetPendingApprovalsQuery(manager_user):
    """Returns query for pending manager approval requests for a manager.

    Args:
      manager_user: users.User object of the manager for whom the pending
          approval list should be queried.

    Returns:
      db.Query that can be queried to retrieve all the pending approvals.
    """
    pending_approvals = ManagerApproval.all()
    utils.AddFilter(pending_approvals, 'manager =', manager_user)
    utils.AddFilter(pending_approvals, 'manager_decision =', False)
    pending_approvals.order('queue_time')
    return pending_approvals


class UserRegistration(_BaseModel):
  """User registration status for an activity.

  UserRegistration records a user's registration attempt and tracks the status
  of the registration attempt.

  Attributes:
    user: User who is trying to register.
    activity: The activity to which the user is trying to register.
    program: The program to which the activity belongs to.
    queue_time: The time the user starts the registration attempt. Helps in
        processing priority between similar requests between users. Once the
        user starts a registration request a queue_time is created which is kept
        active until the user initiates an unregister request.
    creator: The user who initiated the registration.
    schedule_list: A list of schedules the user is attending.
    access_point_list: An ordered list relating 1-1 with schedule_list recording
        which available access_point for the schedule the user wants to attend.

    status: String category from utils.RegistrationStatus.
    confirmed: Only entities marked with string status 'confirmed' are consumed
        by the off-line rule context construction. Entities marked with 'ready'
        are consumed to be processed. 'not ready' status is ignored.
    active: String status that records if the entity is holding the latest
        registration status. A user registration creates multiple entities over
        the life cycle and only the latest will be marked with a value 'active'
    online_unregistered: Flag that records if the online state was
        notified after unregistration by the ofline process.
    affecting_rule_tags: List string tags that affecting rules (rules that
        agreed with the final status of rule engine evaluation) wanted to
        identify the registration with. See rules.RuleRegister.Evaluate
        for more info on how rule_tags can be used.
    rule_tags: List of string tags that all the rules wanted to identify this
        registration with. See rules.RuleRegister.Evaluate for more info on how
        rule_tags can be used.
    affecting_rule_configs: A list of rule configs that affected the current
        status of the registration.
    attendance: Category status depicting if the user attended the activity.
    last_notified: Indicates the registration status of the last email
        notification sent to the user. See utils.RegistrationStatus.
    notify_email: Boolean to indicate whether to send email notification or not.
    post_process_tasks: List of processors.TaskConfig that configure the
        tasks to run after an unregistration is processed offline.
    force_status = Boolean that indicates if the status has been forced to the
        current value by ignoring the rule engine decision.
    last_modified: Date the entity was last modified.
  """

  user = db.UserProperty(required=True)
  activity = db.ReferenceProperty(Activity, required=True)
  program = db.ReferenceProperty(Program, required=True)
  queue_time = db.DateTimeProperty(auto_now_add=True)
  creator = db.UserProperty(required=True)
  schedule_list = dbutils.KeyListProperty(ActivitySchedule, indexed=False)
  access_point_list = dbutils.KeyListProperty(AccessPoint, indexed=False)

  status = db.CategoryProperty(required=True, choices=_Status.Choices())
  confirmed = db.CategoryProperty(required=True, choices=_Confirm.Choices())
  active = db.CategoryProperty(required=True, choices=_Active.Choices())
  online_unregistered = db.BooleanProperty(required=True, default=False,
                                           indexed=False)
  affecting_rule_tags = db.StringListProperty(indexed=True)
  rule_tags = db.StringListProperty(indexed=False)
  affecting_rule_configs = dbutils.FakeModelListProperty(
      rules.RuleConfig, default=[])
  attendance = db.CategoryProperty(required=True, choices=_Attend.Choices(),
                                   default=_Attend.UNKNOWN)
  last_notified = db.CategoryProperty(choices=_Status.Choices(), indexed=False)
  notify_email = db.BooleanProperty(default=True)
  post_process_tasks = dbutils.FakeModelListProperty(processors.TaskConfig,
                                                     default=[])
  force_status = db.BooleanProperty(indexed=False, default=False)
  last_modified = db.DateTimeProperty(auto_now=True)

  def __init__(self, *args, **kwargs):
  # Use of super on old style class. Invalid warning.
  # pylint: disable-msg=E1002
    """Registration constructor that considers eval_context data.

    When called with an eval_context named argument, the construction uses the
    eval_context to build the properties. Properties in kwargs override the ones
    in eval_context.

    Args:
      args: All the un-named parameters besides self.
      kwargs: All named parameters like property names. If eval_context is one
         of the named parameters then it is used to initialize some properties.
    """

    if 'eval_context' in kwargs:
      eval_context = kwargs['eval_context']

      new_kwargs = {}

      new_kwargs['program'] = eval_context.program
      new_kwargs['activity'] = eval_context.activity
      new_kwargs['queue_time'] = eval_context.queue_time
      new_kwargs['force_status'] = eval_context.force_status
      new_kwargs['user'] = eval_context.user.appengine_user
      new_kwargs['creator'] = eval_context.creator.appengine_user
      new_kwargs['schedule_list'] = eval_context.schedule_list
      new_kwargs['access_point_list'] = eval_context.access_point_list
      # Remove eval_context element from kwargs.
      kwargs.pop('eval_context')
      new_kwargs.update(kwargs)

      super(UserRegistration, self).__init__(*args, **new_kwargs)
    else:
      super(UserRegistration, self).__init__(*args, **kwargs)

    assert (self.confirmed != _Confirm.NOT_READY or
            self.active == _Active.INACTIVE)

  def OnlyWaitingForMaxPeopleActivity(self):
    """Determine if registration is waiting only on max people activity rule."""
    a_configs = self.affecting_rule_configs
    return (self.status == utils.RegistrationStatus.WAITLISTED and
            len(a_configs) == 1 and
            a_configs[0].rule_name == rules.RuleNames.MAX_PEOPLE_ACTIVITY)

  def WaitingForMaxPeopleActivity(self):
    """Determine if registration is waiting on max people activity rule."""
    max_people_rule_name = rules.RuleNames.MAX_PEOPLE_ACTIVITY
    a_configs = self.affecting_rule_configs
    return (self.status == utils.RegistrationStatus.WAITLISTED and
            max_people_rule_name in [cfg.rule_name for cfg in a_configs])

  def __unicode__(self):
    return '%s/%s' % (unicode(self.user), unicode(self.activity))

  @staticmethod
  def AddRegisterOrder(query):
    """Adds to query the ranking order of user registration entities."""

    query.order('queue_time')
    query.order('user')

  @staticmethod
  def ActiveQuery(program=None, activity=None, user=None, query=None,
                  keys_only=False):
    """Constructs query for active UserRegistrations with additional filters.

    Args:
      program: If not None the query will filter for registrations related to
          the given program.  Can be a db.Key or Program instance.
      activity: If not None the query will filter for registrations related to
          the given activity. Can be a db.Key or Activity instance.
      user: If not None the query will filter for registrations related to the
          given user.User.
      query: A valid query on the UserRegistration class that is modified to
          return active registrations. If None new query is created.
      keys_only: Boolean if only keys should be returned by the query.

    Returns:
      A query that can be used to access active registrations.
    """

    if query is None:
      query = UserRegistration.all(keys_only=keys_only)

    utils.AddFilter(query, 'active =', _Active.ACTIVE)

    if activity is not None:
      utils.AddFilter(query, 'activity =', activity)
    elif program is not None:
      utils.AddFilter(query, 'program =', program)
    if user is not None:
      utils.AddFilter(query, 'user =', user)

    return query

  def isValid(self, schedules):
    """Checks that user registration is valid against expected schedules.

    Args:
      schedules: An iterator over models.ActivitySchedules

    Returns:
      True iff the user registration schedules/access points are part of the
      given schedules.
    """
    schedule_ap_map = {}
    for schedule in schedules:
      schedule_ap_map[schedule.key()] = (schedule.access_points +
                                         schedule.access_points_secondary)
    # Check that every access point of each schedule is still valid
    for schedule_key, ap_key in zip(self.schedule_list,
                                    self.access_point_list):
      ap_keys = schedule_ap_map.get(schedule_key, None)
      # Check that user access point selection is still valid
      if ap_key not in ap_keys:
        return False
    return True

  @staticmethod
  def WaitlistRankForUser(activity, user):
    """Get the user's waitlist rank for a max capacity constrained course.

    Args:
      activity: Activity or db.Key of an Activity for which a user's waitlist
          rank is required.
      user: users.User for whom we need to find the waitlist rank.

    Returns:
      A integer waitlist rank starting from 1. If the waitlist cannot be found
      or the user not available in it, it returns 0.
    """

    query = UserRegistration.ActiveQuery(activity=activity)
    UserRegistration.AddRegisterOrder(query)
    utils.AddFilter(query, 'status =', utils.RegistrationStatus.WAITLISTED)
    queue_rank = 1

    for registration in query:
      if registration.user == user:
        break
      if registration.OnlyWaitingForMaxPeopleActivity():
        queue_rank += 1
    else:
      queue_rank = 0

    return queue_rank

  @staticmethod
  def NumberRegisteredForActivity(activity_key):
    """Counts the number of active registered users for an activity."""

    registrations = UserRegistration.ActiveQuery(activity=activity_key)
    return registrations.count()

