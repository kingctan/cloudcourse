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


"""Module to handle permissions."""



from django import http
from django import shortcuts
from django import template

from core import request_cache


# Supress pylint around redefines of __name__ for functions
# pylint: disable-msg=W0612,W0621


def AccessDenied(request):
  """Returns a 403 response."""
  context = template.RequestContext(request)
  resp = shortcuts.render_to_response('403.html', context_instance=context)
  resp.status_code = 403
  return resp


def CourseCreator(func):
  """Decorator for a view function. Checks course creator permission.

  Checks that user is course creator, returns 403 access denied if not.
  Methods which use this decorator must have request as first argument.

  Args:
    func: Function to decorate.

  Returns:
    Decorated function.
  """

  def Wrap(request, *args, **kwargs):
    """Internal wrap."""
    if request.user.CanCreateProgram():
      return func(request, *args, **kwargs)
    return AccessDenied(request)
  Wrap.__name__ = func.__name__
  return Wrap


def Staff(func):
  """Decorator for a view function. Checks staff permission.

  Checks that user is staff. Returns 403 access denied if not.
  Methods which use this decorator must have request as first argument.

  Args:
    func: Function to decorate.

  Returns:
    Decorated function.
  """

  def Wrap(request, *args, **kwargs):
    """Internal wrap."""
    if request.user.is_staff:
      return func(request, *args, **kwargs)
    return AccessDenied(request)
  Wrap.__name__ = func.__name__
  return Wrap


def StaffOrCronOrTask(func):
  """Decorator for a view function. Checks task/cron/admin-user invocation.

  Checks that user is staff and if the User is not present checks if the handler
  was called by a cron job or a task. If these criteria are not met then access
  is denied.

  Args:
    func: Function to decorate.

  Returns:
    Decorated function.
  """

  def Wrap(request, *args, **kwargs):
    """Internal wrap."""
    if request.user.is_staff:
      return func(request, *args, **kwargs)
    else:
      check_headers = set(['HTTP_X_APPENGINE_TASKNAME',
                           'HTTP_X_APPENGINE_QUEUENAME',
                           'HTTP_X_APPENGINE_CRON'])
      if set(request.META.keys()).intersection(check_headers):
        return func(request, *args, **kwargs)

    return AccessDenied(request)
  Wrap.__name__ = func.__name__
  return Wrap


def ProgramOwner(func):
  """Decorator for a view function. Checks program ownership.

  Checks that user owns the program, returns 403 access denied if not.
  Views which use this decorator must have request and program_key as first
  arguments.
  This decorator will enrich kwargs of the decorated function with 'program'
  arg as fetched from datastore based on program_key.

  Args:
    func: Function to decorate.

  Returns:
    Decorated function.

  Raises:
    http.Http404 if program_key is invalid.
  """

  def Wrap(request, program_key, *args, **kwargs):
    """Internal wrap."""
    program = request_cache.GetEntityFromKey(program_key)
    if program:
      if request.user.CanEditProgram(program):
        kwargs['program'] = program
        return func(request, *args, **kwargs)
      else:
        return AccessDenied(request)
    else:
      raise http.Http404
  Wrap.__name__ = func.__name__
  return Wrap


def ActivityCreation(func):
  """Decorator for view function. Checks user can create activity under program.

  Checks that user can create a new activity under a program. Returns 403 access
  denied if not. Views that use this decorator must have request and program_key
  as first arguments.
  This decorator will enrich kwargs of the decorated function with 'program'
  arg as fetched from datastore based on program_key.

  Args:
    func: Function to decorate.

  Returns:
    Decorated function.

  Raises:
    http.Http404 if program_key is invalid.
  """

  def Wrap(request, program_key, *args, **kwargs):
    """Internal wrap."""
    program = request_cache.GetEntityFromKey(program_key)
    if program:
      if request.user.CanCreateActivity(program):
        kwargs['program'] = program
        return func(request, *args, **kwargs)
      else:
        return AccessDenied(request)
    else:
      raise http.Http404
  Wrap.__name__ = func.__name__
  return Wrap


def ActivityOwner(func):
  """Decorator for a view function. Checks activity ownership.

  Checks that user owns the activity, returns 403 access denied if not.
  Views which use this decorator must have request and activity_key as first
  arguments.

  This decorator will enrich kwargs of the decorated function with 'activity'
  and 'program' args as fetched from datastore based on activity_key.

  Args:
    func: Function to decorate.

  Returns:
    Decorated function.

  Raises:
    http.Http404 if activity_key is invalid.
  """

  def Wrap(request, activity_key, *args, **kwargs):
    """Internal wrap."""
    activity = request_cache.GetEntityFromKey(activity_key)
    if activity:
      program = request_cache.GetEntityFromKey(activity.parent_key())
      assert program
      if request.user.CanEditActivity(activity):
        kwargs['program'] = program
        kwargs['activity'] = activity
        return func(request, *args, **kwargs)
      else:
        return AccessDenied(request)
    else:
      raise http.Http404
  Wrap.__name__ = func.__name__
  return Wrap

