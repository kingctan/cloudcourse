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

# pylint: disable-msg=W0231

"""This module contains implementations for various rules."""



# Supress pylint invalid import order
# pylint: disable-msg=C6203

# Supress pylint invalid use of super on old style class
# pylint: disable-msg=E1002

import datetime
import logging
import time

import appenginepatcher
from django.utils import translation
from google.appengine.ext import db

from core import errors
from core import models
from core import notifications
from core import request_cache
from core import rules
from core import service_factory
from core import utils


_ = translation.ugettext
STATUS = utils.RegistrationStatus


class MaxNumberRegisteredBy(rules.RuleRegisterResource):
  """Abstract class to limit the number of people who can be registered.

  Attributes:
    max_people: Maximum number of people who can registered.
  """

  # Key to keep track of how many students are currently enrolled.
  _KEY_PREFIX = '_'

  def __init__(self, max_people, *args, **kargs):
    super(MaxNumberRegisteredBy, self).__init__(*args, **kargs)
    self.max_people = max_people

  def _NormalizeKey(self, key):
    if not key:
      key = self._KEY_PREFIX
    # we normalize the key to a string
    return str(key)

  def _Evaluate(self, unused_initial_state, target_state, key=None):
    """Proxy around RuleRegister.Evaluate to deal with memcache state/keys.

    Args:
      unused_initial_state: See RuleRegister.Evaluate
      target_state: See RuleRegister.Evaluate
      key: The resource key to be used for maintaining the state in mem cache
        as far as incrementing/decrementing is concerned.

    Returns:
      Returns value that RuleRegister.Evaluate() should return.
    """
    key = self._NormalizeKey(key)
    resource_remaining = None
    if target_state == utils.RegistrationStatus.ENROLLED:
      num_students = self._Incr(key)
      if num_students is None:
        # Cannot look up the value, we waitlist.
        logging.error('Could not increment key, val, namespace [%s,%s,%s]', key,
                      self._Get(key, 0), self.namespace)
        if self.online:
          value = utils.RegistrationStatus.WAITLISTED
          resource_remaining = 0  # Conservative estimate.
        else:  # in offline mode we fail and retry again.
          assert False, 'Could not access memcache'
      elif num_students <= self.max_people:
        value = utils.RegistrationStatus.ENROLLED
        resource_remaining = self.max_people - num_students
      else:
        value = utils.RegistrationStatus.WAITLISTED
        resource_remaining = self.max_people - num_students
        if self.offline:
          self._Decr(key)
        # In online mode we don't decrement the counter because we want this
        # rule to stay in waiting state for all further requests.
        # Reasoning is that we don't want another user get ENROLLED after one
        # got WAITING for fairness reasons (since the WAITING one may get denied
        # afterwards with back-end processing)
    else:
      # This rule only tries to limit number of enrollments. Anything else is OK
      value = target_state
      resources_used = self._Get(key)
      if resources_used is None:
        resources_used = self.max_people
      # Can t lookup resources used, we take a conservative approach
      resource_remaining = self.max_people - resources_used

    # We build the limiting resource key
    contextualized_key = self.key + key
    return {'status': value, 'rule_tags': [contextualized_key],
            'resource_remaining': resource_remaining}

  def _ProcessOnlineOutcome(self, eval_state, final_state, key):
    if eval_state == utils.RegistrationStatus.UNREGISTERED:
      if final_state == utils.RegistrationStatus.UNREGISTERED:
        # Need to decrement the counter. This _ProcessOutcome for UNREGISTERED
        # is only being called by the offline process on the online rules.
        # This is the only case where the offline process impacts the online
        # context. Note that the online process never notifies offline context.
        self._Decr(key)
    else:
      assert eval_state in [utils.RegistrationStatus.WAITLISTED,
                            utils.RegistrationStatus.ENROLLED]
      if final_state is None:
        # We incremented and dont need to.
        self._Decr(key)

  def _ProcessOfflineOutcome(self, eval_state, final_state, key):
    if eval_state == utils.RegistrationStatus.UNREGISTERED:
      if final_state == utils.RegistrationStatus.UNREGISTERED:
        # we get notified but we never processed this request since this rule
        # does not act on unregister actions.
        self._Decr(key)
    elif eval_state == utils.RegistrationStatus.ENROLLED:
      if final_state != utils.RegistrationStatus.ENROLLED:
        # We incremented and dont need to.
        self._Decr(key)
    else:
      assert eval_state == utils.RegistrationStatus.WAITLISTED
      if final_state == utils.RegistrationStatus.ENROLLED:
        # We did not increment and need to.
        self._Incr(key)

  def _ProcessOutcome(self, eval_state, final_state, key=None):
    key = self._NormalizeKey(key)
    if self.offline:
      self._ProcessOfflineOutcome(eval_state, final_state, key)
    else:
      self._ProcessOnlineOutcome(eval_state, final_state, key)

  def ProcessOutcome(self, eval_state, final_state):
    self._ProcessOutcome(eval_state, final_state)


class MaxNumberRegisteredByActivity(MaxNumberRegisteredBy):
  """Limits the number of people who can be registered for an activity.

  Attributes:
    max_people: Int. Maximum number of people who can register for the activity.
  """

  def __init__(self, max_people, *args, **kargs):
    super(MaxNumberRegisteredByActivity, self).__init__(max_people, *args,
                                                        **kargs)

  def Evaluate(self, initial_state, target_state):
    return MaxNumberRegisteredBy._Evaluate(self, initial_state, target_state,
                                           None)

  # Suppress pylint unused argument for overriden method
  # pylint: disable-msg=W0613
  @classmethod
  def TagsToReprocessOnChange(cls, rule_config, program_or_activity=None):
    """Overrides parent method."""
    return [rule_config.key+cls._KEY_PREFIX]

  def _BuildContext(self):
    """Overrides parent method."""
    query = models.UserRegistration.all()
    query.filter('activity = ', self.eval_context.activity)

    _UpdateQueryMode(query, self.offline)

    num_students = 0

    for reg in query:
      if _RegistrationNeedsAccounting(reg, self.offline):
        num_students += 1

    return {self._KEY_PREFIX: num_students}

  @classmethod
  def GetDescription(cls):
    return _('Limited slots for activity.')


class MaxNumberRegisteredByAccessPoint(MaxNumberRegisteredBy):
  """Limits the number of people who can be registered for an access point.

  Due to datastore limitations, an access point cannot accept more than 1000
  people at this time.

  Attributes:
    max_people: Maximum number of people for that access point.
    access_point_key: List of AccessPoint keys to be used for this rule.
  """

  def __init__(self, max_people, access_point_keys, *args, **kargs):
    super(MaxNumberRegisteredByAccessPoint, self).__init__(max_people, *args,
                                                           **kargs)
    self.access_point_keys = access_point_keys

  def _BuildContext(self):
    """Overrides parent method."""
    return self._BuildContextFromAccessPoints(self.access_point_keys)

  @classmethod
  def CanProcessMultipleSchedules(cls):
    return False

  def _BuildContextFromAccessPoints(self, access_point_keys):
    """Builds a context from a list of access point keys.

    Args:
      access_point_keys: List of access point keys.

    Returns:
      A dictionary of key/values representing the context.
    """
    query = models.UserRegistration.all()
    query.filter('activity = ', self.eval_context.activity)
    _UpdateQueryMode(query, self.offline)

    keys = {}
    for reg in query:
      if _RegistrationNeedsAccounting(reg, self.offline):
        for schedule_key, ap_key in zip(reg.schedule_list,
                                        reg.access_point_list):
          if ap_key in access_point_keys:
            sched_key = str(schedule_key)
            # This user registration is relevant to this rule
            keys[sched_key] = keys.get(sched_key, 0) + 1

    return keys

  def Evaluate(self, initial_state, target_state):
    """Overrides parent method."""
    return self._EvaluateAccessPoints(initial_state, target_state,
                                      self.access_point_keys)

  def _EvaluateAccessPoints(self, initial_state, target_state,
                            access_point_keys):
    """Evaluates the rule based on the given list of access point keys."""
    # TODO(user): append .value once we have the right evalcontext
    # We take the first schedule/access point because this rule can not process
    # multiple schedules. As such, its context is populated with only one entry
    # at the rules level.
    access_point_key = self.eval_context.access_point_list[0].key()
    schedule_key = self.eval_context.schedule_list[0].key()
    if access_point_key in access_point_keys:
      # This rule applies to this schedule
      return self._Evaluate(initial_state, target_state,
                            schedule_key)
    else:
      return {'status': target_state, 'resource_remaining': None,
              'rule_tags': []}

  def _ProcessOutcomeAccessPoints(self, eval_state, final_state,
                                  access_point_keys):
    for schedule, access_point in zip(self.eval_context.schedule_list,
                                      self.eval_context.access_point_list):

      if access_point.key() in access_point_keys:
        self._ProcessOutcome(eval_state, final_state, schedule.key())

  def ProcessOutcome(self, eval_state, final_state):
    return self._ProcessOutcomeAccessPoints(eval_state, final_state,
                                            self.access_point_keys)

  @classmethod
  def GetDescription(cls):
    return _('Limited slots for attending location')


class MaxNumberRegisteredByAccessPointTag(MaxNumberRegisteredByAccessPoint):
  """Limits the number of people who can be registered for an access point tag.

  Every access point can have a tag associated with it. For example, both
  'Lincoln Center' and 'War Room' access points can have NYC tag.
  This rule can enforce that no more than 20 people can register with NYC.

  Attributes:
    max_people: Maximum number of people for that access point tag.
    access_point_tags: A string list of tags to be used for this rule.
  """

  def __init__(self, max_people, access_point_tags, *args, **kargs):
    ap_keys = kargs['eval_context'].activity.GetAccessPoints()
    relevant_keys = _GetRelevantAccessPointKeys(ap_keys, access_point_tags)

    super(MaxNumberRegisteredByAccessPointTag, self).__init__(max_people,
                                                              relevant_keys,
                                                              *args, **kargs)

  @classmethod
  def GetDescription(cls):
    return _('Limited slots for attending location type')


def _GetRelevantAccessPointKeys(access_point_keys, access_point_tags):
  """Returns a list of access point keys relevant to given tags.

  Args:
    access_point_keys: A list of AccessPoint keys.
    access_point_tags: A string list of access point tags.

  Returns:
    The subset of access_point_keys which corresponding access points have ALL
    the given access_point_tags.

  """
  # Get relevant access points from tags
  aps_from_tags = _GetAccessPointsWithTags(access_point_tags)

  # Extract relevant access point keys
  ap_keys_from_tags = [x.key() for x in aps_from_tags]

  # Interesect relevant access point keys with user input.
  access_point_keys = set(ap_keys_from_tags).intersection(access_point_keys)

  return access_point_keys


class TimeFrameRegistrationByActivity(rules.RuleRegister):
  """Limits the time frame for registration based for an activity.

  This rule limits the time frame in which people can register for a
  particular activity. People cannot register after the time frame has elapsed.
  If someone registers before the time frame, that person will be placed on the
  waiting list for the particular access point. Once the time frame arrives the
  person will be automatically enrolled - as long as other rules are satisfied.

  Attributes:
    start_time: Datetime at which people can start registering.
    end_time: Datetime after which people cannot register.
  """

  def __init__(self, start_time, end_time, *args, **kargs):
    super(TimeFrameRegistrationByActivity, self).__init__(*args, **kargs)
    self.start_time = datetime.datetime.fromtimestamp(start_time)
    self.end_time = datetime.datetime.fromtimestamp(end_time)

  def Evaluate(self, initial_state, target_state):
    if target_state == utils.RegistrationStatus.ENROLLED:
      value = _CanRegisterTimeWindows(initial_state,
                                      self.eval_context.queue_time,
                                      self.start_time, self.end_time)
    else:
      value = target_state
    return {'status': value}

  @classmethod
  def GetDescription(cls):
    return _('Registration window.')


class TimeFrameRegistrationByAccessPointTag(rules.RuleRegister):
  """Limits the time frame for registration based on access point tag.

  This rule limits the time frame in which people can register for a
  particular activity / access point tag. People cannot register after the time
  frame has elapsed.
  If someone registers before the time frame, that person will be placed on the
  waiting list. Once the time frame arrives the person will be automatically
  enrolled as long as other rules are satisfied.

  Attributes:
    start_time: Datetime at which people can start registering.
    end_time: Datetime after which people cannot register any more.
    access_point_tags: List of access point tags for this rule.
  """

  def __init__(self, start_time, end_time, access_point_tags=None,
               *args, **kargs):
    super(TimeFrameRegistrationByAccessPointTag, self).__init__(*args, **kargs)
    self.start_time = datetime.datetime.fromtimestamp(start_time)
    self.end_time = datetime.datetime.fromtimestamp(end_time)
    self.access_point_tags = access_point_tags

  def Evaluate(self, initial_state, target_state):
    """Overrides parent method."""
    if target_state == utils.RegistrationStatus.ENROLLED:
      ap_keys = [ap.key() for ap in self.eval_context.access_point_list]
      aps = _GetRelevantAccessPointKeys(ap_keys, self.access_point_tags)

      if aps:
        # this rule applies
        return {'status': _CanRegisterTimeWindows(initial_state,
                                                  self.eval_context.queue_time,
                                                  self.start_time,
                                                  self.end_time)}

    return {'status': target_state}

  @classmethod
  def GetDescription(cls):
    return _('Registration window for attending location.')


class TimeCancelByActivity(rules.RuleRegister):
  """Enforces a time limit for late registration cancels by activity.

  This rule enforces a time limit after which users will not be able to
  unregister from a particular activity.

  Attributes:
    time_to_activity: Time in seconds until activity starts.
  """

  def __init__(self, time_to_activity, *args, **kargs):
    super(TimeCancelByActivity, self).__init__(*args, **kargs)
    self.time_to_activity = time_to_activity

  def Evaluate(self, initial_state, target_state):
    """Overrides parent method."""
    if (target_state == utils.RegistrationStatus.UNREGISTERED
        and initial_state == utils.RegistrationStatus.ENROLLED):
      # It is OK to use local time with mktime as long as all datetimes are in
      # the same timezone.
      start_time = self.eval_context.activity.start_time
      activity_start = time.mktime(start_time.timetuple())
      deadline = activity_start - self.time_to_activity
      if time.mktime(self.eval_context.queue_time.timetuple()) < deadline:
        return {'status': utils.RegistrationStatus.UNREGISTERED}
      else:
        return {'status': initial_state}

    # this rule does not apply
    return {'status': target_state}

  @classmethod
  def GetDescription(cls):
    return _('Unregister deadline.')


class ManagerApproval(rules.RuleRegister):
  """Enforces students to require manager approval before attending a course."""

  def __init__(self, *args, **kargs):
    super(ManagerApproval, self).__init__(*args, **kargs)
    self._check_and_create_approval = False

  def _GetRuleTag(self):
    return '%s_%s_%s' % (self.key, self.eval_context.activity.key(),
                         self.eval_context.user.appengine_user)

  def _GetUserManager(self):
    """Gets the manager users.User object of the registering user."""
    if not appenginepatcher.on_production_server:
      # In dev mode user is her own manager. Change it to another user to
      # test. Else registration will go preapproved. No workflow.
      return self.eval_context.user.appengine_user

    if not hasattr(self, '_manager'):
      student_email = self.eval_context.user.appengine_user.email()
      user_service = service_factory.GetUserInfoService()
      manager_info = user_service.GetManagerInfo(student_email)
      if manager_info is None:
        self._manager = None
      else:
        self._manager = utils.GetAppEngineUser(manager_info.primary_email)

    return self._manager

  def _IsPreApproved(self):
    try:
      # Check if manager is trying to enroll the user through batch enrollment.
      return self._GetUserManager() == self.eval_context.creator.appengine_user
      # Suppress pylint catch Exception
      # pylint: disable-msg=W0703
    except errors.ServiceCriticalError, exception:
      logging.error('[%s] %s', type(exception), exception)
      assert self.online  # We dont fail online, just assume, not pre approved.
    return False

  def _IsPreDeclined(self):
    try:
      return self._GetUserManager() is None  # Dont know person or her manager.
      # Suppress pylint catch Exception
      # pylint: disable-msg=W0703
    except errors.ServiceCriticalError, exception:
      if not self.online:
        # We dont fail online, just assume, not disapproved.
        raise exception
    return False

  def _GetApprovalKey(self):
    """Key to be used on the approval object."""
    return db.Key.from_path(models.ManagerApproval.kind(),
                            self._GetRuleTag())

  def _GetUsableApproval(self):
    approval_key = self._GetApprovalKey()
    approval = request_cache.GetEntityFromKey(approval_key)
    if approval is not None:
      time_diff = abs(approval.queue_time - self.eval_context.queue_time)
      allow_delta = datetime.timedelta(seconds=1)
      if not approval.approved and time_diff >= allow_delta:
        # Allows user to re-ask approval if denied previously.
        approval = None  # Dont use the approval object.
    return approval

  def _CheckAndInitiateApprovalProcess(self):
    """Initiates approval process if necessary."""
    approval = self._GetUsableApproval()
    if approval is None:
      # Send email to manager to approve user request.
      dummy_registration = models.UserRegistration(
          eval_context=self.eval_context,
          status=utils.RegistrationStatus.WAITLISTED,
          confirmed=utils.RegistrationConfirm.PROCESSED,
          active=utils.RegistrationActive.ACTIVE)
      notifications.SendMail(
          dummy_registration,
          notifications.NotificationType.MANAGER_APPROVAL_REQUEST,
          to=self._GetUserManager().email(),
          cc=self.eval_context.user.appengine_user.email(),
          extra_context={'approval_key': str(self._GetApprovalKey())})

      # Write an approval entity to datastore.
      approval_entity = models.ManagerApproval(
          key_name=self._GetRuleTag(),
          candidate=self.eval_context.user.appengine_user,
          manager=self._GetUserManager(),
          activity=self.eval_context.activity.key(),
          program=self.eval_context.program.key(),
          nominator=self.eval_context.creator.appengine_user,
          approved=False,
          manager_decision=False,
          queue_time=self.eval_context.queue_time,
      )
      approval_entity.put()

  def Evaluate(self, unused_initial_state, target_state):
    """Overrides parent method."""
    if rules.IsPredictionMode():
      return {'status': target_state, 'rule_tags': [self.key]}

    return_status = target_state  # By default accept transition.
    rule_tag = None

    if target_state == utils.RegistrationStatus.ENROLLED:
      if self._IsPreDeclined():
        return_status = None  # Non google.com account or no manager.
      elif not self._IsPreApproved():
        rule_tag = self._GetRuleTag()
        approval = self._GetUsableApproval()
        if approval is None:  # No usable approval, workflow to be initiated.
          return_status = utils.RegistrationStatus.WAITLISTED
          self._check_and_create_approval = True
        elif not approval.manager_decision:  # Manager did not decide.
          return_status = utils.RegistrationStatus.WAITLISTED
        elif not approval.approved:  # Manager decided and declined.
          return_status = None

    rule_tags = [self.key]
    if rule_tag is not None:
      rule_tags.append(rule_tag)
    return {'status': return_status, 'rule_tags': rule_tags}

  def ProcessOutcome(self, eval_state, final_state):
    """Process the result of rule evaluation to manage rule state."""
    if self.online: return  # Nothing to do during online mode.

    if (final_state == utils.RegistrationStatus.WAITLISTED and
        self._check_and_create_approval):
      assert eval_state == utils.RegistrationStatus.WAITLISTED
      # Initiate the manager approval workflow.
      self._CheckAndInitiateApprovalProcess()

  # Suppress pylint unused argument for overriden method
  # pylint: disable-msg=W0613
  @classmethod
  def TagsToReprocessOnChange(cls, rule_config, program_or_activity=None):
    """Overrides parent method."""
    return [rule_config.key]

  @classmethod
  def GetDescription(cls):
    return _('Needs manager approval.')


class TimeCancelByAccessPointTag(rules.RuleRegister):
  """Enforces a time limit for late registration cancels by access point tag.

  This rule enforces a time limit after which users will not be able to
  unregister from a particular access point tag.

  Attributes:
    time_to_activity: Time in seconds until activity starts.
    access_point_tags: List of access point tags for this rule.

  Example:
      TimeCancelByAccessPointTag(3600) will allow users to unregister until up
      to 1 hour before the activity starts.
  """

  def __init__(self, time_to_activity, access_point_tags=None,
               *args, **kargs):
    super(TimeCancelByAccessPointTag, self).__init__(*args, **kargs)
    self.time_to_activity = time_to_activity
    self.access_point_tags = access_point_tags

  def Evaluate(self, initial_state, target_state):
    """Overrides parent method."""
    if (target_state == utils.RegistrationStatus.UNREGISTERED
        and initial_state == utils.RegistrationStatus.ENROLLED):

      ap_keys = [ap.key() for ap in self.eval_context.access_point_list]
      aps = _GetRelevantAccessPointKeys(ap_keys, self.access_point_tags)

      if aps:
        # this rule applies
        start_time = self.eval_context.activity.start_time
        activity_start = time.mktime(start_time.timetuple())
        deadline = activity_start - self.time_to_activity
        if  time.mktime(self.eval_context.queue_time.timetuple()) < deadline:
          return {'status': utils.RegistrationStatus.UNREGISTERED}
        else:
          return {'status': initial_state}

    # this rule does not apply
    return {'status': target_state}

  @classmethod
  def GetDescription(cls):
    return _('Unregister deadline for attending location type.')


class EmployeeTypeRestriction(rules.RuleRegister):
  """Restricts enrollment based on employee type.

  Attributes:
    employee_types: List of utils.EmployeeType.XXX choices.
  """

  def __init__(self, employee_types,
               *args, **kargs):
    super(EmployeeTypeRestriction, self).__init__(*args, **kargs)
    self.employee_types = employee_types

  # Supress pylint unused argument, overriding parent method
  # pylint: disable-msg=W0613
  def Evaluate(self, initial_state, target_state):
    """Overrides parent method."""
    if target_state == STATUS.ENROLLED:
      # Retrieve employee type from user service
      exception = None
      person = None
      email = self.eval_context.user.email
      try:
        user_service = service_factory.GetUserInfoService()
        person = user_service.GetUserInfoMulti([email]).get(email)
        # Suppress pylint catch Exception
        # pylint: disable-msg=W0703
      except errors.ServiceCriticalError, exception:
        logging.error('[%s] %s', type(exception), exception)

      # In dev we just let the user to be enrolled. (No user service in dev).
      if not appenginepatcher.on_production_server:
        return {'status': STATUS.ENROLLED}

      if exception is not None:  # Prod user info service problems.
        if self.online:  # Production online case, we waitlist.
          return {'status': STATUS.WAITLISTED}
        # Production offline case, we raise exception.
        logging.info('User[%s] lookup failed', email)
        raise exception

      # Prod mode, no exception and didn't find user using user hr service.
      if person is None:
        logging.info('Can not lookup user [%s]',
                     self.eval_context.user)
        return {'status': None}  # Not allowed if cannot lookup user.

      logging.info('Person type for %s is %s, allowing only %s',
                   email, person.employee_type, self.employee_types)
      if person.employee_type in self.employee_types:
        return {'status': STATUS.ENROLLED}
      # Not allowed.

      return {'status': None}

    # this rule does not apply
    return {'status': target_state}

  @classmethod
  def GetDescription(cls):
    return _('Restricted by employee types.')


def _UpdateQueryMode(query, offline):
  """Updates a query filters based on offline mode.

  Args:
    query: The query to be updated.
    offline: A boolean to indicate offline mode.

  Returns:
    A list of queries that give the relevant registrations
  """
  if offline:
    query.filter('status =', utils.RegistrationStatus.ENROLLED)
    query.filter('confirmed =', utils.RegistrationConfirm.PROCESSED)

  return query


def _RegistrationNeedsAccounting(reg, offline):
  """Returns True if the given registration needs to be accounted.

  This method can further filter the registrations that are relevant to a query
  in memory. Can be used for filtering that aren't easy to make on the datastore
  and are best done in memory. For completeness of the function though the logic
  in _UpdateQueryMode is also replicated to have this function usable on its own
  even without filtering at the datastore query level.

  Args:
    reg: User registration
    offline: A Boolean to indicate offline mode

  Returns:
    True if the given user registration needs to be taken into account when
    building a context.
  """
  if offline:
    return (reg.status == utils.RegistrationStatus.ENROLLED and
            reg.confirmed == utils.RegistrationConfirm.PROCESSED)
  else:
    res1 = reg.active == utils.RegistrationActive.ACTIVE

    # Count registrations in transition/temporary state.
    res2 = (reg.status == utils.RegistrationStatus.ENROLLED and
            reg.confirmed == utils.RegistrationConfirm.NOT_READY)

    # Count unregistrations that aren't yet processed by offline process. Count
    # registrations that are not active anymore since unregisterOnline has
    # marked them inactive. These take up resources until the offline process
    # deletes the whole register-unregister entity group.
    res3 = (reg.status == utils.RegistrationStatus.UNREGISTERED and
            reg.confirmed == utils.RegistrationConfirm.READY)

    return res1 or res2 or res3


def _CanRegisterTimeWindows(initial_state, queue_time, start_time, end_time):
  """Checks if user is allowed to register based on given time window.

  If a user tries to register before the time window opens, the user is placed
  on the waiting list.

  Args:
    initial_state: Initial state of user when registering.
    queue_time: Datetime of the user request.
    start_time: Datetime date of registration window.
    end_time: Datetime end of registration window.

  Returns:
    A rules.RuleResultRegister.STATUS_XXX value or initial_state if outside
     time window.
  """
  if queue_time > start_time and queue_time < end_time:
    value = utils.RegistrationStatus.ENROLLED
  else:
    format = '%Y-%m-%d %I:%M%p'
    logging.debug('Can not register in time window [%s - %s] for queue time %s',
                  start_time.strftime(format), end_time.strftime(format),
                  queue_time.strftime(format))
    value = initial_state
  return value


def _GetAccessPointsWithTags(access_point_tags):
  """Returns access points which contain every tag from the input.

  Args:
    access_point_tags:
      A list of strings representing access point tags, with a maximum of 30
      entries.

  Returns:
    An iterator of AccessPoint such that every AccessPoint contains all the tags
    specified in access_point_tags.
  """
  query = models.AccessPoint.all()
  for tag in access_point_tags:
    # We need access points which have EVERY tag from access_point_tags.
    # The IN <list> clause in appengine returns entries which have ANY of the
    # tags in the <list>. So we need to build multiple IN clauses to get a full
    # match.
    query.filter('tags in ', [tag])
  return query


class LockPastActivity(rules.RuleRegister):
  """Locks registrations for activities in the past."""

  def __init__(self, *args, **kargs):
    super(LockPastActivity, self).__init__(*args, **kargs)

  def Evaluate(self, initial_state, target_state):
    """Overrides parent method."""
    if self.online:  # Only operate on online mode, accept everything offline.
      lock_time = self.eval_context.activity.start_time
      if self.eval_context.queue_time > lock_time:
        return {'status': initial_state}  # Deny any state changes.

    return {'status': target_state}  # Accept transition.

  @classmethod
  def GetDescription(cls):
    return _('Registrations locked for past activities.')
