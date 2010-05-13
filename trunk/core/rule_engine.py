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


"""Responsible for state transitions in registration, certifications etc.

The rule engine is responsible for online and off-line processing of state
transitions for registration and certification management, along with logic
to evaluate and interpret results from multiple individual rules. It is also
responsible to handle concurrency and contention between rule evaluation
operations.
"""



import datetime
import logging

from django.utils import translation
from google.appengine.ext import db
from google.appengine.ext import deferred
import uuid

from core import calendar
from core import errors
from core import models
from core import notifications
from core import query_processor
from core import request_cache
from core import rules
from core import utils

_ = translation.ugettext
_REPROCESS_RULE_TAGS_KEY = db.Key.from_path(models.Configuration.kind(),
                                            'offline_reprocess_tags')
_WAITLIST_REPROCESS_KEY = db.Key.from_path(models.Configuration.kind(),
                                           'offline_registrations_to_ready')


class EvalContext(object):
  """A context associated a user registration, used for rule evaluation.

  User registration context like program, activity, access points for each of
  the schedules chosen by the user can be captured in this class.

  Attributes:
    user: A models.GlearnUser who's registration status needs to be changed.
    creator: A models.GlearnUser who is initiating this request.
    program: A models.Program user is trying to register to.
    activity: A models.Activity, which the user is planning to (not) attend.
    schedule_list: A list of models.ActivitySchedule for ordering choices in
        access_point, schedule_list and access_point_list correspond 1-1.
    access_point_list: A models.AccessPoint choice for schedule_list items.
    queue_time: Time when the user initiated the registration request.
    force_status: A boolean that indicates if the rule engine should be forced
        to accept the target status which the user is trying to move to.
  """

  def __init__(self, queue_time=None, program=None, activity=None, user=None,
               creator=None, schedule_list=None, access_point_list=None,
               force_status=False):

    # Supress pylint super warning.
    # pylint: disable-msg=E1002
    super(EvalContext, self).__init__()

    self.queue_time = queue_time or datetime.datetime.utcnow()
    self.program = program
    self.activity = activity
    self.user = user
    self.creator = creator
    self.schedule_list = schedule_list or []
    self.access_point_list = access_point_list or []
    self.force_status = force_status

  @staticmethod
  def CreateFromUserRegistration(user_reg):
    """Seed EvalContext with UserRegistration data.

    Args:
      user_reg: models.UserRegistration to seed EvalContext with.

    Returns:
      EvalContext
    """
    program_key = user_reg.GetKey('program')
    activity_key = user_reg.GetKey('activity')

    ev = EvalContext(
        queue_time=user_reg.queue_time,
        program=request_cache.GetEntityFromKey(program_key),
        activity=request_cache.GetEntityFromKey(activity_key),
        user=models.GlearnUser.GetGlearnUserFromCache(user_reg.user.email()),
        creator=models.GlearnUser.GetGlearnUserFromCache(
            user_reg.creator.email()),
        schedule_list=request_cache.GetEntitiesFromKeys(user_reg.schedule_list),
        access_point_list=request_cache.GetEntitiesFromKeys(
            user_reg.access_point_list),
        force_status=user_reg.force_status)
    return ev


def _RuleGenerator(eval_context):
  """Generator for rules that need evaluation for given EvalContext.

  Generates the rules that need to be evaluated at different levels of hiearchy.

  Args:
      eval_context: The EvalContext for which the rules need to be retrieved.

  Yields:
      RuleConfigs that correspond to the EvalContext attributes like program
      activity, access_points etc.
  """
  for rule in eval_context.program.rules:
    yield rule
  for rule in eval_context.activity.rules:
    yield rule
  processed_key_map = {}
  for access_point in eval_context.access_point_list:
    if access_point.key() not in processed_key_map:
      processed_key_map[access_point.key()] = True
      for rule in access_point.rules:
        yield rule


def _RulesEvaluate(eval_context, initial_status, target_status, is_online,
                   namespace=''):
  """Processes the rules for the EvalContext and the requested status change.

  This function evaluates the relevant rules for the eval_context and returns
  the collective rule response to the user's request of going to target_status
  of registration from initial_state.

  Args:
    eval_context: The EvalContext requesting the status change.
    initial_status: The current RegistrationStatus of UserRegistration
    target_status: The target RegistrationStatus user is trying to reach.
    is_online: If the evaluation is under online mode.
    namespace: The namespace under which the rules state is stored in memcache.

  Returns:
    A dictionary with following keys:
      final_status: UserRegistration.status, collective result of all rules.
      all_rule_configs: List of rules.RuleConfig which were evaluated.
      all_rule_results: List of (rules.RuleRegister, utils.RegistrationStatus),
        mapping 1-1 with the list of all_rule_configs.
      all_rule_resources_remaining: List of remaining resources mapping 1-1 with
        the list all_rule_configs, outcome from
        rules.RuleRegisterResource.Evaluate().
      all_rule_tags: Set of rule tags provided by rules that are evaluated.
      affecting_rule_tags: Set rule tags provided by the rules that affected the
        final_status.
      affecting_rule_configs: Set of RuleConfigs affecting the final status.

  Raises:
    BadStateTransition: The evaluation request or results are leading to
        illegal UserRegistration state transitions.
  """
  if not utils.RegistrationStatus.IsValidTransition(initial_status,
                                                    target_status):
    raise errors.BadStateTransition(
        'Invalid Registration status change requested, %s to %s' %
        (initial_status, target_status)
    )

  order = utils.RegistrationStatus.VALID_TRANSITIONS[initial_status]
  # status_priority defines the priority for the final state that is picked.
  # All rules are executed and the highest priority state is the final state.
  status_priority = dict(zip(order, range(len(order))))

  max_p = max(status_priority.values())
  # Status stop is the highest priority state, so if a rule responds with this
  # state then we already know that final_status is that and can stop.
  status_stop = [k for (k, v) in status_priority.items() if v == max_p]

  rule_results = []
  iter_rules = _RuleGenerator(eval_context)

  # Each of the relevant rules for the eval_context
  use_break = False
  for rule_config in iter_rules:
    if use_break: break

    rule_list = rule_config.CreateRules(eval_context, not is_online,
                                        namespace=namespace)
    for rule in rule_list:
      if rule.IsRegister():
        # Create and evaluate the rule.
        rule_result = rule.Evaluate(initial_status, target_status)
        rule_status = rule_result['status']
        rule_tags = rule_result.get('rule_tags', [])
        resource_remaining = rule_result.get('resource_remaining', 0)

        if not utils.RegistrationStatus.IsValidTransition(initial_status,
                                                          rule_status):
          raise errors.BadStateTransition(
              'Invalid Registration status change, %s to %s by rule %s' %
              (initial_status, rule_status, rule_config.GetDescription())
          )

        rule_results.append((rule_config, rule, rule_status, rule_tags,
                             resource_remaining))
        # If we need to force a status then one rule providing a stop status
        # wouldn't affect us since we will need to let all the rules run and
        # then later tell them that their decision was overridden.
        if rule_status in status_stop and not eval_context.force_status:
          use_break = True
          break

  # Get a combined rule result.

  if rule_results:
    unused_max_p, final_status = max(
        [(status_priority[rtup[2]], rtup[2]) for rtup in rule_results]
    )
  else:
    final_status = target_status

  # Required for notify pass of the rules
  all_rule_results = []
  # Required rerun online context when off-line needs to update online state.
  all_rule_configs = []
  # Lists the tags that rules want to identify this registration with.
  all_rule_tags = set()
  # Required for efficient re-processing/access of rule tags on registrations.
  affecting_rule_tags = set()
  all_rule_resources_remaining = []
  # Required to construct reason for final_state when it is not target_state
  affecting_rule_configs = set()

  for (rule_config, rule, status, rule_tags, res_remaining) in rule_results:
    all_rule_results.append((rule, status))
    all_rule_configs.append(rule_config)
    all_rule_resources_remaining.append(res_remaining)
    all_rule_tags.update(rule_tags)
    if status == final_status:
      affecting_rule_configs.add(rule_config)
      affecting_rule_tags.update(rule_tags)

  # Add program and activity tags.
  rule_engine_tags = [_GetRuleTagForEntity(eval_context.program.key()),
                      _GetRuleTagForEntity(eval_context.activity.key())]
  all_rule_tags.update(rule_engine_tags)
  affecting_rule_tags.update(rule_engine_tags)

  if eval_context.force_status:
    # If we need to force the status then effective its like every rule had
    # agreed to the transition. Hence affecting rule configs are all configs and
    # affecting rule tags are the tags from every rule.
    affecting_rule_configs = set(all_rule_configs)
    affecting_rule_tags = all_rule_tags
    final_status = target_status

  return {'final_status': final_status,
          'all_rule_results': all_rule_results,
          'all_rule_configs': all_rule_configs,
          'all_rule_resources_remaining': all_rule_resources_remaining,
          'all_rule_tags': all_rule_tags,
          'affecting_rule_tags': affecting_rule_tags,
          'affecting_rule_configs': affecting_rule_configs}


def _RulesNotify(final_status, rule_results):
  """Notify the rules of the final decision _RulesEvaluate.

  Args:
    final_status: The final UserRegistration status selected.
    rule_results: Rule and rule status result tuples during Rule_Evaluate run.
  """
  for (rule, result) in rule_results:
    rule.ProcessOutcome(result, final_status)


def RegistrationLock(appengine_user, activity_key):
  """Constructs a lock for the given user/activity.

  Args:
    appengine_user: The users.User object of the user trying to enroll.
    activity_key: The entity key of the activity that the user wants to enroll.

  Returns:
    The utils.Lock for user, activty.
  """
  lock_name = '%s:%s' % (appengine_user.email(), activity_key)
  return utils.Lock(lock_name)


def RegisterOnline(eval_context, notify=True):
  """Wrapper for _RegisterOnlineUnsafe to run in a locked/mutual exclusive way.

  Args:
    eval_context: EvalContext containing the user registration information.
    notify: Boolean flag to send notifications.

  Returns:
    (final_status, message_list)
    final_status: The registration status allowed by the rules for the request.
    message_list: String list of messages explaining reasons for final_status.
  """
  lock = RegistrationLock(eval_context.user.appengine_user,
                          eval_context.activity.key())
  return lock.RunSynchronous(_RegisterOnlineUnsafe, eval_context, notify)


def _GetActiveUserRegistration(eval_context):
  q = models.UserRegistration.ActiveQuery(activity=eval_context.activity.key(),
                                          user=eval_context.user.appengine_user)
  active_list = q.fetch(2)  # If more than 1 is fetched then its an error.
  assert len(active_list) <= 1, 'User has multiple active registrations'

  if active_list:
    return active_list[0]
  return None


def PredictRegistrationOutcome(eval_context):
  """Predicts registration outcome by simulating online registration.

  Args:
    eval_context: A rules.EvalContext

  Returns:
   return value of _RulesEvaluate()
  """
  # Process the rules and get the rules decision.
  rules.SetPredictionMode(True)
  result = _RulesEvaluate(eval_context, None, utils.RegistrationStatus.ENROLLED,
                          is_online=True)

  # Undo rule changes by simulating a None/denial decision to the rules.
  _RulesNotify(None, result['all_rule_results'])
  rules.SetPredictionMode(False)
  return result


def _RegisterOnlineUnsafe(eval_context, notify=True):
  """Attempts to register the user online. Is called protected by a lock.

  Runs in a protected mutually exclusive block for a user, activity and attempts
  to register user for the requested activity and access points selections. The
  function runs the relevant rules and makes a collective choice. The resource
  constraints required for registration are allocated when registered.

  Args:
    eval_context: EvalContext containing the user registration information.
    notify: Boolean flag to send notifications.

  Returns:
    (final_status, message_list)
    final_status: The registration status allowed by the rules for the request.
    message_list: String list of messages explaining reasons for final_status.

  Raises:
    FailedTransaction: Transaction to activate registration did not go through.
  """
  active_registration = _GetActiveUserRegistration(eval_context)
  if active_registration:
    if not eval_context.force_status:
      logging.info('RegisterOnline: user %s is already registered [%s]',
                   eval_context.user.email, active_registration)
      return (active_registration.status,
              [_('registered user re-register attempt')])
    else:
      # User needs to be force enrolled, if the active status is not enrolled
      # then change it to enrolled with force_status bit.
      if active_registration.status != utils.RegistrationStatus.ENROLLED:
        active_registration.status = utils.RegistrationStatus.ENROLLED
        active_registration.confirmed = utils.RegistrationConfirm.READY
        active_registration.force_status = True  # Force the result offline.
        active_registration.put()
      return (utils.RegistrationStatus.ENROLLED, [_('force enrolled')])

  # An inactive registration entry is written to datastore even before checking
  # if this registration is acceptable. This registration entry will be in a
  # 'not ready' state so will not be processed by the offline process. This
  # entry is counted for resource allocations by the online process iff memcache
  # count of available resources fails. Thus helps us to aggressively over count
  # the usage of the resources so that cases where a registration was first
  # accepted and then later rejected will not occur.
  new_entry = models.UserRegistration(
      eval_context=eval_context, status=utils.RegistrationStatus.ENROLLED,
      confirmed=utils.RegistrationConfirm.NOT_READY,
      active=utils.RegistrationActive.INACTIVE,
  )
  new_entry.put()

  # Process the rules and get the rules decision.
  result = _RulesEvaluate(eval_context, None, utils.RegistrationStatus.ENROLLED,
                          is_online=True)

  final_status = result['final_status']
  results = result['all_rule_results']
  rule_tags = list(result['all_rule_tags'])
  a_rule_tags = list(result['affecting_rule_tags'])
  a_configs = list(result['affecting_rule_configs'])
  # This will release resources iff the registration was denied.
  _RulesNotify(final_status, results)

  reasons = []
  if final_status != utils.RegistrationStatus.ENROLLED:
    reasons = [cfg.GetDescription() for cfg in a_configs]

  if final_status is None:  # Denied, delete temporary registration entry.
    new_entry.delete()
  else:
    new_entry.status = final_status
    new_entry.confirmed = utils.RegistrationConfirm.READY  # Ready for offline.
    new_entry.active = utils.RegistrationActive.ACTIVE  # This entry is active.
    new_entry.rule_tags = rule_tags
    new_entry.affecting_rule_tags = a_rule_tags
    new_entry.affecting_rule_configs = a_configs
    new_entry.notify_email = notify

    new_entry.put()

  logging.info('RegisterOnline: %s -> %s %s', eval_context.user.appengine_user,
               final_status, reasons)

  return (final_status, reasons)


def UnregisterOnline(eval_context, post_process_tasks=None):
  """Attempts to unregister the user online.

  Runs in a protected mutually exclusive block for a user, activity and attempts
  to unregister user from the activity previously registered. The function runs
  the relevant rules and makes a collective choice.

  Args:
    eval_context: EvalContext containing the user registration information.
    post_process_tasks: List of processors.TaskConfigs that are used to enqueue
      tasks once the offline process processes the unregistration.

  Returns:
    (final_status, message_list)
    final_status: The status allowed by rules following unregister request.
    message_list: String list of messages explaining reasons for final_status.
  """
  lock = RegistrationLock(eval_context.user.appengine_user,
                          eval_context.activity.key())
  return lock.RunSynchronous(_UnregisterOnlineUnsafe, eval_context,
                             post_process_tasks)


def _UnregisterOnlineUnsafe(eval_context, post_process_tasks):
  """Unregister the user, but is called protected by a lock.

  Args:
    eval_context: EvalContext containing the user registration information.
    post_process_tasks: List of processors.TaskConfigs that are used to enqueue
      tasks once the offline process processes the unregistration.

  Returns:
    (final_status, message_list)
    final_status: The status allowed by rules following unregister request.
    message_list: String list of messages explaining reasons for final_status.

  Raises:
    FailedTransaction: Transaction to finalize unregister did not go through.
  """
  post_process_tasks = post_process_tasks or []
  active_registration = _GetActiveUserRegistration(eval_context)
  if not active_registration:  # Nothing to unregister from
    logging.info('UnregisterOnline: can not find registration for user %s',
                 eval_context.user.email)
    return (utils.RegistrationStatus.UNREGISTERED,
            [_('user must be registered/waitlisted to unregister')])

  # We have an active user registration from which we can unregister.
  active_status = active_registration.status

  # Process rules to unregister. The assumption is that for a UNREGISTERED
  # target_state the rules will not release any resources or slots.
  result = _RulesEvaluate(eval_context, active_status,
                          utils.RegistrationStatus.UNREGISTERED, is_online=True)
  final_status = result['final_status']
  rule_tags = list(result['all_rule_tags'])
  affecting_rule_tags = list(result['affecting_rule_tags'])
  affecting_configs = list(result['affecting_rule_configs'])

  reasons = []
  if final_status == utils.RegistrationStatus.UNREGISTERED:  # Rules agree.

    def InitiateUnregister():
      """Create unregister active entities."""
      new_entry = models.UserRegistration(
          parent=active_registration, eval_context=eval_context,
          status=utils.RegistrationStatus.UNREGISTERED,
          confirmed=utils.RegistrationConfirm.READY,
          active=utils.RegistrationActive.INACTIVE,
          affecting_rule_tags=affecting_rule_tags,
          affecting_rule_configs=affecting_configs,
          rule_tags=rule_tags,
          post_process_tasks=post_process_tasks
      )

      new_entry.put()

      active_registration.active = utils.RegistrationActive.INACTIVE
      active_registration.put()

      return new_entry

    
    new_entry = db.run_in_transaction(InitiateUnregister)
    assert new_entry
  else:
    reasons = [cfg.GetDescription() for cfg in affecting_configs]

  # The online process will not decrement or free resources. Hence the rules are
  # not yet notified of the unregistration decision like we did for enrollment.
  # The resources are freed by the offline unregistration process.

  logging.info('UnregisterOnline %s,%s,%s', eval_context.user.email,
               final_status, reasons)
  return (final_status, reasons)


def _GetOrCreateConfigEntity(key, config_value='', config_key=''):
  """Get a config entity with given key or construct one using arguments."""
  entity = db.get(key)
  if entity is not None: return entity
  # A newly instantiated config is not written to db, just constructed.
  return models.Configuration(key_name=key.name(), config_value=config_value,
                              config_key=config_key)


class _CheckPointed(object):
  """Decorator that determines a function crash and changes memcache namespace.

  Decorates functions such that a configuration object tracks the begin and end
  of the function. When a decorated function exits abnormally then the next
  decorated function that runs will be given a new namespace. When functions
  that modify memcache crash, memcache can be in an invalid state and we change
  the namespace to stop using whatever state we had constructed.

  IMPORTANT: This decorator is not thread-safe and should only be executed in a
  locked method.

  """

  def __init__(self, run_function):
    """Store run_function that needs to be called along with decorated code.

    Args:
      run_function: Function that is decorated with check point functionality.
          Run_function should accept named argument namespace which changes when
          a decorated function call fails.

    """
    self._run_function = run_function

  def __call__(self, *args, **kwargs):
    """Wrapper call that gets called when the decorated function is called."""
    run_in_progress_key = db.Key.from_path(models.Configuration.kind(),
                                           'offline_run_in_progress')
    namespace_config_key = db.Key.from_path(models.Configuration.kind(),
                                            'offline_namespace')

    def CreateNewNamespace():
      """Generate a new uuid to use as memcache namespace for the rules."""
      namespace = '__memcache_ns_%s' % uuid.uuid4()
      models.Configuration(key_name=namespace_config_key.name(),
                           config_value=namespace).put()
      return namespace

    if db.get(run_in_progress_key) is not None:
      # The previous offline run excited abnormally, we have to reset namespace.
      namespace = CreateNewNamespace()
    else:
      # Normal exit or never ran before.
      models.Configuration(key_name=run_in_progress_key.name()).put()
      namespace_config = db.get(namespace_config_key)
      if namespace_config is None:
        # Never ran before, create new namespace.
        namespace = CreateNewNamespace()
      else:
        namespace = str(namespace_config.config_value)

    # Call the decorated function with namespace argument.
    kwargs['namespace'] = namespace
    result = self._run_function(*args, **kwargs)

    db.delete(run_in_progress_key)
    return result


def _RulesNotifyOnline(eval_context, config_list,
                       evaluated_state, final_state):
  """Create rules for online processing and notify them of final_state.

  This function is called by the offline process when it determines that the
  online determined state for a registration can be changed such that resources
  counted by the online process can be decremented. Called when an unregistered
  entry is processed by offline process and online resources are decremented.
  Can also be called when online process has registered a user but offline
  determines that such a registration shouldn't be possible.

  Args:
    eval_context: The EvalContext used as parameter in rule creation.
    config_list: The list of RuleConfigs used to create the rules. Might have
        repetitions.
    evaluated_state: The state which the rules previously evaluated to.
    final_state: The state which the rules will be notified as the final result.
  """
  online_results = []
  for config in set(config_list):
    rule_list = config.CreateRules(eval_context, False, namespace='')
    online_results.extend([(r, evaluated_state) for r in rule_list])

  _RulesNotify(final_state, online_results)  # Release/decrement resources.


@_CheckPointed
def _UnregisterOfflineUnsafe(unregister, namespace=None):
  """Check an unregistration entry, frees resources if feasible, else cancels.

  Tries to evaluate an unregistration offline. If the unregistration fails then
  the parent entity is reactivated. This can happen due to changed or new rules
  introduced into the system from the time the online rule evaluated the entry.
  If the unregistration succeeds then the resources are freed in the online
  state.

  Args:
    unregister: The user unregistration entity that is being processed offline.
    namespace: The memcache state namespace.
  """
  parent_enroll = unregister.parent()
  assert parent_enroll is not None, ('unregister entity %s has no parent' %
                                     unregister.key())
  # Check if the offline process processed the corresponding enrollment and
  # counted the resources required for enrollment.
  if (parent_enroll.confirmed == utils.RegistrationConfirm.PROCESSED and
      parent_enroll.status == utils.RegistrationStatus.ENROLLED):
    processed_enroll = True
  else:
    processed_enroll = False

  # We have to force an unregistration. If the rules in offline mode don't
  # accept to an unregistration then it's an error.
  # This is because we don't restrict the user from trying to register back
  # again after unregistering online. If this unregistration is not accepted
  # then rolling it back will cause consistency problems with multiple active
  # registrations being active for the user.

  eval_context = EvalContext.CreateFromUserRegistration(unregister)
  # No decrement of resources happen during unregister rules evaluation.
  result = _RulesEvaluate(eval_context, parent_enroll.status,
                          utils.RegistrationStatus.UNREGISTERED,
                          namespace=namespace, is_online=False)

  final_status = result['final_status']
  results = result['all_rule_results']
  configs = result['all_rule_configs']
  affecting_rule_tags = result['affecting_rule_tags']

  # For now just assert. Need a way to enforce this in the future.
  assert final_status == utils.RegistrationStatus.UNREGISTERED

  # Check if this unregister entry triggered an online decrement before.
  online_decrement = unregister.online_unregistered
  unregister.online_unregistered = True  # Can only decrement once for online.
  unregister.put()

  logging.info('UnregisterOffline(%s):%s,%s,%s', processed_enroll,
               eval_context.user.appengine_user, final_status,
               affecting_rule_tags)

  if not online_decrement:
    # Decrement online resources that were incremented on online register.
    # This attempt is only made once. In the next attempt since unregister
    # entity already has online_unregistered set to True above, this block of
    # code will not be executed. In the worst case the online process will be
    # over counting.
    _RulesNotifyOnline(eval_context, configs,
                       utils.RegistrationStatus.UNREGISTERED,
                       utils.RegistrationStatus.UNREGISTERED)

  if processed_enroll:
    # Decrement resources.
    _RulesNotify(final_status, results)  # Release resources/decrement.

    # Store the affecting rule tags in a configuration object to help re-process
    # waitlisted registrations that are waiting for these resources.
    SaveRuleTagsToReprocess(affecting_rule_tags)

  # Notify the user even when registration wasn't confirmed. The notification
  # is done just before the registration entries are deleted so that no more
  # notifications happen.
  _NotifyUserAndUpdateCalendars(unregister)

  def RemoveProcessedUnRegistration():
    # We want to delete all aspects of this registration for simplicity. If not
    # deleted the offline process on memcache failure will over count resources.
    # This is because the count is constructed by reading all processed and
    # enrolled entities. Unless the count also considers the processed and
    # unregistered entitites to decrement resource count it will be wrong. This
    # is unnecessary logic and more simple to just remove them from the system
    # like they never existed.

    # TODO(user): We should not delete entities, we should use the same deleted
    # flag as the rest of the entities and update the queries for registrations.
    # so we have some sort of history
    unregister.delete()
    parent_enroll.delete()

    # Run the post processing tasks if present after unregistration.
    if unregister.post_process_tasks:
      for task_config in unregister.post_process_tasks:
        task_config.DispatchTask(transactional=True)

    return True

  assert db.run_in_transaction(RemoveProcessedUnRegistration)


@_CheckPointed
def _RegisterOfflineUnsafe(register, namespace=None):
  """Check registration is feasible, if yes update state, else remove entry.

  Tries to evaluate a registration offline. If the registration fails then the
  registration entry is removed. If it succeeds either as waitlisted or enrolled
  then the entry is updated with the state and recorded as processed. If
  enrolled then the state is updated to count for the resources taken up by the
  enrollment. Waitlisted states do not account for resources.

  Args:
    register: The user registration entity that is being processed offline.
    namespace: The memcache state namespace.
  """
  # We first check that this registration is up to date with its activity.
  schedules = register.activity.ActivitySchedulesQuery()

  if not register.isValid(schedules):
    # We do not notify users as we do it later
    _SyncRegistrationsWithActivityUnsafe(register.activity.key(),
                                         [register.key()],
                                         notify_users=False)
    # We reload registration to get latest update
    register = models.UserRegistration.get(register.key())

  eval_context = EvalContext.CreateFromUserRegistration(register)

  # By the time we process this entry its probable that an unregister entry
  # was added into our system that could have changed our final_status to be
  # enrolled instead of waitlisted. This is ok since waitlisted entries are
  # reprocessed after the new unregister is processed.
  result = _RulesEvaluate(eval_context, None, utils.RegistrationStatus.ENROLLED,
                          namespace=namespace, is_online=False)
  final_status = result['final_status']
  rule_results = result['all_rule_results']
  configs = result['all_rule_configs']
  rule_tags = list(result['all_rule_tags'])
  affecting_rule_tags = list(result['affecting_rule_tags'])
  affecting_config = list(result['affecting_rule_configs'])

  _RulesNotify(final_status, rule_results)  # If needed release resources.

  logging.info('RegisterOffline:%s,%s,%s', eval_context.user.appengine_user,
               final_status, affecting_rule_tags)

  register.confirmed = utils.RegistrationConfirm.PROCESSED
  register.rule_tags = rule_tags
  register.affecting_rule_tags = affecting_rule_tags
  register.affecting_rule_configs = affecting_config

  if final_status is None:
    # TODO(user): We can be nicer to online state and notify the online
    # process of this denial (like we do in unregistration offline above.)

    # Cannot enroll, the rules changed their final decision offline or rules
    # were modified. For example when manager disapproves a course, or when
    # UserInfoService wasn't available before and becomes available later on.
    register.status = utils.RegistrationStatus.UNREGISTERED
    _NotifyUserAndUpdateCalendars(
        register, notifications.NotificationType.ENROLL_REJECTED)
    # Remove the registration.
    register.delete()
    # Decrement the online held resources for this registration.
    _RulesNotifyOnline(eval_context, configs,
                       utils.RegistrationStatus.ENROLLED, None)

  else:  # Enrolled or Waitlisted
    assert (final_status == utils.RegistrationStatus.WAITLISTED or
            final_status == utils.RegistrationStatus.ENROLLED)
    register.status = final_status

    _NotifyUserAndUpdateCalendars(register)
    register.put()


def _NotifyUserAndUpdateCalendars(register, notification_type=None):
  """Notifies the user and updates user state.

  Args:
    register: A models.UserRegistration that needs notifications to be updated.
        This registration object might not reflect in the datastore, but will
        have the latest state that the rule engine has evaluated and needs
        notifications to be based off it.
    notification_type: A notifications.NotificationType of what notification to
      trigger. Defaults to register.status notification type.
  """
  # TODO(user): Notify and update using a task to make sure this email goes
  # through properly.
  
  # d/thread/3838abe5dde8485a/c0bdb7ec0d4afc44?lnk=gst&q=transaction# c0bdb7ec0d
  # 4afc44
  if register.status == register.last_notified:
    return  # Already notified state in the past.

  # Calendar updates.
  if register.status in [utils.RegistrationStatus.UNREGISTERED,
                         utils.RegistrationStatus.ENROLLED]:
    schedule_key_str_list = [str(skey) for skey in register.schedule_list]
    deferred.defer(
        _SyncRegistrationCalendarList, register.user.email(),
        schedule_key_str_list, _queue='calendar')

  # Emails.
  if register.notify_email:
    if (register.status == utils.RegistrationStatus.UNREGISTERED and
        register.parent() and register.parent().last_notified is None):
      # user got unregistered. We make sure user got registration notification
      # to keep consistent so user do not only get unregistration email out of
      # the blue.
      notifications.SendMail(register, notifications.NotificationType.ENROLLED)

    notification_type = notification_type or register.status
    notifications.SendMail(register, notification_type)

  # This might not get persisted, we take an optimistic approach. If it is
  # persisted then a similar notification is not attempted next time.
  register.last_notified = register.status


def _FetchAndProcessOffline(run_function, status, *args, **kwargs):
  """Run a given function with the next unprocessed entity under entity lock.

  The function queries for the next registration entity in the queue of given
  status and passes it along to the given function.

  Args:
    run_function: Function to run after fetching the next unprocessed entity.
        run_function should accept the queried entity as its first argument.
    status: The next unprocessed entity with this status is queried for.
    args: Arguments passed to run_function.
    kwargs: Named arguments passed to run_function.

  Returns:
    False when no unprocessed entries with given status are present.
  """
  q = models.UserRegistration.all()
  utils.AddFilter(q, 'status =', status)
  utils.AddFilter(q, 'confirmed =', utils.RegistrationConfirm.READY)
  models.UserRegistration.AddRegisterOrder(q)

  record = q.get()
  if record is None: return False  # None found with said criteria.

  def ProcessFetchedRecord():
    """Function runs protected under the record lock and calls run_function."""
    # Query for the record again, check if the record hasn't changed.
    check_changed = models.UserRegistration.get(record.key())
    if (check_changed is not None and
        check_changed.status == status and
        check_changed.confirmed == utils.RegistrationConfirm.READY):
      run_function(check_changed, *args, **kwargs)

  def ActivityLockWrapper():
    # Call run_function under the lock.
    reg_lock = RegistrationLock(record.user, record.GetKey('activity'))
    reg_lock.RunSynchronous(ProcessFetchedRecord)

  # We lock activity before processing any registration
  lock = models.Activity.GetLock(record.GetKey('activity'))
  lock.RunSynchronous(ActivityLockWrapper)
  return True


def SaveRuleTagsToReprocess(rule_tags):
  """Informs the rule engine the rule tags that need reprocessing.

  The rule engine will re-process all registrations that contain the given rule
  tags as affecting rule tags.

  Args:
    rule_tags: list or set of string rule tags that identify registrations in
        need of reprocessing.
  """

  def SaveRuleTagsToReprocessUnsafe(rule_tags):
    """Unsafe inner method."""
    logging.info('Rule tags to reprocess: %s', rule_tags)
    reprocess_entity = _GetOrCreateConfigEntity(_REPROCESS_RULE_TAGS_KEY)
    old_rule_tag_set = set()
    if reprocess_entity.config_value:
      old_rule_tag_set = set(reprocess_entity.config_value.split(','))
    old_rule_tag_set = old_rule_tag_set.union(set(rule_tags))

    reprocess_entity.config_value = ','.join(old_rule_tag_set)
    reprocess_entity.put()

  if rule_tags:
    lock = utils.DbLock(str(_REPROCESS_RULE_TAGS_KEY))
    lock.RunSynchronous(SaveRuleTagsToReprocessUnsafe, rule_tags)


def SyncRegistrationsWithActivity(activity_key, notify_users=True):
  """Syncs registrations with activity.

  Args:
    activity_key: String activity key or db.Key.
    notify_users: Whether to notify users by email or not.
  """
  if isinstance(activity_key, basestring):
    activity_key = db.Key(activity_key)
  user_regs = []
  for reg in models.UserRegistration.ActiveQuery(activity=activity_key,
                                                 keys_only=True):
    user_regs.append(reg)

  # Process no more than 10 regs at a time
  user_reg_buckets = utils.ArraySplit(user_regs, 10)

  for bucket in user_reg_buckets:
    deferred.defer(_SyncRegistrationsWithActivity, activity_key,
                   bucket, notify_users)


def _SyncRegistrationsWithActivity(activity_key, registration_keys,
                                   notify_users=True):
  """Synchronizes activity & schedules changes with existing user registrations.

  Part 2 of 2 step process. Updates user registration.
  This method should either be called on ENROLLED/CONFIRMED registration after
  an activity update ONLINE or on READY entries when processed offline.

  Args:
    activity_key: String activity key or db.Key.
    registration_keys: List of db.Key for UserRegistrations.
    notify_users: Whether to notify users by email or not.
  """
  lock = models.Activity.GetLock(activity_key)
  lock.RunSynchronous(_SyncRegistrationsWithActivityUnsafe, activity_key,
                      registration_keys, notify_users)


def _SyncRegistrationsWithActivityUnsafe(activity_key, registration_keys,
                                         notify_users=True):
  logging.info('Synchronizing user registrations with activity %s',
               activity_key)
  if isinstance(activity_key, basestring):
    activity_key = db.Key(activity_key)

  current_schedule_keys = set()
  schedule_map = {}
  aps_map = {}

  current_schedules = models.Activity.SchedulesQueryFromActivityKey(
      activity_key)
  current_schedule_keys.update([s.key() for s in current_schedules])
  for schedule in current_schedules:
    schedule_map[schedule.key()] = schedule

  def GetAccessPoint(ap_key):
    ap = aps_map.get(ap_key)
    if not ap:
      ap = models.AccessPoint.get(ap_key)
      aps_map[ap_key] = ap
    return ap

  def GetAccessPointForOffice(ap_key, schedule):
    """Retrieves an access point from schedule which matches best given ap."""
    # We lookup an access point with the same primary tag.
    # By design, it HAS to be available (we enforce timeslots to have all
    # the same office locations).
    office_location = GetAccessPoint(ap_key).tags[0]
    aps_available = schedule.access_points
    aps_available += schedule.access_points_secondary
    for available_ap_key in aps_available:
      available_ap = GetAccessPoint(available_ap_key)
      if office_location == available_ap.tags[0]:
        # Found one, we use it. The logic here could be smarter in trying
        # to distribute people evenly across APs which have the same
        # office location. But it is really hard to get this correctly
        # because of rules on access points. Since we currently
        # don't re-process enrolled registrations for change of rules, it
        # does not make sense to try to get this part right. So we just
        # do a simple allocation algorithm for now. Course admins can
        # override it manually as needed.
        return available_ap_key
    # We should always find an access point with the given office location
    assert False

  for reg in db.get(registration_keys):
    new_schedules = []
    new_aps = []
    for schedule_key, ap_key in zip(reg.schedule_list, reg.access_point_list):

      if schedule_key in current_schedule_keys:
        # Schedule still exists for this activity, we sync it
        schedule = schedule_map[schedule_key]
        new_schedules.append(schedule_key)
        if (ap_key in schedule.access_points or
            ap_key in schedule.access_points_secondary):
          # Access point is still available, we can reuse it
          new_aps.append(ap_key)
        else:
          # Access point not  available anymore for the time slot. We pick
          # a new one based on the office location associated with it
          new_aps.append(GetAccessPointForOffice(ap_key, schedule))

    for schedule_key in current_schedule_keys:
      if schedule_key not in new_schedules:
        # New schedule was added. We select location which is good for user
        # based on user selection of any other location.
        # We assume that user usually goes to same office for all access points.
        new_aps.append(GetAccessPointForOffice(reg.access_point_list[0],
                                               schedule_map[schedule_key]))
        new_schedules.append(schedule_key)

    assert len(new_aps) == len(new_schedules)
    assert len(current_schedule_keys) == len(new_schedules)

    if (dict(zip(reg.schedule_list, reg.access_point_list)) !=
        dict(zip(new_schedules, new_aps))):
      reg.schedule_list = new_schedules
      reg.access_point_list = new_aps
    reg.put()

    if notify_users:
      # We notify user that update happened
      notifications.SendMail(
          reg, notifications.NotificationType.REGISTRATION_UPDATE)


def _ReadyRegistrationsInWaiting():
  """Runs _ReadyRegistrationsInWaitingUnsafe under a lock for thread safety."""
  lock = utils.DbLock(str(_REPROCESS_RULE_TAGS_KEY))
  return lock.RunSynchronous(_ReadyRegistrationsInWaitingUnsafe)


def _ReadyRegistrationsInWaitingUnsafe():
  """Switches waitlisted registrations that need reprocessing to ready state.

  Queries for all processed waitlisted registrations that have rule tags that
  need reprocessing and changes their state to ready for off-line processing.

  The function does small chunks of work and records progress. On an obnormal
  exit and the subsequent calling of this function again work is resumed from
  the last recorded progress point.

  Returns:
    False if no processing was done and the function did not have to change
    any waitlisted registrations into ready state, True other wise.
  """
  performed_processing = False  # Return value.

  def GetConfigStringList(entity):
    """If config value is not empty string then split by ',' else empty list."""
    if entity.config_value:
      return entity.config_value.split(',')
    return []

  tags_entity = _GetOrCreateConfigEntity(_REPROCESS_RULE_TAGS_KEY)
  tags = GetConfigStringList(tags_entity)  # Tags to reprocess.

  logging.debug('Entering _ReadyRegistrationsInWaiting for tags %s', tags)
  query_batch = 20
  registrations_entity = None

  # Step 1: Query all registrations that have given rule tags.
  # need reprocessing. Query in batches and update storage with partial results
  # to be resilient for timeouts and crashes.

  tags_bucket = tags[:query_batch]
  while tags_bucket:
    logging.debug('Processing registrations in waiting for %d tags',
                  len(tags))
    query = models.UserRegistration.all()

    # The filter with 'in' keyword generates multiple queries hence bucket
    # is limited to query_batch < 30. 30 is the query interface limit.
    utils.AddFilter(query, 'affecting_rule_tags in', tags_bucket)

    utils.AddFilter(query, 'confirmed =', utils.RegistrationConfirm.PROCESSED)
    utils.AddFilter(query, 'status =', utils.RegistrationStatus.WAITLISTED)
    utils.AddFilter(query, 'active =', utils.RegistrationActive.ACTIVE)

    new_registrations = []
    for register in query:
      new_registrations.append(str(register.key()))

    logging.debug('Found %d registrations waiting for given tags',
                  len(new_registrations))
    if new_registrations:
      # Add them to already collected registrations list.
      if registrations_entity is None:
        registrations_entity = _GetOrCreateConfigEntity(_WAITLIST_REPROCESS_KEY)
      old_registrations = set(GetConfigStringList(registrations_entity))

      new_registrations = set(new_registrations)
      new_registrations = new_registrations.union(old_registrations)

      # Update the registrations with the new ones we queried.
      registrations_entity.config_value = ','.join(new_registrations)
      registrations_entity.put()

    # Remove the tags that we have completed querying.
    tags = tags[query_batch:]
    tags_entity.config_value = ','.join(tags)
    tags_entity.put()
    performed_processing = True

    tags_bucket = tags[:query_batch]

  # Step 2: Batch up the registrations whose status needs to be changed from
  # 'processed' to 'ready'. Update the persistent storage after every batch
  # to be resilient to timeouts/crashes.

  # Waiting entities are not counted towards resource state and hence changing
  # the confirmed state to ready will not affect the state.

  write_batch = 10
  if registrations_entity is None:
    registrations_entity = _GetOrCreateConfigEntity(_WAITLIST_REPROCESS_KEY)
  registrations = GetConfigStringList(registrations_entity)

  def MakeWaitingReady(register):
    if (register.status == utils.RegistrationStatus.WAITLISTED and
        register.confirmed == utils.RegistrationConfirm.PROCESSED and
        register.active == utils.RegistrationActive.ACTIVE):
      register.confirmed = utils.RegistrationConfirm.READY
      register.put()

      logging.info('OfflineMakeWaitingReady:%s, %s', register.user,
                   register.affecting_rule_tags)

  registrations_bucket = registrations[:write_batch]
  while registrations_bucket:
    for register_key_str in registrations_bucket:

      waiting = db.get(db.Key(register_key_str))
      if waiting is None: continue

      lock = RegistrationLock(waiting.user,
                              waiting.GetKey('activity'))
      lock.RunSynchronous(MakeWaitingReady, waiting)

    # Checkpoint work after a batch is updated.
    registrations = registrations[write_batch:]
    registrations_entity.config_value = ','.join(registrations)
    registrations_entity.put()
    performed_processing = True

    registrations_bucket = registrations[:write_batch]

  return performed_processing


def ProcessOfflineUnsafe():
  """The offline user registrations processing function.

  The function goes through registrations that are new in the system and updates
  rule states. It performs a unit of work each time it is called and needs to be
  called repeatedly until it returns false for the registrations in the system
  to be confirmed and processed off-line.

  This function has two distinctions from the online registration. First, it is
  expected to call this function serially which avoids rule state contention.
  Second, the function goes back in time and processes waitlisted registrations
  unlike the online process that only deals with current user requests.

  WARNING: This function should be called serially under a lock.

  Returns:
    False if off-line processing at that moment is complete. False implies
    that there aren't any registrations at that time that aren't processed. This
    state can change quickly though if the online registration system fulfills
    a new registration request.
  """

  # Sync activity calendars
  if query_processor.PerformQueryWork(
      query_processor.SYNC_SCHEDULES_WITH_CALENDAR):
    return True  # More calendar syncs needed.

  # Process the unregistered entity first. This will allow resources
  # to be freed up and we can avoid re-evaluating wait lists multiple times.
  if _FetchAndProcessOffline(_UnregisterOfflineUnsafe,
                             utils.RegistrationStatus.UNREGISTERED):
    return True

  # Process the enrolled entity after unregistered. This way all the resources
  # that are used up for registrations are counted and accounted for.
  if _FetchAndProcessOffline(_RegisterOfflineUnsafe,
                             utils.RegistrationStatus.ENROLLED):
    return True

  # For the rule tags that need reprocessing we collect all the waitlisted
  # registrations that contain these tags and make them ready for offline
  # processing again.
  if _ReadyRegistrationsInWaiting():
    return True

  # Finally process the waitlisted entries. The waitlisted entities can be
  # reprocessed multiple times while there is a chance that one of them can be
  # successfully enrolled.
  return _FetchAndProcessOffline(_RegisterOfflineUnsafe,
                                 utils.RegistrationStatus.WAITLISTED)


def _ProcessRuleUpdate(rule_configs, program_or_activity_key=None):
  """Triggers reprocessing of registrations as needed after rule update.

  Updating a rules may trigger some reprocessing of existing user registrations
  and retrieval of data from datastore. Such operation may be expensive and
  is better executed in a task.

  Args:
    rule_configs: rule_configs that have been updated (or deleted).
    program_or_activity_key: db.Key of models.Program or models.Activity this
        rule applies to.
  """
  if program_or_activity_key is not None:
    program_or_activity = db.get(program_or_activity_key)
  else:
    program_or_activity = None

  reprocess_rule_tags = []
  for rule_config in rule_configs:
    rule_class = rules.GetRule(rule_config.rule_name)
    reprocess_rule_tags.extend(rule_class.TagsToReprocessOnChange(
        rule_config, program_or_activity))

  SaveRuleTagsToReprocess(reprocess_rule_tags)


def _ReprocessRegistrations(program_or_activity_key):
  """Triggers reprocessing of registrations under a given entity scope.

  This function reprocess all waitlisted registrations under given
  program or activity so that new rules and their workflows can be applied.

  Args:
    program_or_activity_key: db.Key of models.Program or models.Activity where
        new rules have been added.
  """
  SaveRuleTagsToReprocess([_GetRuleTagForEntity(program_or_activity_key)])


def _GetRuleTagForEntity(program_or_activity_key):
  """A tag for registrations that belong to given program or activity."""
  # TODO(user): We should avoid this extraneous stamping since program
  # and activity key are actually available on registration, but that would
  # require another configuration object or way to recognize the tag outside
  # the rule tags mechanism. Medium priority but not required just as yet as we
  # should be good up to nearly 1000 rule tags stamped on a registration.
  return '_rule_engine_tag_%s' % program_or_activity_key


def _EnqueueProcessing(count_down=0):
  """Triggers a task to process offline.

  Args:
    count_down: Number of seconds into the future that this Task should execute,
        measured from time of insertion. Defaults to zero.
  """
  deferred.defer(ProcessOfflineTask, _countdown=count_down, _queue='offline')


def ProcessOfflineTask():
  """Runs offline process."""

  def ProcessOfflineTaskUnsafe():
    """Run the offline process (unsafe)."""
    logging.info('Offline process run start')
    more_processing = ProcessOfflineUnsafe()
    if more_processing:
      # Give one second for offline process to release lock
      _EnqueueProcessing(count_down=1)
    logging.info('Offline process run stop')

  lock = utils.DbLock('offline_process_run_lock', sleep_seconds=1)
  lock.RunSynchronous(ProcessOfflineTaskUnsafe)


def UpdateProgramOrActivityRules(program_or_activity, rule_configs):
  """Set/update rules on a program/activity and kick of necessary reprocessing.

  Updates the rules property of the given program or activity entity and kicks
  off the necessary background processing to handle the updates. The update is
  in memory and is not persisted.

  Args:
    program_or_activity: The models.Program or models.Activity to update.
    rule_configs: New rules.RuleConfig array to update program or activity with.
  """
  rule_config_map = dict([(rc.rule_name, rc) for rc in rule_configs])
  new_rule_configs = []

  # Identify the rules that are either modified or deleted.
  modified_old_rules = []
  for current_rule_config in program_or_activity.rules:
    if current_rule_config.rule_name in rule_config_map:
      new_rule_config = rule_config_map.pop(current_rule_config.rule_name)
      # Check if rule is being updated.
      if current_rule_config.parameters != new_rule_config.parameters:
        # The rule is being updated.
        modified_old_rules.append(current_rule_config)
        new_rule_configs.append(new_rule_config)  # Will have new key.
      else:  # Rule is unchanged, use the current config.
        new_rule_configs.append(current_rule_config)
    else:
      # The rule is being deleted.
      modified_old_rules.append(current_rule_config)

  # Rules left in rule_config_map are the rules that weren't there before (new).
  new_rule_configs.extend(rule_config_map.itervalues())

  # TODO(user): In theory we can also trigger events when rules are
  # deleted for workflow, but for now we just process rule deletion as a rule
  # update and reevaluate registrations. The workflow is not terminated early
  if rule_config_map.values():
    # New rules are added to scope. Reprocess all registrations under the
    # program or activity scope since we need to apply the new rules and their
    # workflow to all registrations.
    deferred.defer(_ReprocessRegistrations, program_or_activity.key(),
                   _transactional=True)
  elif modified_old_rules:
    # We can be more intelligent since only updates have happenned and we can
    # target just those registrations which are affected by the rules that are
    # modified.
    deferred.defer(_ProcessRuleUpdate, modified_old_rules,
                   program_or_activity.key(), _transactional=True)

  # Set the rules on entity for storage.
  program_or_activity.rules = new_rule_configs


def _SyncRegistrationCalendarList(user_email, schedule_key_str_list):
  """Syncs registration for calendars corresponding to given schedule list."""
  if len(schedule_key_str_list) == 1:
    _SyncRegistrationCalendar(user_email, schedule_key_str_list[0])
  else:
    for schedule_key_str in schedule_key_str_list:
      deferred.defer(_SyncRegistrationCalendar, user_email, schedule_key_str,
                     _queue='calendar')


def _SyncRegistrationCalendar(user_email, schedule_key_str):
  """Syncs registration for a single calendar corresponding to a schedule."""
  user = utils.GetAppEngineUser(user_email)
  schedule_key = db.Key(schedule_key_str)
  lock = RegistrationLock(user, schedule_key.parent())
  lock.RunSynchronous(calendar.SyncRegistrationForScheduleUnsafe,
                      user, schedule_key)
