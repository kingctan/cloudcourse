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


"""Memcache wrapper.

This wrapper makes sure that different app versions interact with different
memcache data and avoid conflicts between the different versions.
"""



import os

from google.appengine.api import memcache

# CURRENT_VERSION_ID is of the form <major version>.<minor version>.
# For example '1.1234324'.
_VERSION_PREFIX = os.environ.get('CURRENT_VERSION_ID')


def _GetVersionedWrapper(method_name, namespace_position):
  """Provides a wrapper function that adds version information to namespace.

  Creates a wrapper method that can change the namespace arguments and call the
  corresponding method in the memcache.Client class. The namespace is prefixed
  with the current application version number.

  Args:
    method_name: String method name to be called in the memcache.Client class.
    namespace_position: Int position of the namespace argument in the original
        method of the memcache.Client class. For example memcache.get() has
        namespace argument in the second position.

  Returns:
    Returns a function that calls method_name in memcache.Client with namespace
    argument that is prefixed with the current application version.
  """

  def VersionedWrapper(self, *args, **kwargs):
    """Function that GetVersionWrapper returns as described above."""
    if len(args) > namespace_position:
      args = list(args)
      args[namespace_position] = args[namespace_position] or ''
      args[namespace_position] = _VERSION_PREFIX + args[namespace_position]
    else:
      kwargs = kwargs.copy()
      kwargs['namespace'] = kwargs.get('namespace', '') or ''
      kwargs['namespace'] = _VERSION_PREFIX + kwargs['namespace']

    base_method = getattr(super(_WrapperClient, self), method_name)
    return base_method(*args, **kwargs)

  return VersionedWrapper


class _WrapperClient(memcache.Client):
  """Memcache client wrapper."""
  add = _GetVersionedWrapper('add', 4)
  add_multi = _GetVersionedWrapper('add_multi', 4)
  delete = _GetVersionedWrapper('delete', 2)
  delete_multi = _GetVersionedWrapper('delete_multi', 3)
  get = _GetVersionedWrapper('get', 1)
  get_multi = _GetVersionedWrapper('get_multi', 2)
  replace = _GetVersionedWrapper('replace', 4)
  replace_multi = _GetVersionedWrapper('replace_multi', 4)
  set = _GetVersionedWrapper('set', 4)
  set_multi = _GetVersionedWrapper('set_multi', 4)

  decr = _GetVersionedWrapper('decr', 2)
  incr = _GetVersionedWrapper('incr', 2)

  offset_multi = _GetVersionedWrapper('offset_multi', 2)


def SetupClient():
  """Sets memcache wrapper. See module level doc."""
  memcache.setup_client(_WrapperClient())
