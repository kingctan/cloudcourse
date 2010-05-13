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


"""Middlewares."""



import logging

from django import http

from core import errors
from core import memcache_wrapper
from core import request_cache

# Suppress pylint unused arg and invalid method name (overriden methods)
# pylint: disable-msg=W0613, C6409


class Cache(object):
  """Middleware to handle caching."""

  def process_request(self, request):
    request_cache.ClearCache()
    return None

  def __init__(self):
    memcache_wrapper.SetupClient()


class ExceptionHandler(object):
  """Middleware to handle exceptions."""

  def process_request(self, request):
    errors.ClearExceptions()
    return None

  def process_exception(self, request, exception):
    if not isinstance(exception, http.Http404):
      logging.error('Uncaught exception: [%s] %s', type(exception), exception)
    return None
