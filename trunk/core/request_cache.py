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


"""Cache layer for request."""




from google.appengine.ext import db

_ENTITY_CACHE = {}
_OBJECT_CACHE = {}


def ClearCache():
  _ENTITY_CACHE.clear()
  _OBJECT_CACHE.clear()


def GetEntityFromKey(entity_key):
  """Retrieves an entity from key, using request cache if possible.

  Args:
    entity_key: db.Key or string representing the key.

  Returns:
    A db.model entity.
  """
  return GetEntitiesFromKeys([entity_key])[0]


def GetEntitiesFromKeys(entity_keys):
  """Retrieves entities from keys, using request cache if possible.

  Args:
    entity_keys: A list of db.Key or string representing keys.

  Returns:
    A list of db.Model with 1-1 mapping with entity_keys
  """
  missing_keys = []
  for key in entity_keys:
    if not _ENTITY_CACHE.get(str(key)):
      missing_keys.append(key)

  if missing_keys:
    entities = db.get(missing_keys)
    for entity in entities:
      if entity:
        _ENTITY_CACHE[str(entity.key())] = entity

  return [_ENTITY_CACHE.get(str(entity_key)) for entity_key in entity_keys]


def GetObjectFromCache(key):
  """Gets an object from cache.

  Args:
    key: string key of object to cache.

  Returns:
    A the object associated with the key, or None.
  """
  return _OBJECT_CACHE.get(key)


def CacheObject(key, value):
  """Updates cache with given key/value.

  Args:
    key: Key string.
    value: Value to associate with key.
  """
  _OBJECT_CACHE[key] = value
