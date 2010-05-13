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


"""Utility class to manage notifications."""



import settings

from django import template
from django.template import loader
from django.utils import translation
from google.appengine.api import mail
from google.appengine.ext import db

from core import models
from core import utils

_ = translation.ugettext


class NotificationType(utils.RegistrationStatus):
  """Different types of user notifications.

  Attributes:
    ENROLL_REJECTED: An enroll request can get rejected if for example an online
      contention leads to a WAITING state, but the offline rule does not allow
      WAITING on an activity.
      Another example could be an activity which freezes ENROLLED list 24 hours
      before activity start, and rejects all WAITING.
    REMINDER: Used to send email reminders as activity schedule approaches.
    MANAGER_APPROVAL_REQUEST: Notification to manager that approval for a user
      is required before joining a course.
    REGISTRATION_UPDATE: Used when the registration has been updated.
  """

  ENROLL_REJECTED = 'enroll_rejected'
  REMINDER = 'reminder'
  MANAGER_APPROVAL_REQUEST = 'manager_approval_request'
  REGISTRATION_UPDATE = 'update'


def SendMail(user_registration, notification_type, to=None,
             reply_to=None, cc=None, bcc=None, extra_context=None):
  """Sends mail about a particular event.

  Args:
    user_registration: The models.UserRegistration for which we need to send the
        latest email notification.
    notification_type: A NotificationType.
    to: An optinoal string address override to send notification email to.
    reply_to: An optional string for the reply-to address.
    cc: An optional string or list of string for emails to be cc-ed.
    bcc: An optional string or list of string for emails to be bcc-ed.
    extra_context: A dict to pass in extra context to the email templates. The
        context passed to the templates is updated with this dict.
  """
  bcc = bcc or []
  cc = cc or []
  # Get contact list users.
  contact_list = user_registration.program.contact_list
  if contact_list:
    reply_to = reply_to or contact_list[0].email()
  to = to or user_registration.user.email()

  datastore_user = models.GlearnUser.FromAppengineUser(user_registration.user)
  access_points = db.get(user_registration.access_point_list)
  schedules = db.get(user_registration.schedule_list)

  # Get locations and times.
  locations_and_times = []
  for access_point, schedule in zip(access_points, schedules):
    locations_and_times.append({
        'start_time_local': datastore_user.GetLocalTime(schedule.start_time),
        'location': access_point.uri})
  locations_and_times = sorted(locations_and_times,
                               key=lambda x: x['start_time_local'])

  # Get possible reasons for status.
  status_reasons = [_(str(cfg.GetDescription()))
                    for cfg in user_registration.affecting_rule_configs]

  context_values = {'register': user_registration,
                    'locations_and_times': locations_and_times,
                    'hostname': settings.DATABASE_OPTIONS['remote_host'],
                    'contact_list': contact_list,
                    'status_reasons': status_reasons}

  # Add extra_context to the template context.
  extra_context = extra_context or {}
  context_values.update(extra_context)

  if notification_type == NotificationType.ENROLLED:
    template_name = 'email_enroll.html'
    subject = _('Registration confirmation: %s')
  elif notification_type == NotificationType.REGISTRATION_UPDATE:
    template_name = 'email_registration_update.html'
    subject = _('Updated activity: %s')
  elif notification_type == NotificationType.ENROLL_REJECTED:
    template_name = 'email_enroll_rejected.html'
    if user_registration.creator != user_registration.user:
      # The registration was rejected and was initiated by somebody else.
      # We send the email to the person who initiated the registration, not
      # to the user who wasn't allowed to register, to notify the person who
      # attempted this action of failure.
      to = user_registration.creator.email()
    subject = _('Sign-up denied: %s')
  elif notification_type == NotificationType.WAITLISTED:
    # Determine if the user is waiting only for max people in activity rule.
    if user_registration.OnlyWaitingForMaxPeopleActivity():
      template_name = 'email_waitlisted.html'
      subject = _('Waitlist notification: %s')

      context_values['rank'] = models.UserRegistration.WaitlistRankForUser(
          user_registration.activity, user_registration.user)
      context_values['capacity'] = user_registration.activity.MaxCapacity()
    else:
      # Waitlisted, but rules other than max rule are also in play.
      # Mention to user that registration is pending and give reasons.
      template_name = 'email_pending.html'
      subject = _('Enroll request pending: %s')
  elif notification_type == NotificationType.UNREGISTERED:
    if not user_registration.activity.to_be_deleted:
      # Ordinary unregistration.
      subject = _('Cancellation confirmation: %s')
    else:  # Special system unregistration.
      subject = _('Unregistered due to session cancellation: %s')
    template_name = 'email_unregister.html'
  elif notification_type == NotificationType.MANAGER_APPROVAL_REQUEST:
    template_name = 'email_manager_approval.html'
    subject = _('Approval required for %s to attend %s')
    subject %= (user_registration.user.nickname(), '%s')
  else:
    assert False
  subject %= user_registration.program.name

  context = template.Context(context_values)
  body = loader.render_to_string(template_name,
                                 context_instance=context)

  message = mail.EmailMessage(sender=settings.ADMIN_EMAIL)
  message.to = to
  message.body = body
  message.html = body
  if cc: message.cc = cc
  if bcc: message.bcc = bcc
  if reply_to: message.reply_to = reply_to
  message.subject = subject

  message.send()
