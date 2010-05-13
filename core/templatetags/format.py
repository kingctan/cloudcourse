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


"""Template tags used to format data."""



import os
import re
import settings

from django import template
from django.utils import dateformat
from django.utils import simplejson
from django.utils import translation
from google.appengine.api import users

from core import access_points
from core import errors

# To be a valid tag library, the module must contain a module-level variable
# named register that is a template.Library instance, in which all the tags and
# filters are registered
register = template.Library()
_ = translation.ugettext
FLASH_RE = re.compile(r'<embed .*type="application/x-shockwave-flash".*>',
                      re.IGNORECASE)


@register.filter(name='format_time')
def FormatTime(datetime):
  """Formats a time for display like 10:00 am."""
  # We lower case AM / PM
  return dateformat.format(datetime, 'g:iA').lower()


@register.filter(name='format_date')
def FormatDate(datetime):
  """Formats a date for display like Nov 3, 2009."""
  value = dateformat.format(datetime, 'b j, Y')
  return value[0].upper() + value[1:]


@register.filter(name='timezone')
def Timezone(datetime):
  """Returns a short timezone for display e.g. EST."""
  # We lower case AM / PM
  return datetime.strftime('%Z')


@register.filter(name='weekday')
def Weekday(datetime):
  """Returns a weekday for display e.g. Mon."""
  return datetime.strftime('%a')


@register.filter(name='full_datetime')
def FullDateTime(datetime):
  """Returns a fully formatted date/time, Wed Nov 3, 2009 10:15 am (EST)."""
  return '%s %s %s (%s)' % (Weekday(datetime), FormatDate(datetime),
                            FormatTime(datetime), Timezone(datetime))


@register.filter(name='email_url')
def EmailUrl(emails):
  """Returns a href which launches email client to email given users."""
  res = ('https://mail.google.com/mail/b/%s/?AuthEventSource'
         '=Internal&view=cm&tf=0&to=%s&su=')
  return res % (users.get_current_user().email(), emails)


@register.filter(name='massage_html')
def MassageHtml(html):
  """Formats the given html so it plays well within portal."""
  # Make sure any flash video content will not appear on top
  if FLASH_RE.search(html):
    return html.replace('type="application/x-shockwave-flash"',
                        'type="application/x-shockwave-flash" wmode="opaque"')
  else:
    return html


@register.tag(name='app_version')
# overriding method
# pylint: disable-msg=W0613
def AppVersion(parser, token):
  """Gets application version."""
  return _FormatVersionNode()


class _FormatVersionNode(template.Node):

  # overriding method
  # pylint: disable-msg=W0613, C6409
  def render(self, context):
    return os.environ.get('CURRENT_VERSION_ID', '').split('.')[0]


@register.tag(name='help_url')
# overriding method
# pylint: disable-msg=W0613
def HelpUrl(parser, token):
  """Gets application help URL."""
  return _FormatHelpUrlNode()


class _FormatHelpUrlNode(template.Node):

  # overriding method
  # pylint: disable-msg=W0613, C6409
  def render(self, context):
    return settings.HELP_URL


@register.tag(name='app_logo')
# overriding method
# pylint: disable-msg=W0613
def AppLogo(parser, token):
  """Gets application logo."""
  return _FormatLogoNode()


class _FormatLogoNode(template.Node):

  # overriding method
  # pylint: disable-msg=W0613, C6409
  def render(self, context):
    return settings.LOGO_LOCATION


@register.tag(name='app_errors')
# overriding method
# pylint: disable-msg=W0613
def AppErrors(parser, token):
  """Gets errors which happened during request."""
  return _FormatAppErrors()


class _FormatAppErrors(template.Node):

  # overriding method
  # pylint: disable-msg=W0613, C6409
  def render(self, context):
    return '<br>'.join(_GetExceptions())


@register.tag(name='app_errors_display')
# overriding method
# pylint: disable-msg=W0613
def DisplayErrors(parser, token):
  """Returns class to display errors."""
  return _DisplayErrors()


class _DisplayErrors(template.Node):

  # overriding method
  # pylint: disable-msg=W0613, C6409
  def render(self, context):
    if not _GetExceptions():
      return 'display:none;'
    return ''


def _GetExceptions():
  """Returns a list of exceptions messages."""
  return [message for unused_ex, message in errors.GetExceptions()]


@register.tag(name='search_locations')
# overriding method
# pylint: disable-msg=W0613
def SearchLocations(parser, token):
  """Get the list of all location tags that can be used to filter search."""
  return _FormatSearchLocations()


class _FormatSearchLocations(template.Node):

  # overriding method
  # pylint: disable-msg=W0613, C6409
  def render(self, context):
    """Renders a json array of location tags."""
    return simplejson.dumps(access_points.GetRoomLocations())
