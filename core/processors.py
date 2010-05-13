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


"""Functions whose information is stored in datastore for later execution."""



# Supress pylint invalid import order
# pylint: disable-msg=C6203

from google.appengine.api.labs import taskqueue
from ragendja import dbutils


class TaskConfig(dbutils.FakeModel):
  """Class that stores the information necessary to enqueue a task.

  Useful to store params required to execute a task. Instances of this class can
  be stored on a db.Model class as a property and can be accessed from the
  datastore to enqueue new tasks.
  """

  fields = ('params',)

  def __init__(self, params):
    self.params = params

  def __repr__(self):
    return '<Params: %s>' % (self.params,)

  def DispatchTask(self, transactional=False):
    """Enqueues a task using the params to run asynchronously.

    Args:
      transactional: Boolean to indicate if the task should be enqueued
          only if the transactions in which this function is called succeeds.

    Returns:
      The task that was enqueued.
    """
    processed_params = dict([(str(key), value)
                             for (key, value) in self.params.iteritems()])
    processed_params['transactional'] = transactional
    return taskqueue.add(**processed_params)

  # Invalid method name.
  # This method is used by app engine patch admin form helper.
  # pylint: disable-msg=C6409
  @classmethod
  def all(cls):
    """Method needed by the django admin interface to list possible values."""
    return []
