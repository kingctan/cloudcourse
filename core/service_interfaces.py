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


"""Base classes that define services returned by service_factory."""




class UserInfo(object):
  """User information returned by the UserInfoService.

  Attributes:
    name: str user name.
    primary_email: str email to use for the user.
    title: str user work title.
    department: str name of the user's department.
    employee_type: One of utils.EmployeeType choices.
    photo_url: str http url for the user's photograph.
    location: str display information for the users desk/building location.
    country_city: str 'country-city' formatted user location. ex:US-SFO. Should
        be one of timezone_helper.GetLocationCodes().
  """

  def __init__(self, name, primary_email, title, department, employee_type,
               photo_url, location, country_city):
    self.name = name
    self.primary_email = primary_email
    self.title = title
    self.department = department
    self.employee_type = employee_type
    self.photo_url = photo_url
    self.location = location
    self.country_city = country_city


class UserInfoService(object):
  """Base class for service that provides information for users."""

  def GetManagerInfo(self, email):
    """Provides the UserInfo for the manager of the given user.

    Args:
      email: Str email of the user.

    Returns:
      UserInfo for the manager of a given user. None when the user is not valid
      or doesn't have a valid manager.

    Raises:
      errors.ServiceCriticalError: The request failed due to a critical error
          like not being able to access a datasource, or finds invalid schema
          in the datasource etc.
    """
    raise NotImplementedError

  def GetUserInfoMulti(self, email_list):
    """Provides the UserInfo for a given list of user emails.

    Args:
      email_list: Str list of user emails.

    Returns:
      A {str email, UserInfo} dict. The user emails for whom the service didn't
      find UserInfo aren't included in the dict.

    Raises:
      errors.ServiceCriticalError: The request failed due to a critical error
          like not being able to access a datasource, or finds invalid schema
          in the datasource etc.
    """
    raise NotImplementedError


class DatastoreSyncService(object):
  """Base class for service that syncs entities with external storage."""

  def SyncEntity(self, entity):
    """Write entity to external storage that needs to sync from datastore.

    Args:
      entity: db.model instance to be synced with an external system.

    Raises:
      errors.ServiceCriticalError: The request failed due to a critical error
          like not being able to access a datasource, or finds invalid schema
          in the datasource etc.
    """
    raise NotImplementedError

  def IsModelSynced(self, model_class):
    """Indicates if the Sync service wants models of a class to be synced.

    Args:
      model_class: db.Model subclass from models.py

    Returns:
      True if entities of model_class should be synced.
    """
    raise NotImplemented


class SearchResult(object):
  """Search results display info.

  Attributes:
    program_key: str db.Key representation of a models.Program entity.
    program_name: str name of a models.Program entity.
    program_description: str description of a models.Program entity.
  """

  def __init__(self, program_key, program_name, program_description):
    self.program_key = program_key
    self.program_name = program_name
    self.program_description = program_description


class SearchService(object):
  """Base class for service that provides search functionality."""

  def Search(self, search_text='', search_location='',
             search_start_time=None, search_end_time=None,
             max_results=20):
    """Searches for programs that match given search criteria.

    Args:
      search_text: Str search text, program results should have name and/or
          description attributes that matches this.
      search_location: Str location tag. Program results should have a
          models.Activity with this location.
      search_start_time: Datetime. Program results should have a models.Activity
          that starts after this time.
      search_end_time: Datetime. Program results should have a models.Activity
          that starts before this time.
      max_results: Maximum number of SearchResults to return.

    Returns:
      Array of SearchResult objects.

    Raises:
      errors.ServiceCriticalError: The request failed due to a critical error
          like not being able to access a datasource, or finds invalid schema
          in the datasource etc.
    """
    raise NotImplementedError


class RoomInfo(object):
  """Room information returned by the RoomInfoService.

  Attributes:
    room_id: str unique identifier that represents the current room.
    name: str display name for identifying the room.
    calendar_email: str google calendar room resource email id.
    location: str display information for the rooms building/city location.
        ex:New York, NewYork/US, BLD1/NewYork/US.
    country_city: str 'country-city' formatted room location. ex:US-SFO. Should
        be one of timezone_helper.GetLocationCodes().
  """

  def __init__(self, room_id, name, country_city, calendar_email='',
               location=''):
    self.room_id = room_id
    self.name = name
    self.country_city = country_city
    self.location = location or country_city
    self.calendar_email = calendar_email


class RoomInfoService(object):
  """Service to provide rooms information."""

  def GetRoomInfoMulti(self, start_offset, num_rooms):
    """Get rooms information.

    Provides rooms information for a requested number of room starting at an
    offset. Lets say there are around 1000 rooms, this function helps to access
    them in small batches num_rooms size at a time.

    This function is called through the admin interface to update rooms in the
    datastore. The rooms can be dynamic and change over time and this service
    lets the system pull information about new rooms.

    Args:
      start_offset: int, zero indexed start offset of the rooms info to return.
      num_rooms: int number of room information to return. Can return lesser
          than this number if we reach the end of all room.

    Returns:
      List of RoomInfo objects.

    Raises:
      errors.ServiceCriticalError: The request failed due to a critical error
          like not being able to access a datasource, or finds invalid schema
          in the datasource etc.
    """
    raise NotImplementedError
