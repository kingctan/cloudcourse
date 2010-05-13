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


"""Error classes."""



_EXCEPTIONS = {}


class Error(Exception):
  """Base error type."""


class BadTypeError(Error):
  """Raised for unexpected types."""


class BadObjectState(Error):
  """Raised when the object state is invalid or is unexpected."""


class DuplicateAttributeError(Error):
  """Raised when attribute being added is already present."""


class BadValueError(Error):
  """Raised when the value of an object is unexpected or unknown."""


class BadDbState(Error):
  """Raised when a db state that is invalid and implausible is found."""


class FailedTransaction(Error):
  """Raised when a db transactions fail due to contension."""


class LockAcquireFailure(Error):
  """Raised when lock cannot be acquired."""


class BadStateTransition(Error):
  """Raised when any state variable transition is unexpected or invalid."""


class AbstractMethod(Error):
  """Raised for abstract methods."""


class AppengineError(Error):
  """Raised for errors triggered because of appengine issues."""


class ServiceCriticalError(Error):
  """Raised when service_interfaces services cannot service requests."""


def RecordException(exception_id, exception, message):
  """Records exception happening during request.

  Args:
    exception_id: String unique id for the exception
    exception: Exception
    message: Human teadable string.
  """
  _EXCEPTIONS[exception_id] = (exception, message)


def GetExceptions():
  """Returns exceptions which occured during the lifetime of the request.

  Returns:
    A list of tuples (exception, message) where message is a human readable
    string associated with the exception.
  """
  return _EXCEPTIONS.values()


def GetException(exception_id):
  """Retrieves an exception for the current request based on id.

  Args:
    exception_id: unique id associated with the exception.

  Returns:
    Exception associated with id or None if not available.
  """
  exception = _EXCEPTIONS.get(exception_id)
  if exception:
    return exception[0]
  return None


def ClearExceptions():
  """Clears the exceptions for the current request."""
  _EXCEPTIONS.clear()
