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


"""Module describing rules applying to gLearn courses.

Depends on the rules_impl module for actual implementation of rules.

Rules can be applied to different actions:
  - whenever a user signs up for a program, activity or specific schedule, some
    rules need to be validated before the user action gets validated
  - whenever a user unregisters from a particular activity
  - when a user completes an activity, in order to grant some certification

Some use cases:
  - a particular course may not accept more than 20 people at any given time
  - SWEs are allowed to register for no more than 10 trainings / month
  - a class cannot have more than 20% of sales people
  - any google employee cannot take more than $10K worth of training in 2009
  - a user is certified in Python only after completing 3 python trainings
"""



import copy
import logging
import os

from google.appengine.api import memcache
from ragendja import dbutils
import uuid

from core import errors
from core import utils

# Number of maximum retries to regenerate the rule context.
_NUM_RETRIES = 1
_PREDICTION_MODE = 'PREDICTION_MODE'


class RuleNames(utils.ChoiceBase):
  """This class is a helper to get the available rule names."""
  EMPLOYEE_TYPE_RESTRICTION = 'EmployeeTypeRestriction'
  LOCK_PAST_ACTIVITY = 'LockPastActivity'
  MANAGER_APPROVAL = 'ManagerApproval'
  MAX_PEOPLE_ACTIVITY = 'MaxNumberRegisteredByActivity'
  TIME_CANCEL_ACTIVITY = 'TimeCancelByActivity'
  TIME_CANCEL_ACCESS_POINT_TAG = 'TimeCancelByAccessPointTag'
  TIME_REGISTER_BY_ACTIVITY = 'TimeFrameRegistrationByActivity'
  TIME_REGISTER_BY_ACCESS_POINT_TAG = 'TimeFrameRegistrationByAccessPointTag'


class RuleConfig(dbutils.FakeModel):
  """Rule with parameters to be processed by the rule engine..

  Attributes:
    rule_name: A string name of RuleBase class.
    parameters: A dictionary containing the function parameters and the
        values to be used when the rule engine calls the function.
    description: A string having the reason for using this rule, defaults to
        rule description.
    key: A unique key identifying this rule.

  Example:
    description: 'Instructor quiz is ideal only for under 10 members'.
    rule_name: 'NumberRegisteredByAccessPoint'.
    parameters: {max_register': 10}.

  """

  fields = ('rule_name', 'parameters', 'description', 'key')
  # objects = ContentTypeManager()

  def __init__(self, rule_name, parameters, description=None, key=None):

    self.rule_name = rule_name
    # Transform unicode to regular strings for key names. FakeModel attributes
    # are stored as unicode strings (JSON dumps) in datastore.
    self.parameters = dict((str(k), v) for k, v in parameters.iteritems())

    self.description = description
    if not key:
      # We generate a unique key for this rule. We convert to string so it can
      # get JSON serialized when stored in datastore (FakeModel uses JSON)
      self.key = str(uuid.uuid1())
    else:
      # The key is already provided. This happens when the RuleConfig is
      # deserialized from datastore. Note that this key is always created with
      # a call to uuid.uuid1() in the first place.
      self.key = key

  def CreateRules(self, eval_context, offline, namespace=''):
    """Creates the rule associated with this rule configuration.

    Args:
      eval_context: A EvalContext object.
      offline: A boolean to indicate that this rule is evaluated offline.
        Rules which run online are not run in a thread safe environment.
        In offline mode, only one process will evaluate rules at any given time.
      namespace: An optional string to control the namespace where this rule
        stores its state. Note that the given namespace may not be the one
        exactly used - but it will be part of the final namespace (so providing
        a unique namespace here will avoid collisions).

    Returns:
      A list of RuleBase instance(s), [] if no rules available.
    """
    rule = GetRule(self.rule_name)
    process_lists = rule.CanProcessMultipleSchedules()
    if process_lists:
      rule_instance = rule(key=self.key,
                           eval_context=eval_context,
                           offline=offline,
                           namespace_prefix=namespace,
                           **self.parameters)
      return [rule_instance]
    else:
      # This rule can only work off individual schedule/access points
      # We break down the list of schedules/access points in individual items.
      rules = []
      for schedule, ap in zip(eval_context.schedule_list,
                              eval_context.access_point_list):
        context = copy.copy(eval_context)
        context.schedule_list = [schedule]
        context.access_point_list = [ap]

        rule_instance = rule(key=self.key,
                             eval_context=context,
                             offline=offline,
                             namespace_prefix=namespace,
                             **self.parameters)
        rules.append(rule_instance)

      return rules

  def GetDescription(self):
    """The description of this rule or the default rule description."""
    if self.description:
      return self.description
    else:
      return GetRule(self.rule_name).GetDescription()

  def __repr__(self):
    tmp = 'RuleConfig(%s, %s, description=%s, key=%s)'
    return tmp % (self.rule_name, self.parameters, self.description, self.key)

  # Name required by appengine patch.
  # Suppress pylint invalid method name warning.
  # pylint: disable-msg=C6409
  @classmethod
  def all(cls):
    """Method needed by the django admin interface to list possible values."""
    return []


class RuleBase(object):
  """Abstract class for a standard rule.

  Attributes:
    eval_context: A EvalContext object.
    key: Unique key associated with this rule.
    offline: A boolean to indicate whether this rule is being processed
      online or offline.
  """

  def __init__(self, key, eval_context, offline, namespace_prefix=''):
    self.eval_context = eval_context
    self.key = key
    self.offline = offline
    self.online = not offline
    if offline:
      prefix = 'offline'
    else:
      prefix = 'online'
    self.namespace = '%s_%s%s' % (prefix, namespace_prefix, key)

  @classmethod
  def GetDescription(cls):
    """Returns the description of the rule.

    Returns:
      Default implementation returns the class name.
    """
    return cls.__name__

  @classmethod
  def IsCertify(cls):
    """Returns whether this rule applies to program certification.

    Returns:
      True iff this rule applies to program certification.
    """
    return issubclass(cls, RuleCertify)

  @classmethod
  def IsRegister(cls):
    """Returns whether this rule applies to registration.

    Returns:
      True iff this rule applies to registration for a program, activity or
      schedule.
    """
    return issubclass(cls, RuleRegister)


class RuleCertify(RuleBase):
  """Base class for a program certification rule."""

  def __init__(self, *args, **kargs):
    super(RuleCertify, self).__init__(*args, **kargs)

  def Evaluate(self):
    """Evaluates the rule.

    Returns:
      An integer from 0 to 100 representing the percentage toward certification.
    """
    raise NotImplementedError


class RuleRegister(RuleBase):
  """Base class for a program / activity / schedule registration rule."""

  def __init__(self, *args, **kargs):
    super(RuleRegister, self).__init__(*args, **kargs)

  def Evaluate(self, initial_state, target_state):
    """Evaluates the rule.

    Args:
      initial_state: Original state of the user registration.
        One of utils.RegistrationStatus states or None.
      target_state: State that the user is trying to transition to.
        One of utils.RegistrationStatus states, must be different from
        initial_state.

    Returns:
      A dict with following keys:
       - status: a utils.REGISTRATION_STATUS, outcome of rule evaluation.
       - rule_tags: An optional string list of tags for the registration. These
         tags can be used to gather registrations with some properties later.
         Suppose there is a rule that places registered users to a baseball game
         on waitlist until it can confirm the weather for New York is sunny on
         game day. It can provide a unique tag for New York weather for that day
         and all registrations in the system that depend on this event can later
        be retrieved by the rule or rule engine for reprocessing.
    """
    raise NotImplementedError

  def ProcessOutcome(self, eval_state, final_state):
    """Method called by the rule engine after rules have been evaluated.

    Default implementation does nothing.

    Args:
      eval_state: The state as returned by the call to _Evaluate() on this rule.
        One of utils.RegistrationStatus states.
      final_state: The final state after evaluation of all rules.
        One of utils.RegistrationStatus states.
    """
    pass

  @classmethod
  def CanProcessMultipleSchedules(cls):
    """Returns whether this rule can process list of access_points/schedules.

    A rule evaluation can either work on a list of schedule/access points for a
    particular user or on individual schedule/access point.
    In the latter case, the evaluation of the rule will only consider the first
    schedule/access point of the eval_context lists when Evaluate() is invoked.

    Returns:
      A boolean indicating if the rule can process list of schedules/access
      points for registration.
    """
    return True

  @classmethod
  def IsResourceRule(cls):
    """Returns whether this rule handles resource allocation.

    Returns:
      True iff this rule handles resource allocation.
    """
    return issubclass(cls, RuleRegisterResource)

  # Suppress pylint unused argument for default implementation.
  # pylint: disable-msg=W0613
  @classmethod
  def TagsToReprocessOnChange(cls, rule_config, program_or_activity=None):
    """Tags that identify registrations in need of reprocessing on rule change.

    A rule can decide which rule tags need to be reprocessed when it is changed.

    Args:
      rule_config: Ruleconfig associated with the rule.
      program_or_activity: models.Program or models.Activity relevant to that
        rule.

    Returns:
      The list of rule tags that identify registrations that need reprocessing.
    """
    # By default if the rules don't implement this function then no
    # registrations are reprocessed.
    return []


class RuleRegisterResource(RuleRegister):
  """Base class for registration rules that deal with resource allocation."""

  def _BuildContext(self):
    """Builds the context associated with this rule.

    Each rule may need to gather some values in order to evaluate. This is
    called the context of the rule. This context is cached and reused during
    rule evaluation by the rule engine. This method is automatically called to
    regenerate the cache when the cache gets flushed.

    For example, a rule which restricts $10k/year of training for a team would
    need to retrieve all the trainings that people from that team registered for
    every time someone registers again.
    This operation could be expensive. To make it faster, the rule can cache
    information using its context.

    Returns:
      A dictionary of key / value pairs where the value is an integer.
      Default implementations returns {}. Rules should override as needed.
    """
    return {}

  def _Regenerate(self):
    """Regenerates the rule context."""
    context = self._BuildContext()

    if self.online and not IsPredictionMode():
      # We do not want to count ourself twice.
      # We know that the UserRegistration entry that triggered the call is
      # already stored in datastore when we reach this code - except if we
      # are predicting outcome.
      for key, value in context.iteritems():
        context[key] = value - 1
        assert value > 0

    # The following code adds the key/values only if not present and then
    # sets an __init__ flag which contains an enumeration of the keys.
    # Since the memcache.add() calls are not transactional, it is possible
    # that __init__ key can be set but still the values associated with the keys
    # would not be present (for example cache gets flushed between add and
    # add_multi call. This is a very remote/rare case though, and this situation
    # still needs to be addressed in the _Incr / _Decr method anyway since keys
    # can get evicted from the cache at any time.

    # We add the values if and only they are not present.
    memcache.add_multi(context, namespace=self.namespace)
    # The __init__ contains a list of available keys for this context
    memcache.add('__init__', context.keys(), namespace=self.namespace)

  def _Incr(self, key, retries=_NUM_RETRIES):
    """Atomically increments a key's value.

    Args:
      key: String key to increment. Stored within the local rule context.
      retries: Maximum number of retries to increment the value for the key.

    Returns:
      New long integer value, or None if key was not in the cache, or could not
      be incremented for any other reason.
    """
    if IsPredictionMode():
      # If predicting outcome/online, we really don't need to increment, since
      # we are not competing with other requests to enroll.
      # No decrement either. We just need to get the current value.
      value = self._Get(key)
      if not value:
        value = 1
      else:
        value += 1
      return value

    try:
      value = memcache.incr(key, namespace=self.namespace)
      # Either cache is not populated yet or it was flushed.
      if value is None:
        # We check if value should be there.
        existing_keys = memcache.get('__init__', namespace=self.namespace)
        if existing_keys is None or key in existing_keys:
          # Info from memcache is stale, we regenerate
          self._Regenerate()
          existing_keys = memcache.get('__init__', namespace=self.namespace)

        if existing_keys is None or key in existing_keys:
          # key should be available now, we try again
          if retries != 0:
            value = self._Incr(key, retries - 1)
          else:
            value = None
        else:
          # the key is new, it was just not in the cache
          # This situation can happen because some rules will create keys on the
          # fly - not deriving them from the datastore. For example a key based
          # on a schedule/access point will be generated the first time a user
          # tries to register for that schedule/access point
          added = memcache.add(key, 1, namespace=self.namespace)
          if not added:
            # we try again
            if retries != 0:
              value = self._Incr(key, retries - 1)
            else:
              value = None
          else:
            # Key was added, we updated existing keys
            existing_keys.append(key)
            memcache.set('__init__', existing_keys, namespace=self.namespace)
            value = 1
    except (TypeError, ValueError), e:
      # Can happen if key is too long or invalid
      logging.error(e)
      value = None
    if value is None:
      # Despite all our efforts to inctrement the value, we could not
      # That could be because memcache is not accessible etc.
      # We can not afford to stay in such state.
      logging.error('Can not increment value for namespace %s, key %s',
                    self.namespace, key)
      raise errors.AppengineError
    return value

  def _Decr(self, key):
    """Atomically decrements a key's value.

    Args:
      key: Key to decrement.  Stored within the local rule context.
    """
    # The logic for _Decr is simpler than _Incr because if a key is not in the
    # cache during _Decr, then a following call to _Incr will take care of
    # rebuilding the correct value for that particular key. Rules which call
    # _Decr to not care about the value of the key after call is complete. Only
    # subsequent calls to _Incr are of interest.

    try:
      if not IsPredictionMode():
        memcache.decr(key, namespace=self.namespace)
    except (TypeError, ValueError), e:
      # Can happen if key is too long or invalid
      logging.error(e)

  def _Get(self, key, retries=_NUM_RETRIES):
    """Looks up a single key.

    Args:
      key: The key to look up.  Retrieved from the local rule context.
      retries: Maximum number of retries to get the value for the key.

    Returns:
      The value of the key, if found, else None.
    """
    try:
      value = memcache.get(key, namespace=self.namespace)  # @UndefinedVariable
      # Either cache is not populated yet or it was flushed.
      if value is None and retries != 0:
        self._Regenerate()
        return self._Get(key, retries - 1)
    except (TypeError, ValueError), e:
      # Can happen if key is too long or invalid
      logging.error(e)
      value = None
    return value

  def Evaluate(self, initial_state, target_state):
    """Evaluates the rule.

    Prior to calling this method, a transient models.UserRegistration MUST have
    been persisted by the caller in online mode in order to book resources
    for that rule while the rule is being evaluated.

    Args:
      initial_state: Original state of the user registration.
        One of utils.RegistrationStatus states or None.
      target_state: State that the user is trying to transition to. One of
      utils.RegistrationStatus states, must be different from initial_state.

    Returns:
      A dict with following keys:
       - status: one of utils.REGISTRATION_STATUS values as outcome of the rule
       - rule_tags: Array with a single resource identifier string key that the
         resource registration rule is using to constrain this registration.
       - resource_remaining: int remaining value of resource after which rule
         will deny registration. Can be negative. For example -5 for max people
         rule means that user is number 5 on the waitlist. Corresponds to the
         single resource identifier present in the goupd_ids array above.
         None iff resource_key is None.
    """
    raise NotImplementedError

  # Suppress pylint unused argument for default implementation.
  # pylint: disable-msg=W0613
  @classmethod
  def TagsToReprocessOnChange(cls, rule_config, program_or_activity=None):
    """Tags that identify registrations in need of reprocessing on rule change.

    For resource rules, the tags that are affected when a rule is changed are
    set of all tags that were issued by the rule in the Evaluate function
    above for registering users in the given program or activity.

    Args:
      rule_config: Ruleconfig associated with the rule.
      program_or_activity: models.Program or models.Activity relevant to that
        rule.

    Returns:
      The list of rule tags that identify registrations that need reprocessing.
    """
    # Unlike other registration rules resource registration rules are forced to
    # provide an implementation for this function.
    raise NotImplementedError


def ExtractCertifyRules(rules):
  """Extracts a list of certification rules from the given rules.

  Args:
    rules: A string list of rule class names deriving from RuleBase.

  Returns:
    The extracted list of certification rules.
  """
  return _ExtractRules(rules, 'IsCertify')


def ExtractRegisterRules(rules):
  """Extracts a list of registration rules from the given rules.

  Args:
    rules: A string list of RuleBase names.

  Returns:
    The extracted string list registration rules.
  """
  return _ExtractRules(rules, 'IsRegister')


def _ExtractRules(rules, rule_attribute):
  res = []
  for rule_name in rules:
    rule = GetRule(rule_name)
    if rule is not None and getattr(rule, rule_attribute)():
      res.append(rule_name)
  return res


def GetRule(rule_name):
  """Returns class representing the given rule.

  Args:
    rule_name: A string containing the name of the rule.
  Returns:
    The class representing the rule_name or None if not found.
  """
  try:
    return getattr(_GetRulesImplModule(), rule_name)
  except AttributeError:
    # Rule not found
    return None


def ListRules():
  """Returns a list of all available rules."""
  rules_mod = _GetRulesImplModule()
  return [val for val in rules_mod.__dict__.values() if isinstance(val, type)]


def _GetRulesImplModule():
  # Not importing at top of file to avoid circular dependency.
  # pylint: disable-msg=C6204
  from core import rules_impl
  return rules_impl


def SetPredictionMode(is_predict):
  """Sets the rules module to be in prediction mode.

  Args:
    is_predict: boolean whether to enable prediction or not.

  Every rule evaluation will be done with the given that it is to predict a
  registration, not do an actual enrollment.
  """
  os.environ[_PREDICTION_MODE] = str(is_predict)


def IsPredictionMode():
  mode = os.environ.get(_PREDICTION_MODE, 'False')
  return mode == 'True'
