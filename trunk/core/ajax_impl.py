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


"""Has utility methods that ajax modul use to implement their functionality."""

# Supress pylint invalid import order
# pylint: disable-msg=C6203



from django.utils import translation
from google.appengine.ext import db
from core import errors
from core import models
from core import rule_engine
from core import service_factory
from core import utils

_ = translation.ugettext


def DeleteProgramPopupForm(program):
  """Function that generates data to render the delete program popup form.

  Args:
    program: models.Program to be deleted.

  Returns:
    A dictionary with attributes relevant to the popup template.
  """
  activities = models.Program.ActivitiesQueryFromKey(
      program.key(), keys_only=True)

  registrations_count = 0
  activities_count = 0
  for activity_key in activities:
    registrations_count += models.UserRegistration.NumberRegisteredForActivity(
        activity_key)
    activities_count += 1

  data = {'registrations_count': registrations_count,
          'activities_count': activities_count,
          'program_key': str(program.key())}
  return data


def RegisterPopupForm(request, program_key, activity_key, users=None,
                      notify='1', force_status='0'):
  """Function that generates data to render the registration popup form.

  Generates html to render a form required to select access points when the user
  tries to register to an activity.

  Args:
    request: Request object provided for django view functions.
    program_key: The key of the program under which the given activity id lives.
    activity_key: The activity key that identifies the activity for which the
      registration information like the schedules and access points should be
      provided for to the user in a form.
    users:  String of comma separated emails to register. If not provided,
      current user is used.
    notify: Will not send notifications when notify is '0'.
    force_status: Will force register users when it is '1'

  Returns:
    A dictionary with attributes relevant to the popup template:
      schedule_list: List of dictionaries with data relevant to each schedule:
        key: Key of the schedule
        start_time_local: Display time of the schedule
        access_point_list: List of {key: access_point_key,
          display: access_point_display} for the schedule

      activity_key: Key of the activity
      program_key: Key of the program
      notify: 0 or 1 depending on whether we send email notifications or not
      common_access_points: Optional list of access points. Present only if all
        schedules share the same list of access points. If not available, each
        schedule access points is in the schedule dictionary.
  """
  # Get the schedules.
  schedules_query = models.Activity.SchedulesQueryFromActivityKey(activity_key)
  schedules_query.order('start_time')

  # Get the access point to load and make a list of schedules.
  schedules_list = []
  access_point_keys = set()
  access_points_secondary_keys = set()

  common_access_points = set()
  same_access_points = True

  for schedule in schedules_query:
    all_access_points = schedule.GetAllAccessPoints()
    if same_access_points:
      if not common_access_points:
        # We populate the set for the first time
        common_access_points.update(all_access_points)
      elif common_access_points != all_access_points:
        # Access points are different
        same_access_points = False

    schedules_list.append(schedule)
    access_point_keys.update(schedule.access_points)
    access_points_secondary_keys.update(schedule.access_points_secondary)

  access_point_keys.update(access_points_secondary_keys)
  # Load all the access points that are of interest.
  access_points = db.get(list(access_point_keys))
  assert None not in access_points
  access_points = dict(zip(access_point_keys, access_points))

  user = request.user
  schedule_info_list = []
  for schedule in schedules_list:
    schedule_info = {}

    # Format session times to display.
    schedule_info['key'] = str(schedule.key())
    schedule_info['start_time_local'] = user.GetLocalTime(schedule.start_time)

    # Add the access points that are available for each schedule.
    access_point_list = []
    for access_point_key in schedule.GetAllAccessPoints():
      access_point_display = str(access_points[access_point_key])
      if access_point_key in access_points_secondary_keys:
        access_point_display += ' (P)'
      access_point_list.append({'key': str(access_point_key),
                                'display': access_point_display})

    # sort access points by name
    schedule_info['access_point_list'] = sorted(access_point_list,
                                                key=lambda x: x['display'])

    # Add the schedule info to the list
    schedule_info_list.append(schedule_info)

  data = {'schedule_list': schedule_info_list,
          'activity_key': activity_key,
          'program_key': program_key,
          'notify': notify,
          'force_status': force_status}

  if same_access_points:
    data['common_access_points'] = schedule_info_list[0]['access_point_list']

  if users:
    data['users_count'] = len(users.split(','))
    data['users'] = users
  return data


def ValidateEmails(contacts):
  """Checks validity of given emails.

  Args:
    contacts: Comma separated list of emails.

  Returns:
    A list of {input:input, email: email, name:name} where:
      - input is the original input processed
      - email is the resulting email or None if input invalid
      - name is a display name for the given input or None.
  """
  contacts = [c.strip() for c in contacts.strip().split(',') if c.strip()]
  contact_emails = [utils.GetEmailAddress(c) for c in contacts]
  try:
    user_service = service_factory.GetUserInfoService()
    person_hash = user_service.GetUserInfoMulti(contact_emails)
  # Suppress pylint catch Exception
  # pylint: disable-msg=W0703
  except errors.ServiceCriticalError:
    person_hash = {}

  res = []
  for contact, contact_email in zip(contacts, contact_emails):
    item = {'input': contact, 'email': contact_email, 'name': contact}
    if contact_email in person_hash:
      item['name'] = person_hash[contact_email].name
    res.append(item)

  return res


def UserAttendance(activity, contacts, attended):
  """Records user attendance for an activity.

  Args:
    activity: models.Activity to register attendance for.
    contacts: Comma separated list of emails.
    attended: String 'True' or 'False' indicating attendance.

  Returns:
    Dictionary of {email:True or False if attendance could not be recorded}.
  """
  contacts = [c.strip() for c in contacts.strip().split()]

  res = {}
  for contact in contacts:
    user = utils.GetAppEngineUser(contact)
    lock = rule_engine.RegistrationLock(user, activity.key())
    res[contact] = lock.RunSynchronous(_UserAttendanceUnsafe, activity, user,
                                       attended) is not None
  return res


def _UserAttendanceUnsafe(activity, user, attended):
  reg = models.UserRegistration.ActiveQuery(activity=activity, user=user).get()

  if reg:
    if attended == 'True':
      reg.attendance = utils.RegistrationAttend.ATTENDED
    else:
      reg.attendance = utils.RegistrationAttend.NO_SHOW
    reg.put()
    return reg
  else:
    return None


def DeleteActivityPopupForm(activity):
  """Function that generates data to render the delete activity popup form.

  Args:
    activity: The activity to be deleted.

  Returns:
     A dictionary with attributes relevant to the popup template.
  """
  query = models.UserRegistration.ActiveQuery(activity=activity.key())
  students_count = query.count()
  data = {'students_count': students_count,
          'activity_key': activity.key()}
  return data

