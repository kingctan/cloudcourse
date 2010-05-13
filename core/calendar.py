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


"""Calendar utilities."""



import logging
import os
import re

import atom
from django import template
from django.template import loader
from gdata import auth
from gdata import calendar
from gdata import service
from gdata.alt import appengine as gdata_appengine
from gdata.calendar import service as calendar_service
from google.appengine.api import memcache
from google.appengine.ext import db

import settings
from core import models
from core import request_cache
from core import utils

_ACCEPTED_STATUS = calendar.AttendeeStatus()
_ACCEPTED_STATUS.value = 'ACCEPTED'
_CALENDAR_TOKEN_KEY_NAME = 'role_account_session_key'
_REQUIRED_TYPE = calendar.AttendeeType()
_REQUIRED_TYPE.value = 'REQUIRED'
_TO_DELETE_KEY_NAME = 'calendar_events_to_delete_key'


def _GetCalendarService(refresh_memcache=False):
  """Create gdata calendar service with a valid session id.

  Creates a gdata calendar service. Uses session key from memcache when
  available. On a memcache miss, loads the session key from datastore. Tries to
  return a usable calendar service and None if it fails to create one.

  Args:
    refresh_memcache: Force a memcache session key refresh from datastore.

  Returns:
    A gdata.calendar.service.CalendarService
  """
  # Initialize calendar service for AppEngine.
  headers = {'X-Redirect-Calendar-Shard': 'true'}
  calendar_client = calendar_service.CalendarService(additional_headers=headers)
  gdata_appengine.run_on_appengine(calendar_client, store_tokens=False,
                                   single_user_mode=True, deadline=10)

  session_token = None
  memcache_key = 'memcache_'+ _CALENDAR_TOKEN_KEY_NAME
  if not refresh_memcache:
    session_token = memcache.get(memcache_key)

  if session_token is None:  # Memcache miss, load from datastore.
    config_entity = models.Configuration.get_by_key_name(
        _CALENDAR_TOKEN_KEY_NAME
    )
    if not config_entity or not config_entity.config_value: return None
    session_token = config_entity.config_value
    memcache.set(memcache_key, session_token)  # Place in memcache.

  token = auth.AuthSubToken()
  token.set_token_string(session_token)
  calendar_client.current_token = token

  return calendar_client


def CalendarTokenRequestUrl(redirect_path):
  """Constructs a calendar token request url.

  Args:
    redirect_path: The url that should be called back with the auth token.

  Returns:
    A string url that can be used to redirect the user to provide auth tokens
    to calendar.
  """
  scopes = service.lookup_scopes('cl')
  domain = os.environ['AUTH_DOMAIN']
  if domain.lower() == 'gmail.com':
    domain = 'default'
  token_request_url = auth.generate_auth_sub_url(
      redirect_path, scopes, secure=False, session=True, domain=domain
  )
  return token_request_url


def StoreCalendarSessionToken(relative_url):
  """Extract calendar auth tokens from url and store them in the datastore.

  Args:
    relative_url: The url that was called by the calendar token system with
        token information in it.
  """
  # Get auth token from url.
  auth_token = auth.extract_auth_sub_token_from_url(relative_url)
  assert auth_token

  # Upgrade to session token.
  calendar_client = calendar_service.CalendarService()
  gdata_appengine.run_on_appengine(calendar_client, store_tokens=False,
                                   single_user_mode=True, deadline=10)
  session_token = calendar_client.upgrade_to_session_token(auth_token)
  assert session_token

  # Write session token to datastore.
  session_token_str = session_token.get_token_string()
  config = models.Configuration(key_name=_CALENDAR_TOKEN_KEY_NAME,
                                config_value=session_token_str,
                                config_key=_CALENDAR_TOKEN_KEY_NAME)
  config.put()

  # Refresh memcache session token and make sure a usable calendar client can be
  # created.
  calendar_client = _GetCalendarService(refresh_memcache=True)
  assert calendar_client is not None


def _GetCalendarEvents(event_hrefs, batch_ids=None, check_failures=True):
  """Get calendar events given edit hrefs and corresponding batch ids.

  Args:
    event_hrefs: list of string calendar event hrefs.
    batch_ids: optional list of string id's that are stamped on the calendar
        events returned for identification that can be used to map events.
    check_failures: When set to True throws exception if some of the events were
        not retrieved.

  Returns:
    An array of gdata.calendar.CalendarEventEntry objects.
  """
  logging.debug('Entering _GetCalendarEvents')
  if not event_hrefs: return []

  batch_ids = batch_ids or [str(num) for num in xrange(len(event_hrefs))]
  # Prepare batch query.
  request_feed_query = calendar.CalendarEventFeed()
  for edit_href, batch_id in zip(event_hrefs, batch_ids):
    request_feed_query.AddQuery(url_string=edit_href, batch_id_string=batch_id)

  result_arr = _ExecuteBatchQuery(request_feed_query,
                                  check_failures=check_failures)
  logging.debug('Exiting _GetCalendarEvents')
  return result_arr


def _ExecuteBatchQuery(feed_query, accept_status_codes=None,
                       check_failures=True):
  """Executes given batch query and returns result events of the batch queries.

  Args:
    feed_query: A gdata.calendar.CalendarEventFeed with batch queries.
    accept_status_codes: The list of status codes acceptable for query results.
        By default status code '200' is used as acceptable.
    check_failures: If set to True then checks that all queries have been
        executed and that all of them return status codes specified in
        accept_status_codes above.

  Returns:
    An array of gdata.calendar.CalendarEventEntry result objects.
  """
  logging.debug('Entering _ExecuteBatchQuery')
  # Perform batch query.
  calendar_client = _GetCalendarService()
  response_feed = calendar_client.ExecuteBatch(
      feed_query, settings.CALENDAR_BATCH_EVENT_FEED
  )

  # Process query results.
  result_arr = []
  accept_status_codes = accept_status_codes or ['200']
  for entry in response_feed.entry:
    if check_failures:
      assert entry.batch_status.code in accept_status_codes
    result_arr.append(entry)

  # Make sure everything was collected.
  if check_failures:
    assert len(result_arr) == len(feed_query.entry)

  logging.debug('Exiting _ExecuteBatchQuery')
  return result_arr


def _UpdateCalendarEvents(calendar_events, update_func, check_failures=True):
  """Batch update given calendar events with given update function.

  Args:
    calendar_events: List of gdata.calendar.CalendarEventEntry to update.
    update_func: A function that can accept a gdata.calendar.CalendarEventEntry.
        This function is called for each calendar event and is expected to
        update the calendar event as it sees fit.
    check_failures: When set to True throws exception if some of the events were
        not retrieved.

  Returns:
    An array of updated gdata.calendar.CalendarEventEntry objects.
  """
  logging.debug('Entering _UpdateCalendarEvents')
  request_feed_update = calendar.CalendarEventFeed()
  for event in calendar_events:
    update_func(event)
    request_feed_update.AddUpdate(event)

  # Batch execute.
  result = _ExecuteBatchQuery(request_feed_update,
                              check_failures=check_failures)
  logging.debug('Exiting _UpdateCalendarEvents')
  return result


def _RemoveUsersFromEvents(calendar_events, check_failures=True):
  """Removes all attendees from given calendar events.

  Args:
    calendar_events: List of gdata.calendar.CalendarEventEntry to update.
    check_failures: When set to True throws exception if some of the events were
        not retrieved.

  Returns:
    An array of updated gdata.calendar.CalendarEventEntry objects.
  """
  logging.debug('Entering RemoveUsersFromEvents')

  def RemoveAttendeesFromEvent(event):
    """Function that removes all attendees from an event."""
    event.who = []

  result = _UpdateCalendarEvents(calendar_events, RemoveAttendeesFromEvent,
                                 check_failures=check_failures)
  logging.debug('Exiting RemoveUsersFromEvents')
  return result


def _MakeCalendarBody(schedule, activity, program):
  """Make up the text that forms the content of the calendar.

  The content of the calendar will have some program description of the activity
  and utility links that will help the user to reach the activity page easily to
  perform tasks like unregistration etc.

  Args:
    schedule: models.ActivitySchedule corresponding to the calendar event.
    activity: models.Activity to which the schedule belongs.
    program: models.Program to which the schedule belongs.

  Returns:
    Str contents that will form the content of the calendar event.
  """
  template_name = 'calendar_schedule.html'

  context_values = {
      'schedule': schedule, 'activity': activity,
      'program': program, 'hostname': settings.DATABASE_OPTIONS['remote_host'],
  }
  context = template.Context(context_values)
  body = loader.render_to_string(template_name,
                                 context_instance=context)

  return body


def _GetScheduleEmailsForCalendar(schedule):
  """Get the emails relevant to a schedule to send calendar invites to.

  Get the email addresses of instructors and access point resource calendar
  email ids.

  Args:
    schedule: models.ActivitySchedule for which we need the invite email ids.

  Returns:
    Array of str email ids.
  """
  logging.debug('Entering _GetScheduleEmailsForCalendar')
  if schedule is None: return []

  email_set = set()

  # Add instructors to who list.
  for instructor in schedule.primary_instructors:
    email_set.add(instructor.email())

  activity = utils.GetCachedOr404(schedule.parent_key())
  if activity.reserve_rooms:
    # Add rooms if we have calendar names.
    access_point_key_list = (schedule.access_points +
                             schedule.access_points_secondary)
    access_points = request_cache.GetEntitiesFromKeys(access_point_key_list)
    for access_point in access_points:
      if access_point and access_point.calendar_email:
        email_set.add(access_point.calendar_email)

  # Add users who are registered and confirmed ofline.
  reg_query = models.UserRegistration.ActiveQuery(activity=activity)
  utils.AddFilter(reg_query, 'status =', utils.RegistrationStatus.ENROLLED)
  utils.AddFilter(reg_query, 'confirmed =', utils.RegistrationConfirm.PROCESSED)
  reg_query = utils.QueryIterator(reg_query, models.UserRegistration,
                                  prefetch_count=1000, next_count=1000)
  for reg in reg_query:
    email_set.add(reg.user.email())

  logging.debug('Exiting _GetScheduleEmailsForCalendar')
  return list(email_set)


def _GetScheduleWhereForCalendar(schedule):
  """Make the calendar.Where element list required for calendar.Event.

  Args:
    schedule: models.ActivitySchedule for which we need to find the locations.

  Returns:
    Array of calendar.Where elements.
  """
  logging.debug('Entering _GetScheduleWhereForCalendar')
  if schedule is None: return []

  access_point_key_list = (schedule.access_points +
                           schedule.access_points_secondary)

  access_points = request_cache.GetEntitiesFromKeys(access_point_key_list)
  access_points_names = [str(ap) for ap in access_points]

  logging.debug('Exiting _GetScheduleWhereForCalendar')
  return [calendar.Where(value_string=', '.join(access_points_names))]


def _CreateOrUpdateCalendarEventForSchedule(schedule, current_event=None):
  """Construct new or update current calendar event of a schedule in memory.

  Args:
    schedule: A models.ActivitySchedule to construct the calendar event for.
    current_event: An existing gdata.calendar.CalendarEventEntry event for the
        schedule given above.

  Returns:
    A gdata.calendar.CalendarEventEntry. The entry is constructed in memory to
    be used by gdata functions.
  """
  logging.debug('Entering _CreateOrUpdateCalendarEventForSchedule')
  activity = utils.GetCachedOr404(schedule.parent_key())
  program = utils.GetCachedOr404(activity.parent_key())

  event = current_event or calendar.CalendarEventEntry()

  event.title = atom.Title(text=program.name)
  event.content = atom.Content(
      text=_MakeCalendarBody(schedule, activity, program)
  )
  event.send_event_notifications = calendar.SendEventNotifications(
      value='false'
  )

  # Add new rooms and new instructors.
  emails_to_add = _GetScheduleEmailsForCalendar(schedule)
  new_who = []
  for email_to_add in emails_to_add:
    new_who.append(calendar.Who(email=email_to_add,
                                attendee_status=_ACCEPTED_STATUS,
                                attendee_type=_REQUIRED_TYPE))
  event.who = new_who

  event.where = _GetScheduleWhereForCalendar(schedule)

  start_time = schedule.start_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')
  end_time = schedule.end_time.strftime('%Y-%m-%dT%H:%M:%S.000Z')
  event.when = []
  event.when.append(calendar.When(start_time=start_time, end_time=end_time))

  logging.debug('Exiting _CreateOrUpdateCalendarEventForSchedule')
  return event


def ResourceEmail(calendar_name):
  """Construct the email address to use in calendar for resource names.

  Args:
    calendar_name: Str name of the resource as recognized by calendar. It can be
        a complete calendar recognized email or resource name.

  Example:
   Given a calendar room name of 'room_armory' converts it into a calendar email
       of google.com_XXXXXXXXXXX@resource.calendar.google.com.

  Returns:
    A calendar recognized resource email which can be used in event invites to
    reserve them.
  """
  domain_name = os.environ['AUTH_DOMAIN']
  room_pattern = r'%s_\w+@resource.calendar.google.com$' % domain_name

  if re.match(room_pattern, calendar_name): return calendar_name

  encoded_calendar_name = ''.join(['%02x' % ord(c) for c in calendar_name])
  resource_email = '%s_%s@resource.calendar.google.com' % (
      domain_name, encoded_calendar_name
  )
  return resource_email


def SyncScheduleCalendarEvent(schedule):
  """Syncs a schedule with its calendar entry."""
  logging.debug('Entering SyncScheduleCalendarEvent')

  activity_lock = models.Activity.GetLock(schedule.parent_key())
  activity_lock.RunSynchronous(_SyncScheduleCalendarEventUnsafe, schedule)

  logging.debug('Exiting SyncScheduleCalendarEvent')


def _SyncScheduleCalendarEventUnsafe(schedule):
  """Syncs a schedule with its calendar entry."""
  schedule = db.get(schedule.key())  # Force reload inside the lock.

  # Delete calendar if schedule has been deleted.
  if schedule.deleted:
    if not schedule.calendar_edit_href:  # No calendar to delete.
      return
    # Delete the calendar entry or ignore if already deleted.
    # TODO(user): Check that if the calendar is already deleted this
    # function really just ignore the delete request.
    failed_href = _DeleteCalendarEvents([schedule.calendar_edit_href])
    assert not failed_href
    # Update schedule href.
    schedule.calendar_edit_href = None
    schedule.put()
    return

  if not schedule.calendar_edit_href:  # Need to create for first time.
    calendar_event = _CreateOrUpdateCalendarEventForSchedule(
        schedule, current_event=None)

    # Don't put guests until we store the created event href on schedule.
    guest_list = calendar_event.who
    calendar_event.who = []

    # Create the event.
    logging.info('Creating a new calendar')
    request_feed_query = calendar.CalendarEventFeed()
    request_feed_query.AddInsert(calendar_event)
    batch_result = _ExecuteBatchQuery(request_feed_query, check_failures=True,
                                      accept_status_codes=['201'])
    calendar_event = batch_result[0]

    # Update schedule.
    schedule.calendar_edit_href = calendar_event.GetEditLink().href
    schedule.put()

    # Adding guest list now that the schedule is paired to the cal event.
    calendar_event.who = guest_list
  else:
    # Query current calendar event.
    logging.info('Querying existing calendar:%s', schedule.calendar_edit_href)
    calendar_event = _GetCalendarEvents(
        [schedule.calendar_edit_href], check_failures=True)[0]

    calendar_event = _CreateOrUpdateCalendarEventForSchedule(
        schedule, current_event=calendar_event)

  # Update event.
  request_feed_query = calendar.CalendarEventFeed()
  request_feed_query.AddUpdate(calendar_event)
  logging.info('Updating calendar:%s', schedule.calendar_edit_href)
  _ExecuteBatchQuery(request_feed_query, check_failures=True)


def SyncRegistrationForScheduleUnsafe(user, schedule_key):
  """Updates a schedule's calendar with the current user register status."""
  # Not run mutually exclusive with _SyncScheduleCalendarEventUnsafe. Activity
  # details and or calendars that this function is trying to modify can change
  # during the execution of this function.
  # Activity changes can be ignored since they will be proceesed later on in
  # _SyncScheduleCalendarEventUnsafe, and calendar updates collision will just
  # fail the calendar update since we always do a (read+update).
  schedule = utils.GetCachedOr404(schedule_key, active_only=False)

  if schedule.deleted or not schedule.calendar_edit_href:
    return  # Dont have to sync.

  # Check if there is an active and confirmed registration for the user.
  reg_query = models.UserRegistration.ActiveQuery(
      activity=schedule.parent_key(), user=user, keys_only=True)
  utils.AddFilter(reg_query, 'status =', utils.RegistrationStatus.ENROLLED)
  utils.AddFilter(reg_query, 'confirmed =', utils.RegistrationConfirm.PROCESSED)

  add_to_guest_list = reg_query.get() is not None

  # Get current event.
  calendar_event = _GetCalendarEvents(
      [schedule.calendar_edit_href], check_failures=True)[0]

  def AddAttendeeToEvent(event):
    """Function that updates given event by adding the user to who list."""
    event.who = [who for who in event.who if who.email != user.email()]
    new_who = calendar.Who(
        email=user.email(),
        attendee_status=_ACCEPTED_STATUS, attendee_type=_REQUIRED_TYPE,
    )
    event.who.append(new_who)

  def RemoveAttendeeFromEvent(event):
    """Function that updates given event by removing the user from who list."""
    event.who = [who for who in event.who if who.email != user.email()]

  if add_to_guest_list:
    update_func = AddAttendeeToEvent
  else:
    update_func = RemoveAttendeeFromEvent
  _UpdateCalendarEvents([calendar_event], update_func, check_failures=True)


def _DeleteCalendarEvents(calendar_event_hrefs):
  """Delete the calendar events referenced by their edit urls.

  Args:
    calendar_event_hrefs: Str list of edit urls of the calendar urls that need
        to be deleted.

  Returns:
    Str list of the calendar edit urls that weren't deleted successfully.
  """
  logging.debug('Entering _DeleteCalendarEvents')

  def ProcessCalendarEntries(event_list):
    """Returns a tuple of (valid events, failed hrefs) from batch query.

    Filters out the 404 not found events, as those are already deleted.

    Args:
      event_list: List of calendar events

    Returns:
      A tuple (valid events, failed hrefs)
    """
    valid_events = []
    failed_hrefs = []
    for entry in event_list:
      if entry.batch_status.code != '200':
        if entry.batch_status.code != '404':  # 404 is for event already deleted
          logging.error('Got calendar query error %s for entry %s',
                        str(entry.batch_status), str(entry))
          failed_hrefs.append(entry.GetEditLink().href)
      else:
        valid_events.append(entry)
    return valid_events, failed_hrefs

  # Query the calendar events first to get the latest versions.
  # If this is not done then deletion fails with 'version conflict' error, to
  # avoid this we query the latest event from calendar first.
  logging.info('Deleting calendar events from hrefs %s', calendar_event_hrefs)
  calendar_events = _GetCalendarEvents(calendar_event_hrefs,
                                       check_failures=False)
  (events_to_update, failed_query) = ProcessCalendarEntries(calendar_events)

  # The attendees from the events are then removed to avoid any notifications.
  # Also if deletion fails this would at  least remove event from users calendar
  updated_events = _RemoveUsersFromEvents(events_to_update,
                                          check_failures=False)
  (events_to_delete, failed_update) = ProcessCalendarEntries(updated_events)

  # Try to delete the events now.
  request_feed_delete = calendar.CalendarEventFeed()
  for event in events_to_delete:
    request_feed_delete.AddDelete(url_string=event.GetEditLink().href)

  deleted_events = _ExecuteBatchQuery(request_feed_delete, check_failures=False)
  (unused_hrefs, failed_delete) = ProcessCalendarEntries(deleted_events)

  logging.debug('Exiting _DeleteCalendarEvents')
  return failed_query + failed_update + failed_delete
