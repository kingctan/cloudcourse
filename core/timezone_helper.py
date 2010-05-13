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


"""Helper class to retrieve timezones based on location."""

import logging
import settings

from django.utils import simplejson

_LOC_CODES = []
# Contains a map of locations to time zones as the first argument
_LOC_TZ_MAP = {}


def GetTimezoneForLocation(country_city):
  """Retrieves timezone for a given location code.

  Args:
    country_city: Country-City code, e.g. 'us-mtv'. Not case sensitive.

  Returns:
    A str timezone or None when not able to determine timezone.
  """
  if not _LOC_TZ_MAP:
    _LoadCache()
  return _LOC_TZ_MAP.get(country_city.upper())


def _LoadCache():
  file_loc = settings.TIMEZONES_FILE_LOCATION
  logging.info('Loading timezones/locations from %s', file_loc)
  try:
    f = open(file_loc, 'r')
  except IOError:
    # When testing, the root is folder is different
    f = open(file_loc[file_loc.index('/')+1:], 'r')

  _LOC_TZ_MAP.update(simplejson.loads(f.read()))
  _LOC_CODES.extend(sorted(loc.upper() for loc in _LOC_TZ_MAP.keys()))
  logging.info('Loaded %d timezones/locations', len(_LOC_CODES))


def GetLocationCodes():
  """Returns a list of user locations from access point locatoins.

  Returns:
    List of sorted user locations. Example ['us-mtv', 'us-nyc',...]
  """
  if not _LOC_CODES:
    _LoadCache()
  return _LOC_CODES
