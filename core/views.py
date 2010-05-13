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


"""View handlers.

The views module does not get tested and as such only contains view handlers
with minimum logic in it.

Any complex logic is to be delegated to views_impl module.
"""

# Suppress pylint invalid import order
# pylint: disable-msg=C6203


from django import http
from django import shortcuts
from django import template
from django.core import urlresolvers
from django.utils import translation

from core import models
from core import permissions
#TODO(user): this import is needed because rules.GetRule() can not import
#rules_impl otherwise
# Suppress pylint const name warnings.
# pylint: disable-msg=W0611
from core import rules_impl
from core import utils
from core import views_impl

_ = translation.ugettext


def Home(request):
  """The landing home page view function."""

  data = views_impl.Home(request.user)
  context = template.RequestContext(request, data)
  template_name = 'home.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


def SystemStatus(request):
  """Shows system status."""

  data = views_impl.SystemStatus()
  context = template.RequestContext(request, data)
  template_name = 'system_status.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


def ShowPrograms(request):
  """Show all the programs that are present in the system on one page."""
  # TODO(user): Required only for the alpha release only, remove later.

  program_query = models.Program.GetSearchableProgramsQuery().order('name')
  program_query = utils.QueryIterator(program_query, models.Program,
                                      prefetch_count=1000, next_count=1000)
  program_list = []
  for program in program_query:
    views_impl.EnrichDisplay(program)
    program_list.append(program)

  template_name = 'show_all_programs.html'
  context = template.RequestContext(request, {'program_list': program_list})
  return shortcuts.render_to_response(template_name, context_instance=context)


def ShowOwned(request):
  """Show the programs that the user has edit privileges for."""

  data = views_impl.ShowOwned(request.user)
  context = template.RequestContext(request, data)
  template_name = 'show_owned.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


def ShowLearning(request):
  """Show the activities that the user is enrolled in."""
  data = views_impl.ShowLearning(request.user)
  context = template.RequestContext(request, data)
  template_name = 'show_learning.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


def ShowTeaching(request):
  """Show the programs that the user is teaching."""
  data = views_impl.ShowTeaching(request.user)
  context = template.RequestContext(request, data)
  template_name = 'show_teaching.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


def ShowProgram(request, program_key):
  """Display program, the corresponding sessions and registration options."""

  data = views_impl.ShowProgram(program_key, request.user)
  context = template.RequestContext(request, data)
  template_name = 'program_detail.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


@permissions.CourseCreator
def CreateProgram(request):
  """View handler to create a new program."""
  return views_impl.CreateOrUpdateProgram(request)


@permissions.ProgramOwner
def UpdateProgram(request, program):
  """View handler to update an existing program in the datastore.

  Args:
    request: The view request object. It contains the forms POST data for
        configuring the program properties.
    program: Program associated with the key.

  Returns:
    Renders the resultant page.
  """
  return views_impl.CreateOrUpdateProgram(request, program)


@permissions.ActivityOwner
def RosterEnroll(request, activity, program):
  """View handler to enroll people from roster page."""
  data = views_impl.RosterEnroll(request, program, activity)
  context = template.RequestContext(request, data)
  return shortcuts.render_to_response('show_roster_enroll.html', context)


@permissions.ProgramOwner
def DeleteProgram(request, program):
  """Delete a program on user request.

  Args:
    request: The view request object.
    program: models.Program to be deleted.

  Returns:
    Http response.
  """

  views_impl.DeleteProgram(program.key(), request.user.appengine_user)
  return http.HttpResponseRedirect(urlresolvers.reverse(Home))


def UpdateSettings(request):
  """Handles the user settings page."""
  return views_impl.UpdateSettings(request)


def ShowRoster(request, activity_key, order_by='status'):
  """Displays the roster page for a particular activity.

  Args:
    request: The view functions request object.
    activity_key: The key of the activity to show the roster page for.
    order_by: String. Sort order to be applied for the models.UserRegistration.

  Returns:
    The roster page html.
  """
  data = views_impl.ShowRoster(request.user, activity_key, order_by)
  context = template.RequestContext(request, data)

  template_name = 'show_roster.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


def PrintRoster(request, activity_key, order_by='user'):
  """Displays the print roster page for a particular activity.

  Args:
    request: The view functions request object.
    activity_key: The key of the activity to show the roster page for.
    order_by: String. Sort order to be applied for the models.UserRegistration.

  Returns:
    The print roster page html.
  """
  data = views_impl.ShowRoster(request.user, activity_key, order_by)
  context = template.RequestContext(request, data)

  template_name = 'print_roster.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


def UserUnregister(request, program_key, activity_key):
  """Unregister the user initiating the request from the given activity."""

  views_impl.ChangeUserStatus(
      [request.user.appengine_user.email()], activity_key,
      utils.RegistrationStatus.UNREGISTERED)

  return http.HttpResponseRedirect(urlresolvers.reverse(
      ShowProgram, kwargs=dict(program_key=program_key)))


@permissions.ActivityOwner
def UnregisterUsers(unused_request, activity, program=None, users=None):
  """Unregister the users for a given activity.

  Args:
    activity: A models.Activity.
    program: A models.Program.
    users: A space separated list of user emails.

  Returns:
    A http Response.
  """
  # The decorator provides the argument 'program'. Do not rename.
  # Suppress pylint invalid import order
  # pylint: disable-msg=W0613

  users = users.strip().split()
  views_impl.ChangeUserStatus(users, activity,
                              utils.RegistrationStatus.UNREGISTERED,
                              force_status=True)
  return http.HttpResponseRedirect(urlresolvers.reverse(
      ShowRoster, kwargs=dict(activity_key=activity.key(),
                              order_by='status')
  ))


@permissions.ActivityOwner
def ChangeUserStatusToEnrolled(unused_request, activity,
                               program=None, users=None):
  """Changes the status of an already waitlisted user to enrolled.

  Args:
    activity: A models.Activity.
    program: A models.Program.
    users: A space separated list of user emails.

  Returns:
    A http Response.
  """
  # The decorator provides the argument 'program'. Do not rename.
  # Suppress pylint invalid import order
  # pylint: disable-msg=W0613

  users = users.strip().split()
  views_impl.ChangeUserStatus(users, activity,
                              utils.RegistrationStatus.ENROLLED,
                              force_status=True)
  return http.HttpResponseRedirect(urlresolvers.reverse(
      ShowRoster, kwargs=dict(activity_key=activity.key(),
                              order_by='status')
  ))


def UserRegister(request):
  """Registers the user in an activity with post choices.

  This function is called after the user completes and confirms her choices for
  registering to an activity. The post information should contain information on
  the activity, the schedules and the user choices of access points for each of
  them etc.

  Args:
    request: The request that contains user registration information.

  Returns:
     Redirects back to the show program page.
  """

  if request.method == 'POST':  # Only POST is supported for now.
    views_impl.UserRegister(request.POST, request.user)
    if request.POST['users']:
      # Registration for multiple users - admin action - redirect to roster
      return http.HttpResponseRedirect(urlresolvers.reverse(
          ShowRoster, kwargs=dict(activity_key=request.POST['activity_id'],
                                  order_by='status')))
    else:
      return http.HttpResponseRedirect(urlresolvers.reverse(
          ShowProgram, kwargs=dict(program_key=request.POST['program_id'])))

  return http.Http404


def ShowActivity(request, activity_key):
  """Display program, with a specific session and registration options."""

  data = views_impl.ShowActivity(activity_key, request.user)
  context = template.RequestContext(request, data)
  template_name = 'program_detail.html'
  return shortcuts.render_to_response(template_name, context_instance=context)


@permissions.ActivityCreation
def CreateActivity(request, program):
  """View handler to create a new activity.

  Args:
    request: A request.
    program: Parent models.Program to created the activity under.

  Returns:
    http response.
  """

  return views_impl.CreateOrUpdateActivity(request, program=program)


@permissions.ActivityOwner
def UpdateActivity(request, activity, program):
  """View handler to update an existing activity in the datastore.

  Args:
    request: The view request object.
    activity: The models.Activity that should be updated.
    program: models.Program under which the activity is present.

  Returns:
    Renders the resultant page.
  """

  return views_impl.CreateOrUpdateActivity(request, activity=activity,
                                           program=program)


@permissions.ActivityOwner
def DeleteActivity(request, activity, program):
  """Delete an activity.

  Args:
    request: The view request object.
    activity: models.Activity which should be deleted.
    program: models.Program under which the activity is present.

  Returns:
    http response.
  """

  views_impl.DeleteActivity(activity, request.user.appengine_user)
  return http.HttpResponseRedirect(urlresolvers.reverse(
      ShowProgram, kwargs=dict(program_key=program.key())))


@permissions.Staff
def UpdateCalendarSessionToken(request):
  """Updates session tokens for role account when needed or when forced.

  Args:
    request: The view request object.

  Returns:
    http response.
  """
  redirect_path = urlresolvers.reverse(StoreCalendarSessionToken)
  return views_impl.UpdateCalendarSessionToken(request, redirect_path)


@permissions.Staff
def StoreCalendarSessionToken(request):
  """Stores the authentication tokens that are given as a redirect.

  The redirect comes from the google authentication server that provides the
  token for accessing calendar feeds using gdata. The redirect url contains the
  authentication tokens as one of the parameters. This method extracts the token
  and stores it in the datastore for future use.

  Args:
    request: The view request object.

  Returns:
    http response.
  """

  views_impl.StoreCalendarSessionToken(request)
  admin_url = urlresolvers.reverse('admin:core_configuration_changelist')
  return http.HttpResponseRedirect(admin_url)


@permissions.Staff
def ResetDatastoreSync(unused_request):
  """Reset the external sync process to start over."""
  views_impl.ResetDatastoreSync()
  admin_url = urlresolvers.reverse('admin:core_configuration_changelist')
  return http.HttpResponseRedirect(admin_url)


@permissions.StaffOrCronOrTask
def BeginConferenceRoomsStorage(unused_request):
  """Marks the beginning of a new conference rooms collection task."""

  views_impl.BeginConferenceRoomsStorage()
  admin_url = urlresolvers.reverse('admin:core_accesspoint_changelist')
  return http.HttpResponseRedirect(admin_url)


def FetchAndStoreConferenceRooms(unused_request, query_offset, num_rooms):
  """Queries RoomInfoService for rooms and stores them as access points.

  Args:
    query_offset: The str offset after which the rooms should be queried from.
    num_rooms: The str number of rooms to retrieve.

  Returns:
    A http response.
  """

  views_impl.FetchAndStoreConferenceRooms(int(query_offset), int(num_rooms))
  admin_url = urlresolvers.reverse('admin:core_accesspoint_changelist')
  return http.HttpResponseRedirect(admin_url)


def ConstructAccessPointsInfo(unused_request):
  """Loads access points info and saves it in datastore config object."""
  views_impl.ConstructAccessPointsInfo()
  admin_url = urlresolvers.reverse('admin:core_accesspoint_changelist')
  return http.HttpResponseRedirect(admin_url)


@permissions.StaffOrCronOrTask
def RunDeferred(request):
  """Executes deferred tasks by invoking the deferred api handler."""
  return views_impl.RunDeferred(request)


def ShowManagerApprovals(request):
  """The page that shows pending approvals for a manager."""
  return views_impl.ShowManagerApprovals(request)


def Search(request):
  """Course search view handler."""
  search_context = views_impl.Search(request)
  template_name = 'search_results.html'
  context = template.RequestContext(request, search_context)
  return shortcuts.render_to_response(template_name, context_instance=context)

