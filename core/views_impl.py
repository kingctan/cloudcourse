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


"""Has utility methods that views use to implement their functionality."""

# Supress pylint invalid import order
# pylint: disable-msg=C6203




import datetime
import logging
import uuid

from django import http
from django import shortcuts
from django import template
from django.core import urlresolvers
from django.forms import formsets
from django.utils import simplejson
from django.utils import translation
from google.appengine.api.labs import taskqueue
from google.appengine.api import capabilities
from google.appengine.ext import db
from google.appengine.ext import deferred
from google.appengine.api import memcache

from core import access_points as ap_utils
from core import calendar
from core import errors
from core import forms
from core import models
from core import query_processor
from core import request_cache
from core import rule_engine
from core import rules
from core import service_factory
from core import tasks
from core import utils
from core.templatetags import format

# Suppress pylint const name warnings.
# pylint: disable-msg=C6409
_ = translation.ugettext
_Active = utils.RegistrationActive
_Status = utils.RegistrationStatus


def SystemStatus():
  """Checks system status.

  Returns:
    A dictionary where keys are names of features, and values are either True
    or False depending on system being OK.
  """
  ds_write = capabilities.CapabilitySet('datastore_v3',
                                        capabilities=['write']).is_enabled()
  ds_available = capabilities.CapabilitySet('datastore_v3').is_enabled()

  datastore_ok = ds_available and ds_write
  if datastore_ok:
    # Make sure we can really write/read
    unique = str(uuid.uuid4())
    test_entity = models.Configuration(key_name=unique, config_key=unique)
    test_entity.put()
    entity_key = db.Key.from_path(models.Configuration.kind(), unique)
    entity = db.get(entity_key)
    datastore_ok = entity is not None and entity.config_key == unique

  memcache_ok = capabilities.CapabilitySet('memcache').is_enabled()
  if memcache_ok:
    unique = str(uuid.uuid4())
    memcache.add(key=unique, value=unique, time=30)
    value = memcache.get(unique)
    memcache_ok = value == unique

  return {'datastore': datastore_ok,
          'urlfetch': capabilities.CapabilitySet('urlfetch').is_enabled(),
          'mail': capabilities.CapabilitySet('mail').is_enabled(),
          'memcache': memcache_ok,
          'taskqueue': capabilities.CapabilitySet('taskqueue').is_enabled()}


def _GetUserProgramRegistrations(user, program):
  """Collect all the activities that a user has enrolled in under a program.

  Args:
    user: The users.User who's registrations we are interested in.
    program: Program who's activities are searched for the user's registrations.

  Returns:
    Returns a {activity_key: models.UserRegistration} dictionary.
  """
  # TODO(user): Need to rework this with new rule engine changes.

  # Construct the user registrations query.
  register_query = program.RegistrationsQuery()
  register_query = models.UserRegistration.ActiveQuery(user=user,
                                                       query=register_query)

  # Create a (activity_key, registration_status) dictionary.
  activity_register_map = {}
  for register in register_query:
    activity_register_map[register.GetKey('activity')] = register

  return activity_register_map


def _AddScheduleDisplayAttributes(schedule, user):
  """Add formatted display information to the given schedule as attributes.

  The given schedule information is formatted to the specification as it should
  be displayed in the show program page and stored as attributes on the given
  schedule. This function modifies the given schedule parameter with these new
  attributes.

  Warning:
    This function modifies the schedule object by adding display attributes,
    it is intended to be used only before rendering a template. Do not use the
    passed in schedule object elsewhere in other functions.

  Args:
    schedule: A models.ActivitySchedule for which the display information is
        being constructed.
    user: A models.GlearnUser for whom the display formatting is being done for.

  Display attributes added to schedule entity:
    instructor_list: A list of dictionaries with key:name containing instructor
        name, and key:email having the email of the schedule instructors.
    start_time_local: Start time in user local timezone.
    end_time_local: End time in user local timezone.
  """
  # Instructor List
  schedule.instructor_list = []
  for instructor in schedule.primary_instructors:
    schedule.instructor_list.append({'name': instructor.nickname(),
                                     'email': instructor.email()})

  # Get user's local times
  schedule.start_time_local = user.GetLocalTime(schedule.start_time)
  schedule.end_time_local = user.GetLocalTime(schedule.end_time)


def _EnrichActivities(activities, schedules, user,
                      include_past_activities=False,
                      include_past_schedules=False):
  """Enriches attributes of activities based on the given schedules.

  Filters out activities that do not have any schedule in the future, sorts them
  by the first upcoming schedule start time.

  Warning:
    This function augments db.Models with some convenient display attributes,
    do not use the model entities returned from here to save back to datastore.
    Intended only to be used by view functions to render templates.

  Args:
    activities: An iterable that lists all the activities that we need to sort
        and add display information for.
    schedules: An iterable of all the schedules that we will encounter for the
        for the above activities.
    user:  The GlearnUser user for whom we are trying to format display info.
      Activities are displayed based on user permissions.
    include_past_activities: boolean to include past activities even if they
      do not have an upcoming schedule. If true, overrides
      include_past_schedules.
    include_past_schedules: Boolean to include past schedules for activities.

  Returns:
    A sorted list of activities. The activities are sorted based on the latest
    up coming schedule in each of them.
    The following attributes are added to the activity:
      sorted_schedules: A list of start_time sorted schedules. Each such
        schedule also has the relevant display information required for the show
        program page.
      instructor_list: A list of all instructors teaching this activity.
      access_points: A list of models.AccessPoint associated with this
        activity.
      access_points_secondary: A list of models.AccessPoint associated with
        this activity.
      locations: A list of primary locations coming from primary access points.
        Duplicates are excluded.
      locations_secondary: A list of secondary locations, exclusive or the
        primary locations. Duplicates are excluded.
      start_time_local: Starting time of the first schedule in user timezone.
      end_time_local: Ending time of the last schedule in user timezone.
      user_can_edit_activity: Whether user can edit activity or not.
      program_name: String representing program name.
      program_id: String representing program key.
  """
  # Create a (activity_key -> Activity Entity) dictionary.
  activity_hash = dict([(a.key(), a) for a in activities])
  processed_activities = {}
  sorted_activities = []

  if include_past_activities:
    include_past_schedules = True
  # Add the schedules (which are sorted by start_time) to their corresponding
  # activity entities. Use the sort order of schedules to sort the activities
  # by increasing time order of first unexpired sessions.
  # An unexpired session is a session whose end_time is in the future.
  time_now = datetime.datetime.utcnow()  # Appengine uses utc for stored times.
  schedules_retrieved = [s for s in schedules]
  for schedule in sorted(schedules_retrieved, key=lambda x: x.start_time):
    activity_key = schedule.parent_key()
    assert activity_key in activity_hash  # Should be an existing activity.

    _AddScheduleDisplayAttributes(schedule, user)
    activity = activity_hash[activity_key]
    if not hasattr(activity, 'sorted_schedules'):
      activity.sorted_schedules = []
      activity.instructor_list = []
      activity.access_points = set()
      activity.access_points_secondary = set()
      activity.start_time = schedule.start_time
      activity.end_time = schedule.start_time
      activity.instructor_set = set()

    if (include_past_schedules or schedule.end_time > time_now
        or user.CanEditActivity(activity_hash[schedule.parent_key()])):
      # The schedule is of interest, we add it to the activity
      activity.end_time = max(activity.end_time, schedule.end_time)
      activity.sorted_schedules.append(schedule)
      # We add schedule instructors to activity instructors
      for person in schedule.instructor_list:
        if not person['email'] in activity.instructor_set:
          activity.instructor_set.add(person['email'])
          activity.instructor_list.append(person)
      # We add schedule primary location to activity locations
      activity.access_points.update(schedule.access_points)
      activity.access_points_secondary.update(
          schedule.access_points_secondary)

    # We only add activities which have a schedule in the future by default, or
    # activities for which user has edit privileges.
    if (include_past_activities or schedule.end_time > time_now
        or user.CanEditActivity(activity_hash[schedule.parent_key()])):
      if activity_key not in processed_activities:
        processed_activities[activity_key] = True
        sorted_activities.append(activity)

  all_aps = []
  for activity in sorted_activities:
    all_aps.extend(activity.access_points)
    all_aps.extend(activity.access_points_secondary)

  # Retrieve all relevant access points at once.
  all_aps = request_cache.GetEntitiesFromKeys(all_aps)
  aps_map = dict([(ap.key(), ap) for ap in all_aps])

  for activity in sorted_activities:
    activity.instructor_list.sort()
    activity.access_points = [aps_map[ap] for ap in activity.access_points]
    activity.access_points_secondary = [aps_map[ap] for ap in
                                        activity.access_points_secondary]

    activity.locations = set()
    for ap in activity.access_points:
      if ap.location is not None:
        activity.locations.add(ap.location)
      else:
        activity.locations.add(ap.type.upper())
    activity.locations_secondary = set([ap.location for ap in
                                        activity.access_points_secondary])
    # Filter out locations which are available as primary.
    activity.locations_secondary -= activity.locations
    # Sort locations alphabetically.
    activity.locations = sorted(list(activity.locations))
    activity.locations_secondary = sorted(list(activity.locations_secondary))

    activity.start_time_local = user.GetLocalTime(activity.start_time)
    activity.end_time_local = user.GetLocalTime(activity.end_time)
    activity.user_can_edit_activity = user.CanEditActivity(activity)

    program = request_cache.GetEntityFromKey(activity.parent_key())

    activity.program_name = program.name
    activity.program_id = program.key()

    # Remove temporary attributes
    delattr(activity, 'instructor_set')

  return sorted_activities


def Home(user):
  """Creates context data for home page.

  Args:
    user: models.GlearnUser.

  Returns:
    Dictionary to construct template.
  """
  max_results = 5
  enrolled_activities = _GetUserEnrolledActivities(user)
  teaching_activities = _GetUserTeachingActivities(user)
  owned_programs = GetUserOwnedPrograms(user)
  more_learning = len(enrolled_activities) > max_results
  more_teaching = len(teaching_activities) > max_results
  more_owned = len(owned_programs) > max_results

  context = {'learning_activities': enrolled_activities[0:max_results],
             'teaching_activities': teaching_activities[0:max_results],
             'owned_programs': owned_programs[0:max_results],
             'more_learning': more_learning,
             'more_teaching': more_teaching,
             'more_owned': more_owned}

  return context


def ShowOwned(user):
  """Creates context data for the 'show owned' page.

  Args:
    user: models.GlearnUser.

  Returns:
    Dictionary to construct template.
  """

  program_list = GetUserOwnedPrograms(user)
  for program in program_list:
    EnrichDisplay(program)
  context = {'program_list': program_list}
  return context


def ShowLearning(user):
  """Show the activities that the user is enrolled in.

  Args:
    user: models.GlearnUser.

  Returns:
    Dictionary to construct template.
  """
  activities = _GetUserEnrolledActivities(user, True)
  context = {'activity_list': activities}
  return context


def ShowTeaching(user):
  """Show the activities that the user is teaching.

  Args:
    user: models.GlearnUser.

  Returns:
    Dictionary to construct template.
  """
  activities = _GetUserTeachingActivities(user, True)
  context = {'activity_list': activities}
  return context


def EnrichDisplay(program):
  """Adds attributes to given models.Program for templates/display.

  Args:
    program: A models.Program.

  Attributes added to program:
    instruction_type: In-person, webinar etc.
    program_level: Difficulty level.
    restricted: People who can enroll for the program/activity.
  """

  def GetTagDisplay(tag_to_display_map):
    """Get a display name for program tags in tag_to_display_map."""

    res = []
    for tag, display_name in tag_to_display_map.items():  # Search tags.
      if  tag in program.program_tags:
        res.append(display_name)
    return ', '.join(res)

  program.instruction_type = GetTagDisplay(forms.TYPE_CHOICES_MAP)
  program.program_level = GetTagDisplay(forms.LEVEL_CHOICES_MAP)
  program.restricted = GetTagDisplay(utils.EmployeeType.DISPLAY_MAP)
  program.department = GetTagDisplay(forms.DEPARTMENT_CHOICES_MAP)


def ShowActivity(activity_key, user):
  """Creates context data for the show activity view.

  Args:
    activity_key: Key string of activity to show.
    user: The models.GlearnUser who is requesting the program page.

  Returns:
    Dictionary to construct template.
  """

  # Get the program entity to display.
  activity = utils.GetCachedOr404(activity_key)
  return ShowProgram(activity.parent_key(), user, activity=activity)


def ShowProgram(program_key, user, activity=None):
  """Creates context data for the 'show program' page.

  Args:
    program_key: Key string of program to show.
    user: The models.GlearnUser who is requesting the program page.
    activity: A models.Activity. If provided will only show this activity within
        the program.

  Returns:
    Dictionary to construct template.
  """

  # Get the program entity to display.
  program = utils.GetCachedOr404(program_key)

  user_can_edit_program = user.CanEditProgram(program)
  user_can_create_activity = user.CanCreateActivity(program)

  # Get tags and contact information.
  EnrichDisplay(program)
  contact_email = program.contact_list[0].email()
  contact_name = program.contact_list[0].nickname()
  needs_manager_approval = program.GetRule(
      rules.RuleNames.MANAGER_APPROVAL) is not None

  context = {'program': program,
             'contact_email': contact_email,
             'contact_name': contact_name,
             'user_can_edit_program': user_can_edit_program,
             'user_can_create_activity': user_can_create_activity,
             'needs_manager_approval': needs_manager_approval}

  if activity is None:
    # All activities under a program.
    activities_query = program.ActivitiesQuery()
    # All schedules under a program.
    schedules_query = program.ActivitySchedulesQuery()

    # Prefetch by batches of 1000 instead of default 20
    activities = utils.QueryIterator(activities_query, models.Activity,
                                     prefetch_count=1000, next_count=1000)
    schedules = utils.QueryIterator(schedules_query, models.ActivitySchedule,
                                    prefetch_count=1000,
                                    next_count=1000)
  else:
    # Schedules under the activity.
    activities = [activity]
    schedules = activity.ActivitySchedulesQuery()

    query = program.ActivitiesQuery()
    context['activity_count'] = query.count()
    context['single_activity_mode'] = True

  # When showing a particular activity, we retrieve it even if in the past
  include_past_activities = activity is not None
  # Get the sorted activities with schedule display information for the program.
  activity_info_list = _CreateActivityDisplayHierarchy(
      program, user, activities, schedules, include_past_schedules=True,
      include_past_activities=include_past_activities)

  # Don't show invisible activities unless user can edit the program or we are
  # visiting the program page in single activity mode.
  if user_can_edit_program or context.get('single_activity_mode', False):
    context['activity_list'] = activity_info_list
  else:
    # We filter out invisible activities but the ones that user is teaching or
    # is registered in.
    filtered_info_list = []
    for activity_info in activity_info_list:
      if ((program.visible and activity_info.visible) or
          activity_info.user_can_edit_activity or
          hasattr(activity_info, 'user_register_status')):
        filtered_info_list.append(activity_info)
    context['activity_list'] = filtered_info_list

  return context


def UpdateSettings(request):
  """Handles the user settings page."""
  if request.method == 'POST':
    form = forms.SettingsForm(request.POST)
    if form.is_valid():
      form.UpdateSettings(request.user)
      return http.HttpResponseRedirect(request.POST['referrer'])
  else:
    form_data = forms.SettingsForm.BuildPostData(request.user)
    form = forms.SettingsForm(form_data)

  context = template.RequestContext(request, {'form': form})
  return shortcuts.render_to_response('settings_form.html', context)


def ShowRoster(user, activity_key, order_by='status'):
  """Creates context data for the 'show roster' page.

  Args:
    user: models.GlearnUser making the request.
    activity_key: String key of the activity to show roster for.
    order_by: String. Sort order to be applied for the models.UserRegistration.

  Returns:
    Dictionary to construct template.
  """
  activity = utils.GetCachedOr404(activity_key)
  student_list = RosterUserInfo(activity, user, order_by)

  schedules_query = activity.ActivitySchedulesQuery()
  schedules_query.order('start_time')

  first_schedule = schedules_query[0]

  # last schedule occured, we allow mark as show/no show
  # we check on start_time and not end_time so instructor can mark while
  # last schedule is in progress
  can_edit_activity = user.CanEditActivity(activity)
  mark_attendance_enabled = (first_schedule.start_time <
                             datetime.datetime.utcnow()) and can_edit_activity

  if order_by == 'user':
    order_by_user = '-user'
  else:
    order_by_user = 'user'

  if order_by == 'status':
    order_by_status = '-status'
  else:
    order_by_status = 'status'

  context = {'program': activity.parent(), 'activity': activity,
             'user_list': student_list,
             'mark_attendance_enabled': mark_attendance_enabled,
             'activity_owner': can_edit_activity,
             'order_by': order_by,
             'order_by_user': order_by_user,
             'order_by_status': order_by_status}

  return _EnrichRosterContext(context, user, activity)


def _EnrichRosterContext(context, user, activity):
  """Enriches the given context with attributes required by the roster."""
  enrolled_count = 0
  waitlisted_count = 0
  query = models.UserRegistration.ActiveQuery(activity=activity)
  for registration in query:
    if registration.status == _Status.ENROLLED:
      enrolled_count += 1
    elif registration.status == _Status.WAITLISTED:
      waitlisted_count += 1

  context['enrolled_count'] = enrolled_count
  context['waitlisted_count'] = waitlisted_count

  # Enrich the activity object
  schedules = [s for s in activity.ActivitySchedulesQuery()]
  _EnrichActivities([activity], schedules, user, include_past_schedules=True,
                    include_past_activities=True)

  return context


def ChangeUserStatus(users, activity_or_key, final_status, force_status=False):
  """Unregister/Register already active users for an activity.

  Args:
    users: List of user emails.
    activity_or_key: models.Activity or activity key representing the activity.
    final_status: A utils.RegistrationStatus to which we want to change the user
        status to. Must be one of ENROLLED or UNREGISTERED.
    force_status: A boolean indicating if the final_status should be forced.
  """
  assert final_status in [utils.RegistrationStatus.ENROLLED,
                          utils.RegistrationStatus.UNREGISTERED]

  
  # as in UserRegister
  # Get the registration entity for the current user and activity.
  if isinstance(activity_or_key, models.Activity):
    activity = activity_or_key
  elif isinstance(activity_or_key, db.Key):
    activity = utils.GetCachedOr404(activity_or_key)
  else:
    activity = utils.GetCachedOr404(db.Key(activity_or_key))

  if activity.to_be_deleted:
    return

  for email in users:
    user = utils.GetAppEngineUser(email)
    query = models.UserRegistration.ActiveQuery(activity=activity,
                                                user=user)
    register = query.get()
    if register:
      eval_context = rule_engine.EvalContext.CreateFromUserRegistration(
          register)
      eval_context.force_status = force_status
      if final_status == utils.RegistrationStatus.ENROLLED:
        rule_engine.RegisterOnline(eval_context)
      else:
        rule_engine.UnregisterOnline(eval_context)


def _EnqueueDeleteProgramOrActivityTaskUnsafe(entity, request_user):
  """Enqueues a delayed task that deletes an entity with registered users.

  Args:
    entity: models.Program or models.Activity or their db.Key which needs to be
        deleted.
    request_user: users.User requesting the modification.

  Returns:
    List of entities that were updated due to this action.
  """

  if not isinstance(entity, db.Model):
    entity = utils.GetCachedOr404(entity)

  config = entity.StoreDeleteTaskConfig(request_user)

  task_url = urlresolvers.reverse(tasks.DeleteProgramOrActivity,
                                  kwargs={'config_key': config.key()})
  taskqueue.add(url=task_url, method='GET',
                countdown=60, transactional=True)

  entity_list = entity.MarkToBeDeletedUnsafeAndWrite(request_user)
  return entity_list


def _EnqueueDeleteProgramOrActivityTask(entity, request_user):
  """Runs _EnqueueDeleteProgramOrActivityTaskUnsafe in a transaction."""

  return db.run_in_transaction(_EnqueueDeleteProgramOrActivityTaskUnsafe,
                               entity, request_user)


def DeleteProgram(program_key, request_user):
  """Deletes a program. Wrapper for _EnqueueDeleteProgramOrActivityTask."""
  return _EnqueueDeleteProgramOrActivityTask(program_key, request_user)


def DeleteActivity(activity, request_user):
  """Deletes an activity. Wrapper for _EnqueueDeleteProgramOrActivityTask."""
  return _EnqueueDeleteProgramOrActivityTask(activity, request_user)


def GetUserOwnedPrograms(user):
  """Get a list of display ready programs the user is a owner or contact for.

  Args:
    user: A models.GlearnUser to retrieve programs for.

  Returns:
    A list of models.Program owned by the given user.
  """
  programs = {}

  def AddPrograms(user_filter):
    program_query = models.Program.all()
    utils.AddFilter(program_query, 'deleted =', 0)
    utils.AddFilter(program_query, user_filter, user.appengine_user)
    for program in program_query:
      programs[program.key()] = program

  AddPrograms('owner =')
  AddPrograms('contact_list =')
  AddPrograms('facilitator_list =')

  program_list = list(programs.values())
  program_list.sort(key=lambda program: program.name.lower())
  return program_list


def _GetUserEnrolledActivities(user, include_past_activities=False):
  """Get display information for the activities that a user is enrolled in.

  Warning: Returns activity display information to be rendered by home.html and
  program_detail.html. Do not use the returned data for further processing.

  Args:
    user: The GlearnUser for whom the page is being rendered.
    include_past_activities: boolean to include past activities even if they
      do not have an upcoming schedule.

  Returns:
    A list of activities.
    Each item represents display information for an activity as returned by the
    _EnrichActivities function and then augmented by registration status info
    from _AddRegisterStatusToActivities. In addition, the access point selection
    of the user for a schedule is stored in the attribute 'selected_location'
    for each of the 'sorted_schedules'. This attribute is not present for
    schedules that do not need an access point.
  """
  query = models.UserRegistration.ActiveQuery(user=user.appengine_user)

  # Get a list of activities and schedules.
  activity_list = []
  schedule_location_map = {}
  activity_register_map = {}

  for register in query:
    activity_key = register.GetKey('activity')
    activity_register_map[activity_key] = register
    activity_list.append(activity_key)
    schedule_location_map.update(zip(register.schedule_list,
                                     register.access_point_list))

  activities = request_cache.GetEntitiesFromKeys(activity_list)
  schedules = request_cache.GetEntitiesFromKeys(schedule_location_map.keys())

  assert None not in activities
  assert None not in schedules

  include_past_schedules = include_past_activities

  sorted_activities = _EnrichActivities(activities, schedules, user,
                                        include_past_activities,
                                        include_past_schedules)
  # Add registration status information.
  _AddRegisterStatusToActivities(user, sorted_activities,
                                 activity_register_map)

  ap_key_entity_map = {}
  if sorted_activities:  # Get access points info only when you need it.
    access_points = request_cache.GetEntitiesFromKeys(
        schedule_location_map.values())
    assert None not in access_points
    ap_key_entity_map = dict([(ap.key(), ap) for ap in access_points])

  # Add program name and id information to activities.
  for activity in sorted_activities:
    # Add the Access Points selected information to the schedules.
    for schedule in activity.sorted_schedules:
      location_display = schedule_location_map.get(schedule.key(), None)
      location_display = ap_key_entity_map.get(location_display, None)
      schedule.selected_location = location_display

  return sorted_activities


def _GetUserTeachingActivities(user, include_past_activities=False):
  """Get display information for the activities that a user is teaching.

  Warning: Returns activity display information to be rendered by home.html and
  program_detail.html. Do not use the returned data for further processing.

  Args:
    user: The GlearnUser for whom the page is being rendered.
    include_past_activities: boolean to include past activities even if they
      do not have an upcoming schedule.

  Returns:
    A list activities.
    Each item represents display information for an activity as returned by the
    _EnrichActivities function and then augmented by registration status info
    from _AddRegisterStatusToActivities. In addition, the access point selection
    of the user for a schedule is stored in the attribute 'selected_location'
    for each of the 'sorted_schedules'. This attribute is not present for
    schedules that do not need an access point.
  """
  query = models.ActivitySchedule.ActiveSchedulesQuery()
  query.filter('primary_instructors in', [user.appengine_user])

  include_past_schedules = include_past_activities

  if not include_past_schedules:
    query.filter('end_time > ', datetime.datetime.utcnow())

  schedules = []
  activities = set()
  for schedule in query:
    schedules.append(schedule)
    activities.add(schedule.parent())
    # Primary location is used for instructor location

  assert None not in activities
  assert None not in schedules

  sorted_activities = _EnrichActivities(activities, schedules, user,
                                        include_past_activities,
                                        include_past_schedules)

  return sorted_activities


def _CreateActivityDisplayHierarchy(program, user, activities, schedules,
                                    include_past_activities=False,
                                    include_past_schedules=False):
  """Create Activity and their Schedules hierarchy with their display info.

  Args:
    program: The models.Program for which the list of activities and their
        schedules are collected.
    user: models.GlearnUser for whom the display information is being formatted.
    activities: The models.Activity iterator that has activities to include in
        the display hierarchy.
    schedules: The models.ActivitySchedules iterator that has the schedules to
      include in the display hierarchy.
    include_past_activities: boolean to include past activities even if they
      do not have an upcoming schedule. If true, overrides
      include_past_schedules.
    include_past_schedules: Boolean to include past schedules for activities.

  Returns:
    A sorted list of activities as returned by _EnrichActivities which are then
    enriched by registration info by _AddRegisterStatusToActivities.
  """

  sorted_activities = _EnrichActivities(
      activities, schedules, user, include_past_activities,
      include_past_schedules)

  # Get registrations for the user under this program.
  activity_register_map = _GetUserProgramRegistrations(user.appengine_user,
                                                       program)

  _AddRegisterStatusToActivities(user, sorted_activities, activity_register_map)

  return sorted_activities


def _AddRegisterStatusToActivities(display_user, sorted_activities,
                                   activity_register_map):
  """Add user registration or prediction status to given activities.

  For activities the user is registered, the following attributes are added
  to the sorted_activities argument:
    user_register_status: holds registration status string
    waitlist_rank_info: text description of waitlist rank if waitlisted.
    register_status_reason: text description as to why user status is pending.
  For activities the user is not registered, the following attributes are added
  to the sorted_activities argument:
    predict_open: str for open status, is present when user is predicted to be
      enrolled, or waitlisted but rules other than max people activity.
    predict_restricted: str for denial prediction status, is present when user
      is predicted to be denied enrollment.
    predict_full: str for call full status, is present when the max people for
      activity rule has already allocated max limit of students.
    waitlist_rank_info: text description of how many open seats or how many
      already waitlisted users are there in the course user is trying to join.
    register_status_reason: text description reasons for prediction.

  Args:
    display_user: The models.GlearnUser for whom this display is being prepared.
    sorted_activities: Sorted list of activities to which the function will add
        prediction/registration display information.
    activity_register_map: Dict models.Activity keys to models.UserRegistration
        objects, essentially given the list of registrations to consider for
        processing registration status. If registration for a given activty is
        not found in this dict then the function will try to predict what will
        happen in case of a registration and provide display information.
  """

  max_people_rule_name = rules.RuleNames.MAX_PEOPLE_ACTIVITY
  for activity in sorted_activities:
    if activity.key() in activity_register_map:  # User is enrolled/waitlisted.
      activity.user_register_status = _('Enrolled')
      registration_entity = activity_register_map[activity.key()]
      if registration_entity.status == utils.RegistrationStatus.WAITLISTED:
        # Determine if the user is waiting only for max people in activity rule.
        if registration_entity.OnlyWaitingForMaxPeopleActivity():
          activity.user_register_status = _('Waitlisted')
          activity.waitlist_rank_info = _(
              'rank: %d' % models.UserRegistration.WaitlistRankForUser(
                  activity, display_user.appengine_user))
        else:  # Complicated to display waitlist rank, just say pending.
          activity.user_register_status = _('Pending')
          reasons = [_(str(cfg.GetDescription()))
                     for cfg in registration_entity.affecting_rule_configs]
          activity.register_status_reason = ', '.join(reasons)
    else:  # The user is not registered, we can give a prediction.
      # Add the registration information to the activities.
      # We assume no schedules and access points and hence remove the rule
      # considerations of what the user hasn't selected yet for registration.
      eval_context = rule_engine.EvalContext(
          program=request_cache.GetEntityFromKey(activity.parent_key()),
          activity=activity,
          user=display_user,
          creator=display_user,
          schedule_list=[],
          access_point_list=[])

      prediction = rule_engine.PredictRegistrationOutcome(eval_context)

      status = prediction['final_status']

      max_people_remaining = None  # None => No max person activity rule.
      resources_and_rules = zip(prediction['all_rule_resources_remaining'],
                                prediction['all_rule_configs'])
      for resource_remaining, rule_config in resources_and_rules:
        if rule_config.rule_name == max_people_rule_name:
          # Adding 1 since resource rule is counting the virtual prediction.
          max_people_remaining = resource_remaining + 1
          break

      if status == utils.RegistrationStatus.ENROLLED:
        activity.predict_open = _('OPEN')
        if max_people_remaining is not None:
          activity.waitlist_rank_info = _('remaining: %d' %
                                          max_people_remaining)
      elif status is None:  # Predicted to deny registration.
        activity.predict_restricted = _('RESTRICTED')
        reasons = [_(str(cfg.GetDescription()))
                   for cfg in prediction['affecting_rule_configs']]
        activity.register_status_reason = ','.join(reasons)
      elif status == utils.RegistrationStatus.WAITLISTED:
        # Check if max people activity affected a waitlist decision.
        affecting_rule_names = [c.rule_name
                                for c in prediction['affecting_rule_configs']]
        if max_people_rule_name in affecting_rule_names:
          activity.predict_full = _('FULL')
          assert max_people_remaining is not None
          waitlisted = -max_people_remaining
          activity.waitlist_rank_info = _('waitlisted: %d' % waitlisted)
        else:  # Waitlisted without max people activity limitation.
          activity.predict_open = _('OPEN')
          if max_people_remaining is not None:
            activity.waitlist_rank_info = _('remaining: %d' %
                                            max_people_remaining)


def RosterEnroll(request, program, activity):
  """Enroll students to given activity."""
  data = {'program': program, 'activity': activity}
  return _EnrichRosterContext(data, request.user, activity)


def CreateOrUpdateProgram(request, program=None):
  """Creates a new program or updates an existing program from a post request.

  Args:
    request: The form post request that should be used to configure a program.
    program: models.Program to be updated. If None, a new program is created.

  Returns:
    Renders the resultant page. Redirects to the ShowProgram page on successful
    update/create of a program. When create/update fails due to validation then
    the program form used to submit the post request is rendered back with error
    messages.
  """

  is_update = False
  if program is not None:
    is_update = True

  if request.method == 'POST':
    form = forms.ProgramForm(request.POST, request.FILES)
    if form.is_valid():
      program = form.CreateOrUpdateProgram(request.user.appengine_user,
                                           program=program)
      if program:
        return http.HttpResponseRedirect(urlresolvers.reverse(
            'ShowProgram',
            kwargs=dict(program_key=program.key())
        ))
  else:
    if program:  # Implies that user wants to update an existing program.
      form_data = forms.ProgramForm.BuildPostData(program)
      form = forms.ProgramForm(form_data)
      assert form.is_valid()
    else:  # User wants to create a new program.
      form = forms.ProgramForm(initial={'contact_person': request.user.email,
                                        'facilitator': request.user.email})

  context = template.RequestContext(request,
                                    {'form': form, 'is_update': is_update})
  return shortcuts.render_to_response('program_form.html', context)


def RosterUserInfo(activity, glearn_user, order_by='status'):
  """Construct the user list registered for an activity and user information.

  Args:
    activity: The models.Activity for which we need to build the roster.
    glearn_user: The models.Glearnuser object who is requesting the roster page.
    order_by:  String. Sort order to be applied for the models.UserRegistration.

  Returns:
    Returns a list of user information dictionaries. Each dictionary contains
    relevant user display information like name, department etc.
  """

  # Query all active registrations for this activity.
  query = models.UserRegistration.ActiveQuery(activity=activity)
  # Any new supported order needs to have corresponding indexes.
  assert order_by in ['status', 'user', '-status', '-user']
  query.order(order_by)

  STATUS_DISPLAY = {
      _Status.ENROLLED: 'Enrolled', _Status.WAITLISTED: 'Waitlisted',
  }
  # Remove registrations that are not Enrolled or WAITLISTED.
  registration_list = []
  for registration in query:
    if (registration.status == _Status.ENROLLED or
        registration.status == _Status.WAITLISTED):
      registration_list.append(registration)

  # Get user's information.
  email_list = [r.user.email() for r in registration_list]
  try:
    user_service = service_factory.GetUserInfoService()
    person_hash = user_service.GetUserInfoMulti(email_list)
    # Suppress pylint catch Exception
    # pylint: disable-msg=W0703
  except errors.ServiceCriticalError, exception:
    logging.error('[%s] %s', type(exception), exception)
    person_hash = {}

  # Update the registration_list with additional information what we wish to
  # show in the that we are going to display in the page.
  roster_list = []
  for registration in registration_list:
    email = registration.user.email()
    queue_time = glearn_user.GetLocalTime(registration.queue_time)
    attended = False
    no_show = False
    if registration.attendance == utils.RegistrationAttend.ATTENDED:
      attended = True
    if registration.attendance == utils.RegistrationAttend.NO_SHOW:
      no_show = True

    display_info = {
        'department': _('Department'),
        'email': email,
        'location': '--',
        'name': email,
        'queue_time_local': queue_time,
        'register_status': _(STATUS_DISPLAY[registration.status]),
        'title': '--',
        'attended': attended,
        'no_show': no_show,
        'enrolled': registration.status == utils.RegistrationStatus.ENROLLED
    }

    # Add display information from person object if present.
    user_info = person_hash.get(email)
    if user_info:
      display_info['department'] = user_info.department
      display_info['location'] = user_info.location
      display_info['name'] = user_info.name
      display_info['title'] = user_info.title
      display_info['photo_url'] = user_info.photo_url

    roster_list.append(display_info)

  return roster_list


def UserRegister(post_data, glearn_user):
  """Registers a user in an activity using information from register data.

  Args:
    post_data: The post data that was submitted for registration. It contains
        information like the user, the activity and the location selections for
        each schedule required to complete the user registration.
    glearn_user: The models.GlearnUser who submitted the request.

  Returns:
    List of models.GlearnUser registered.
  """

  # Get program and activity.
  activity_key = db.Key(post_data['activity_id'])

  # Make sure that the activity is not about to be deleted.
  activity = utils.GetCachedOr404(activity_key)
  if activity.to_be_deleted:
    return []

  force_status = False
  if post_data['users']:
    # Someone is trying to register multiple users.
    # People can land on this url only if they have proper credentials to start
    # with. If not, someone is trying to hack the system
    assert glearn_user.CanEditActivity(activity)
    user_emails = post_data['users'].strip().split(',')
    force_status = post_data['force_status'] == '1'
    glearn_users = models.GlearnUser.GetOrCreateUsers(user_emails, True)
  else:
    # User is trying to register themselves.
    glearn_users = {glearn_user.email: glearn_user}

  for user in glearn_users.itervalues():
    # Check that all users are available. If not, we don't try any of them.
    if not user:
      return []
  # Get schedule to access point choice.
  # Each schedule can either have:
  #  1 - its own access point
  #  2 - share the same common access point
  #  The POST data contains key, values in the form:
  #  1 - select_key / access_point_key  for case #1
  #  2 - select_ / access_point_key   for case #2

  schedule_choice = {}
  common_access_point = None

  prefix = 'schedule_'

  if prefix in post_data:
    # Single access point applies to all schedules
    common_access_point = db.Key(post_data[prefix])
  else:
    # Each schedule has its own access point
    for key, value in post_data.items():
      if key.startswith(prefix):
        schedule_key = db.Key(key[len(prefix):])
        schedule_choice[schedule_key] = db.Key(value)

  # Validate schedule_choice, make ordered list of schedules and access points.
  schedules_query = activity.ActivitySchedulesQuery()
  schedules_query.order('start_time')

  schedule_list = []
  access_point_key_list = []
  for schedule in schedules_query:
    schedule_key = schedule.key()
    if common_access_point:
      access_point = common_access_point
    else:
      access_point = schedule_choice[schedule_key]
    assert (access_point in schedule.access_points or
            access_point in schedule.access_points_secondary)

    schedule_list.append(schedule)
    access_point_key_list.append(access_point)

  assert schedule_list  # Atleast one schedule.
  assert not schedule_choice or len(schedule_choice) == len(schedule_list)

  registered = []
  creator = glearn_user
  # Record the time of registration
  queue_time = datetime.datetime.utcnow()

  access_points = request_cache.GetEntitiesFromKeys(access_point_key_list)
  program = request_cache.GetEntityFromKey(activity.parent_key())

  for user in glearn_users.itervalues():
    # TODO(user): keep track of a list of users which could not be registered
    # and send feedback to client in case something goes south ?
    # Probably do registration in ajaxy fashion from client side instead.
    
    # Build an eval context.

    eval_context = rule_engine.EvalContext(
        queue_time, program, activity, user, creator,
        schedule_list, access_points, force_status=force_status)

    # Send notifications
    notify = post_data['notify'] != '0'

    # Run against the rule engine.
    final_status, unused_messages = rule_engine.RegisterOnline(eval_context,
                                                               notify)
    if final_status is not None:
      registered.append(user)

  return registered


def CreateOrUpdateActivity(request, program, activity=None):
  """Creates or updates an activity.

  Caller must provide the program. Activity is optional when creating a new one.

  Args:
    request: A request.
    program: A models.Program under which we are either creating or updating
      the activity.
    activity: Optional activity. If available, this method will handle the
      update of the given activity. If not available a new one is created.

  Returns:
    http response.
  """
  is_update = activity is not None

  if activity:
    assert activity.parent() == program

  activity_formset = formsets.formset_factory(forms.ActivityScheduleForm,
                                              formset=
                                              forms.ActivityScheduleFormSet,
                                              extra=0, can_delete=True)
  if request.method == 'POST':
    formset = activity_formset(request.POST, request.FILES)

    if formset.PrepareCreateUpdate(request.user, program, activity):
      formset.CreateUpdateSchedules(activity)
      return http.HttpResponseRedirect(urlresolvers.reverse(
          'ShowProgram',
          kwargs=dict(program_key=program.key())))
    else:
      #Some errors are in the forms
      if not formset.IsScheduleAvailable():
        #We undo the delete in every form we send back. User can not delete
        #all forms.
        for index in range(len(formset.forms)):
          #We need to change the data in the request form because the deletion
          #field is a special field added at the formset level, not directly
          #accessible at the form level like anyother field/form attribute.
          #There is probably a way to set the value of deletion to false, but
          #nothing straightforward/obvious, so changing POST data instead.
          param_id = 'form-%s-%s' % (index, formsets.DELETION_FIELD_NAME)
          request.POST[param_id] = ''
          assert not formset.forms[index].IsDeleted()

  else:  #GET
    if is_update:
      form_data = forms.ActivityScheduleFormSet.BuildPostData(request.user,
                                                              activity)
      formset = activity_formset(form_data)
      assert formset.is_valid()
    else:  # User wants to create a new activity.
      user_now = request.user.GetLocalTime(datetime.datetime.utcnow())
      user_now = user_now.replace(second=0, microsecond=0)
      a_start = user_now + datetime.timedelta(minutes=60)
      a_end = a_start + datetime.timedelta(minutes=60)
      a_start_time = format.FormatTime(a_start)
      a_end_time = format.FormatTime(a_end)
      formset = activity_formset(initial=[{'start_date': a_start.date(),
                                           'start_time': a_start_time,
                                           'end_date': a_end.date(),
                                           'end_time': a_end_time,
                                           'owner': program.owner.email}])

  # We put the access point rooms.
  access_points_info = ap_utils.GetAccessPointsInfo(utils.AccessPointType.ROOM)

  access_point_names = simplejson.dumps(access_points_info['uris'])
  access_point_keys = simplejson.dumps(access_points_info['keys'])
  access_point_tzs = simplejson.dumps(access_points_info['timezone_names'])

  data = {'formset': formset,
          'is_update': is_update,
          'program': program,
          'access_point_names': access_point_names,
          'access_point_keys': access_point_keys,
          'access_point_tzs': access_point_tzs}
  context = template.RequestContext(request, data)
  return shortcuts.render_to_response('manage_activity.html', context)


def UpdateCalendarSessionToken(request, redirect_path):
  """Updates session tokens for role account when needed or when forced.

  Args:
    request: Http request
    redirect_path: Redirect path for the calendar API after user grants access.

  Returns:
    A http redirect response to the auth token url.
  """

  redirect_url = 'http://' + request.get_host() + redirect_path
  auth_url = calendar.CalendarTokenRequestUrl(redirect_url)
  return http.HttpResponseRedirect(auth_url)


def StoreCalendarSessionToken(request):
  """Stores the authentication tokens that are given as a redirect."""

  calendar.StoreCalendarSessionToken(request.get_full_path())


def ResetDatastoreSync():
  """Reset the datastore sync process to start over."""
  query_processor.ResetQueryWork(query_processor.SYNC_DATASTORE_ENTITIES)


def BeginConferenceRoomsStorage():
  """Marks the beginning of a new conference rooms collection task."""

  run_id = str(uuid.uuid4())
  ap_utils.CreateConferenceRoomRunConfig(run_id)

  deferred.defer(ap_utils.StartRoomsSync, run_id)


def FetchAndStoreConferenceRooms(query_offset, num_rooms_to_fetch):
  """Queries RoomInfoService for rooms and stores them as access points.

  Args:
    query_offset: The int offset after which the rooms should be queried from.
    num_rooms_to_fetch: Int number of rooms to fetch.
  """
  ap_utils.StoreConferenceRoomsAsAccessPoints(query_offset, num_rooms_to_fetch)


def ConstructAccessPointsInfo():
  """Loads access points info and saves it in datastore config object."""
  ap_utils.UpdateAccessPointsInfo(utils.AccessPointType.ROOM)


def RunDeferred(request):
  """Executes deferred tasks by invoking the deferred api handler."""
  # Log some information about the task we're executing
  headers = ['%s:%s' % (k, v) for k, v in request.META.items()
             if k.lower().startswith('x-appengine-')]
  logging.info('Request META = %s', ', '.join(headers))

  try:
    deferred.run(request.raw_post_data)
  except deferred.PermanentTaskFailure, e:
    logging.exception(
        'Deferred Run: Permanent failure in deferred run. Exception = %s', e)

  return http.HttpResponse()


def ShowManagerApprovals(request):
  """Updates approvals in post message and show the pending approvals page.

  Args:
    request: The view request object.

  Returns:
      A template.RequestContext.
  """
  approve = False
  approval_keys = []
  updated_approvals = []

  # Get the information necessary to update a pending approvals page.
  pending_approvals_query = models.ManagerApproval.GetPendingApprovalsQuery(
      request.user.appengine_user)
  pending_approvals_display = [approval for approval in pending_approvals_query]

  # Add candiate_info candidate organizational information to render the page.
  email_list = [approval.candidate.email()
                for approval in pending_approvals_display]

  try:
    user_service = service_factory.GetUserInfoService()
    person_hash = user_service.GetUserInfoMulti(email_list)
    # Suppress pylint catch Exception
    # pylint: disable-msg=W0703
  except errors.ServiceCriticalError, exception:
    logging.error('[%s] %s', type(exception), exception)
    person_hash = {}

  for approvals_display in pending_approvals_display:
    # Get manager localized request initiation time.
    approvals_display.queue_time_local = request.user.GetLocalTime(
        approvals_display.queue_time)
    # Get candidate information.
    candidate_email = approvals_display.candidate.email()
    approvals_display.candidate_info = person_hash.get(candidate_email)

  # Perform the updates that are requested in the POST message.
  if request.method == 'POST':
    post_approval_keys = request.POST.get('approval_keys', '')
    if post_approval_keys:
      approval_keys = post_approval_keys.strip().split(',')
      approval_keys = [str(approval_key.strip())
                       for approval_key in approval_keys]
      approve = str(request.POST.get('approve', '0')).strip() == '1'

      # Perform updates on approvals if required.
      updated_approvals = _UpdateManagerApprovals(request,
                                                  approval_keys, approve)

  # Remove the updated approvals from the pending_approvals_display.
  updated_keys = [approval.key() for approval in updated_approvals]
  pending_approvals_display = [approval
                               for approval in pending_approvals_display
                               if approval.key() not in updated_keys]

  extra_context = {}
  extra_context['pending_approvals'] = pending_approvals_display

  # Construct display message for the approvals page.
  if approval_keys:  # Had to do some updates.
    display_msg = ''
    explain_msg = ''
    successful_users = [approval.candidate.nickname()
                        for approval in updated_approvals]
    if successful_users:
      approve_msg = _('Declined')
      if approve:
        approve_msg = _('Approved')
      if len(successful_users) == 1:
        display_msg = '%s %s.' % (approve_msg, successful_users[0])
      else:  # > 1
        display_msg = '%s %d approvals.' % (approve_msg, len(successful_users))
        explain_msg = '%s: %s' % (approve_msg, ', '.join(successful_users))
    # Look for failures.
    number_failed = len(approval_keys) - len(successful_users)
    if number_failed:
      display_msg += ' Failed to update %d approvals.' % number_failed

    extra_context['confirm_msg'] = display_msg
    extra_context['explain_confirm_msg'] = explain_msg

  context = template.RequestContext(request, extra_context)

  template_name = 'manager_approvals_pending.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


def _UpdateManagerApprovals(request, approval_keys, approve):
  """Accept manager approval decisions.

  Args:
    request: The view request object.
    approval_keys: str key list referring to a models.ManagerApproval objects.
    approve: Bool True to approve and False to decline.

  Returns:
    A list of updated models.ManagerApproval entities. The entities that failed
    to updated are not included in the list.
  """

  if not approval_keys: return []

  updated_approvals = []
  try:
    for approval_key in approval_keys:
      updated_approval = _UpdateManagerApprovalSafe(request.user,
                                                    approval_key, approve)
      if updated_approval:
        updated_approvals.append(updated_approval)
    # Suppress pylint catch Exception
    # pylint: disable-msg=W0703
  except Exception, exception:
    logging.error('[%s] %s', type(exception), exception)
    # We attempt to give the information back to the user on what ever went
    # through successfuly.

  return updated_approvals


def _UpdateManagerApprovalSafe(request_user, approval_key, approve):
  """Accept manager approval decision.

  Args:
    request_user: models.GlearnUser object requesting the update.
    approval_key: str key referring to a models.ManagerApproval object.
    approve: Bool True to approve and False to decline.

  Returns:
    The updated models.ManagerApproval object, None if approval wasn't updated.
  """
  # Check if approval object exists and if user is the manager.
  approval_key = db.Key(approval_key)
  approval = db.get(approval_key)
  if approval is None or not request_user.CanEditManagerApproval(approval):
    return None  # Approval object not present or user doesn't have permissions.

  def UpdateManagerApprovalUnsafe():
    """Store approval decision if manager decision not already present."""
    # Reload approval inside transaction to get latest version
    approval = db.get(approval_key)
    if approval.manager_decision:
      return None

    deferred.defer(rule_engine.SaveRuleTagsToReprocess, [approval.key().name()],
                   _transactional=True)

    approval.manager_decision = True
    approval.approved = approve
    approval.put()
    return approval

  # Update and return the approval in a transaction.
  return db.run_in_transaction(UpdateManagerApprovalUnsafe)


def Search(request):
  """Generates context to render the search results page."""

  max_programs_per_search = 30

  search_text = request.REQUEST.get('search_text', '')
  search_location = request.REQUEST.get('search_location', '')
  search_start_date = request.REQUEST.get('search_start_date', '')
  search_end_date = request.REQUEST.get('search_end_date', '')

  search_context = {'search_text': search_text,
                    'search_location': search_location,
                    'search_start_date': search_start_date,
                    'search_end_date': search_end_date}

  # Check if we need to search all courses.
  search_context['search_show_advanced'] = (search_location or
                                            search_start_date or
                                            search_end_date)

  search_error_list = []

  # Parse start and end dates.
  def ParseAndGetUTCTime(date_str, request_user):
    """Converts given date string to utc datetime based on user timezone."""
    try:
      if not date_str: return None
      sp = [int(d) for d in date_str.split('-')]
      filter_time = datetime.datetime(sp[0], sp[1], sp[2])
      return request_user.GetUtcTime(filter_time)
    # invalid user time
    # pylint: disable-msg=W0703
    except Exception:
      search_error_list.append(_('%s is not a valid date' % date_str))
      return None

  start_time = ParseAndGetUTCTime(search_start_date, request.user)
  end_time = ParseAndGetUTCTime(search_end_date, request.user)

  # Checks for start and end date errors.
  if search_error_list:
    search_context['search_error_list'] = search_error_list
    return search_context

  # Get the service that implements search functionality.
  search_service = service_factory.GetSearchService()

  result_program_objects = search_service.Search(
      search_text=search_text, search_location=search_location,
      search_start_time=start_time, search_end_time=end_time,
      max_results=max_programs_per_search)

  logging.info('retrieved %d search results', len(result_program_objects))
  search_context['search_results'] = result_program_objects

  return search_context
