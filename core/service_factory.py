#!/usr/bin/python2.4
# Copyright 2010 Google Inc. All Rights Reserved.
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


"""Helper module to load services configured by the app settings."""



import sys

import settings
from core import service_interfaces

# Service name convenience constants.
_DATASTORE_SYNC_SERVICE = 'datastore_sync_service'
_ROOM_INFO_SERVICE = 'room_info_service'
_SEARCH_SERVICE = 'search_service'
_USER_INFO_SERVICE = 'user_info_service'
_NAME_INTERFACE_MAP = {
    _DATASTORE_SYNC_SERVICE: service_interfaces.DatastoreSyncService,
    _ROOM_INFO_SERVICE: service_interfaces.RoomInfoService,
    _SEARCH_SERVICE: service_interfaces.SearchService,
    _USER_INFO_SERVICE: service_interfaces.UserInfoService,
}

assert (set(settings.SERVICE_PROVIDER_MODULES.keys()) ==
        set(_NAME_INTERFACE_MAP.keys()))


def GetDatastoreSyncService():
  """Provides DatastoreSyncService."""
  return _GetService(_DATASTORE_SYNC_SERVICE)


def GetRoomInfoService():
  """Provides RoomInfoService."""
  return _GetService(_ROOM_INFO_SERVICE)


def GetSearchService():
  """Provides a SearchService instance."""
  return _GetService(_SEARCH_SERVICE)


def GetUserInfoService():
  """Provides UserInfoService."""
  return _GetService(_USER_INFO_SERVICE)


def _GetService(service_name):
  """Returns a service class given a service name."""
  module_name, service_class = settings.SERVICE_PROVIDER_MODULES[service_name]
  unused_module = __import__(module_name)
  module = sys.modules[module_name]

  service = getattr(module, service_class)()  # Instance of service class.

  # Check that the service implements the right interface.
  service_interface = _NAME_INTERFACE_MAP.get(service_name)
  assert service_interface and isinstance(service, service_interface)

  return service
