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


"""Ajax handlers.

The ajax module does not get tested and as such only contains handlers
with minimum logic in it.

Any complex logic is to be delegated to ajax_impl module.
"""



# Suppress pylint invalid import order
# pylint: disable-msg=C6203

from django import http
from django import template
from django.utils import simplejson

from core import ajax_impl
from core import permissions
from core import views_impl

_MIME_TYPE_AJAX = 'application/javascript'


@permissions.ActivityOwner
def UserAttendance(request, activity, program, attended):
  """View handler to record user attendance.

  Args:
    request: The view Http request object.
    activity: models.Activity to register attendance for.
    program: models.Program associated with the activity.
    attended: String 'True' or 'False' indicating attendance.

  Returns:
    Http response.
  """
  # The decorator provides the argument 'program'. Do not rename.
  # Suppress pylint invalid import order
  # pylint: disable-msg=W0613

  result = ajax_impl.UserAttendance(activity, request.POST['emails'], attended)
  content = simplejson.dumps(result)
  return http.HttpResponse(content, _MIME_TYPE_AJAX)


def ValidateEmails(request):
  """Returns a JSON response validating the given emails.

  Args:
    request: The Http request object.

  Returns:
    Http response.
  """
  data = ajax_impl.ValidateEmails(request.POST['emails'])
  content = simplejson.dumps(data)
  return http.HttpResponse(content, _MIME_TYPE_AJAX)


def RegisterPopupForm(request, program_key, activity_key, users=None,
                      notify='1', force_status='0'):
  """Function called to render the register popup dialog during registration.

  Wraps the popup html that needs to be displayed in a json object and returns
  the json content back to the client.

  Args:
    request: Request object provided for django view functions.
    program_key: The program key of the activity.
    activity_key: The key of the activity for which the registration popup needs
      to render the schedules and access points information for user choices.
    users: String of comma separated emails to register. Registers the user who
      makes the request if None.
    notify: Will not send email notifications when notify is '0'.
    force_status: Will force register users when it is '1'

  Returns:
    Returns a json object serialized as a string. The json object has a 'body'
    attribute which is the html the popup box needs to render to display the
    registration choices form.
  """
  data = ajax_impl.RegisterPopupForm(request, program_key, activity_key, users,
                                     notify, force_status)
  template_name = 'register_popup_form_multi.html'
  if 'common_access_points' in data:
    template_name = 'register_popup_form_single.html'
  context = template.Context(data)
  body = template.loader.render_to_string(template_name,
                                          context_instance=context)

  content = simplejson.dumps({'body': body})
  return http.HttpResponse(content, _MIME_TYPE_AJAX)


def RegisterPopupFormMultiple(request, program_key, activity_key):
  """Function called to render the register popup dialog during registration.

  Wraps the popup html that needs to be displayed in a json object and returns
  the json content back to the client. Used when registering multiple users.

  Args:
    request: Request object provided for django view functions.
    program_key: The program key of the activity.
    activity_key: The key of the activity for which the registration popup needs
      to render the schedules and access points information for user choices.

  Returns:
    Returns a json object serialized as a string. The json object has a 'body'
    attribute which is the html the popup box needs to render to display the
    registration choices form.
  """
  return RegisterPopupForm(request, program_key, activity_key,
                           users=request.POST['emails'],
                           notify=request.POST['notify'],
                           force_status=request.POST['force_status'])


@permissions.ActivityOwner
def DeleteActivityPopupForm(unused_request, activity, program=None):
  """Function called to render the delete activity popup dialog.

  Wraps the popup html that needs to be displayed in a json object and returns
  the json content back to the client.

  Args:
    activity: Activity to be deleted.
    program: Parent program of the activity.

  Returns:
    Returns a json object serialized as a string. The json object has a 'body'
    attribute which is the html the popup box needs to render.
  """
  # The decorator provides the argument 'program'. Do not rename.
  # Suppress pylint invalid import order
  # pylint: disable-msg=W0613

  data = ajax_impl.DeleteActivityPopupForm(activity)
  context = template.Context(data)
  body = template.loader.render_to_string('delete_activity_popup_form.html',
                                          context_instance=context)

  content = simplejson.dumps({'body': body})
  return http.HttpResponse(content, _MIME_TYPE_AJAX)


@permissions.ProgramOwner
def DeleteProgramPopupForm(unused_request, program):
  """Function called to render the delete program popup dialog.

  Wraps the popup html that needs to be displayed in a json object and returns
  the json content back to the client.

  Args:
    program: models.Program to be deleted.

  Returns:
    Returns a json object serialized as a string. The json object has a 'body'
    attribute which is the html the popup box needs to render.
  """
  data = ajax_impl.DeleteProgramPopupForm(program)
  context = template.Context(data)
  body = template.loader.render_to_string('delete_program_popup_form.html',
                                          context_instance=context)

  content = simplejson.dumps({'body': body})
  return http.HttpResponse(content, _MIME_TYPE_AJAX)


def UserRegister(request):
  """Registers users in an activity with post choices.

  This function supports the bulk enroll functionality of the roster.

  Args:
    request: The request that contains user registration information.

  Returns:
     A json object containing a list of emanil addresses of users successfully
     enrolled under the key 'enrolled'.
  """
  if request.method == 'POST':  # Only POST is supported for now.
    registered = views_impl.UserRegister(request.POST, request.user)
    emails = [guser.email for guser in registered]
    content = simplejson.dumps({'enrolled': emails})
    return http.HttpResponse(content, _MIME_TYPE_AJAX)

  return http.HttpResponse
