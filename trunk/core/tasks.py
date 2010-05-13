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


"""Urls to tasks mappings."""
import logging

from django import http
from django.core import urlresolvers
from google.appengine.ext import db

from core import models
from core import permissions
from core import processors
from core import query_processor
from core import rule_engine
from core import utils


@permissions.StaffOrCronOrTask
def DeleteProgramOrActivity(unused_request, config_key):
  """Delete a registered users entity like Activity or Program."""
  logging.info('Entering DeleteProgramOrActivity config_key:%s', config_key)

  config_entity = db.get(db.Key(config_key))
  if config_entity is None:
    # Entity has already been deleted, nothing to do
    logging.info('Config entity is None, exiting.')
    return http.HttpResponse()

  (entity_key, request_user_email) = config_entity.config_value.split(',')
  logging.info('Trying to delete entity_key:%s, initiated by %s', entity_key,
               request_user_email)

  entity = utils.GetCachedOr404(entity_key, active_only=False)

  if entity.deleted:
    # Entity already deleted, nothing to do
    logging.info('Entity entity_key:%s already deleted exiting.', entity_key)
    return http.HttpResponse()

  if isinstance(entity, models.Activity):
    registrations = models.UserRegistration.ActiveQuery(activity=entity)
  else:
    assert isinstance(entity, models.Program)
    registrations = models.UserRegistration.ActiveQuery(program=entity)

  models.UserRegistration.AddRegisterOrder(registrations)

  registration_list = [register for register in registrations]
  if registration_list:
    logging.info('Found %d registrations for entity, delegating task',
                 len(registration_list))
    last_registration = registration_list[-1]
    task_url = urlresolvers.reverse(DeleteProgramOrActivity,
                                    kwargs={'config_key': config_key})
    # Create a task config to be executed after the offline process completes
    # unregistered all users in the entity.
    processor = processors.TaskConfig({'url': task_url, 'method': 'GET'})
    for register in registration_list:
      context = rule_engine.EvalContext.CreateFromUserRegistration(register)
      # Since the entity is being deleted we want to make sure we can force a
      # registration.
      context.force_status = True

      if register == last_registration:
        # After the last registration is processed by the offline we can go
        # ahead and delete the program or activity that is being deleted. Hence
        # we keep a trigger that does that in the last registration that will be
        # processed by the rule engine.
        rule_engine.UnregisterOnline(context, post_process_tasks=[processor])
      else:
        rule_engine.UnregisterOnline(context)
  else:
    # No more registrations, we can delete the entitites.
    logging.info('No registrations found for entity, deleting entity now.')
    request_user = utils.GetAppEngineUser(request_user_email)
    db.run_in_transaction(_DeleteEntityUnsafe, entity,
                          config_entity.key(), request_user)

  return http.HttpResponse()


def _DeleteEntityUnsafe(entity, config_entity_key, request_user):
  """Deletes the entity and the configuration object.

  Args:
    entity: models.Program or models.Activity which is being deleted.
    config_entity_key: models.Configuration entity db.Key that triggered the
        operation.
    request_user: users.User who initially requested the delete.
  """
  # Reload config entity, in case its not required to delete.
  config_entity = db.get(config_entity_key)
  if config_entity is None:
    logging.info('Config entity reload was None, exiting.')
    return

  entity.DeleteUnsafeAndWrite(request_user)

  # Remove the config entity to stop future processing.
  config_entity.delete()


@permissions.StaffOrCronOrTask
def ProcessOfflineTask(unused_request):
  """Runs offline tasks."""
  rule_engine.ProcessOfflineTask()
  return http.HttpResponse()


@permissions.StaffOrCronOrTask
def PerformQueryWorkTask(unused_request, work_name):
  """Runs long running query works."""
  query_processor.PerformQueryWork(work_name)
  return http.HttpResponse()
