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


"""The forms presented for editing/creating model entities."""



# Supress pylint invalid import order
# pylint: disable-msg=C6203

import copy
import datetime
import logging
import time

from django import forms
from django.forms import formsets
from django.forms import  util as form_util
from django.utils import encoding
from django.utils import safestring
from django.utils import translation
from google.appengine.api import users
from google.appengine.ext import db
from google.appengine.ext import deferred


import settings
from core import models
from core import rule_engine
from core import rules
from core import timezone_helper
from core import utils

_ = translation.ugettext

# Department constants.
_DEPARTMENTS_TAGS = [c[0] for c in settings.FORM_DEPARTMENT_CHOICES]
_DEPARTMENT_DISPLAY = [_(c[1]) for c in settings.FORM_DEPARTMENT_CHOICES]
DEPARTMENT_CHOICES = [('', 'Choose a department')]
DEPARTMENT_CHOICES.extend(zip(_DEPARTMENTS_TAGS, _DEPARTMENT_DISPLAY))
DEPARTMENT_CHOICES_MAP = dict(zip(_DEPARTMENTS_TAGS, _DEPARTMENT_DISPLAY))

# Activity type constants.
_TYPES_TAG = ['instructor-led', 'video', 'webinar', 'quizz']
_TYPES_DISPLAY = [_('In-person'), _('Video'), _('Virtual classroom/webinar'),
                  _('Assesment or test')]
TYPE_CHOICES = zip(_TYPES_TAG, _TYPES_DISPLAY)
TYPE_CHOICES_MAP = dict(TYPE_CHOICES)

# Difficulty level constants.
_LEVEL_TAGS = ['introductory', 'moderate', 'advanced']
_LEVELS_DISPLAY = [_('Introductory'), _('Moderate'), _('Advanced')]
LEVEL_CHOICES = [('', _('Choose difficulty level'))]
LEVEL_CHOICES.extend(zip(_LEVEL_TAGS, _LEVELS_DISPLAY))
LEVEL_CHOICES_MAP = dict(LEVEL_CHOICES)

# Form error messages.
_INVALID_MSG_START_DATE = _('Enter a valid start date.')
_INVALID_MSG_START_TIME = _('Enter a valid start time.')
_INVALID_MSG_END_DATE = _('Enter a valid end date.')
_INVALID_MSG_END_TIME = _('Enter a valid end time.')
_MIN_LENGTH_MSG = _('Please be more descriptive.')
_REQUIRED_MSG_START_DATE = _('Start date is required.')
_REQUIRED_MSG_START_TIME = _('Start time is required.')
_REQUIRED_MSG_END_DATE = _('End date is required.')
_REQUIRED_MSG_END_TIME = _('End time is required.')

_PROGRAM_NAME_LOCK = 'program_first_write'  # Lock prefix for program write.


class SimpleRadioFieldRenderer(forms.widgets.RadioFieldRenderer):
  """Overriding the default rendering of django radio select widget.

  The default radio select widget creates the options as an unordered html list,
  this class overrides this behavior and places all of them in the same line.
  """

  def render(self):
    """Override base implementation. Called to generate widget html."""
    # Supress invalid method name, since overriding base class method.
    # pylint: disable-msg=C6409
    return safestring.mark_safe(
        u'\n'.join([encoding.force_unicode(w) for w in self])
    )


# Suppress pylint no explicit inheritance from base object
# pylint: disable-msg=C6601
# Suppress pylint use of super on old style class
# pylint: disable-msg=E1002


class SettingsForm(forms.Form):
  """Creates a form for user settings.

  Attributes:
    timezone: User timezone.
    location: User city location code ex:'us-mtv'
  """

  location = forms.ChoiceField(choices=(),
                               required=True, label=_('City location'))

  def __init__(self, *args, **kwargs):
    super(SettingsForm, self).__init__(*args, **kwargs)

    locations = timezone_helper.GetLocationCodes()
    locations_display = []
    for loc in locations:
      display = '%s (%s)' % (loc, timezone_helper.GetTimezoneForLocation(loc))
      locations_display.append(display)

    self.fields['location'].choices = zip(locations, locations_display)

  def UpdateSettings(self, user):
    """Updates user settings.

    Args:
      user: The models.GlearnUser who is using creating the program.
    """
    data = self.cleaned_data
    timezone = timezone_helper.GetTimezoneForLocation(data['location'])
    user.timezone = utils.Timezone(timezone)
    user.location = data['location']
    user.put()

  @staticmethod
  def BuildPostData(user):
    """Create the post data to seed the form from an existing user."""
    post_data = {}
    post_data['location'] = user.location
    return post_data


class ProgramForm(forms.Form):
  """Form used to create and edit a program.

  This form is used to collect property values for a models.Program object.

  Attributes:
    name: The string value corresponding to Program.name
    instruction_type: The string choice of instruction type of the program.
      Stored in Program.program_tags.
    contact_person: Comma separated list of people associated with this
      program.
    facilitators: Comma separated list of people who help set up the program.
    description: Hidden form field which stores program description.
    level: The string choice of level of difficulty of the program. Stored in
      Program.program_tags.
    department: The string department choice of which department this course is
      aimed for. Stored in Program.program_tags.
    allow_employee: Boolean indicating if an employee can attend the program.
    allow_intern: Boolean indicating if an intern can attend the program.
    allow_contractor: Boolean indicating if a contractor can attend the program.
    allow_vendor: Boolean indicating if a vendor can attend the program.
  """

  name = forms.CharField(widget=forms.TextInput(attrs={'size': 30}),
                         label=_('Title'))
  instruction_type = forms.ChoiceField(
      widget=forms.RadioSelect(renderer=SimpleRadioFieldRenderer),
      choices=TYPE_CHOICES, required=True,
      label=_('Activity type')
  )
  # The description field is hidden
  # Editor is used as helper for field content
  description = forms.CharField(widget=forms.HiddenInput(),
                                # Init with space otherwise some focus alignment
                                # issue with editor widget
                                initial=_('&nbsp;'),
                                min_length=10, label=_('Description'),
                                error_messages={'min_length': _MIN_LENGTH_MSG})
  level = forms.ChoiceField(choices=LEVEL_CHOICES, initial='', required=False,
                            label=_('Difficulty'))
  department = forms.ChoiceField(choices=DEPARTMENT_CHOICES, initial='',
                                 required=True, label=_('Offered by'))
  allow_employee = forms.BooleanField(initial=True,
                                      label=utils.EmployeeType.DISPLAY_MAP[
                                          utils.EmployeeType.EMPLOYEE],
                                      required=False)
  allow_intern = forms.BooleanField(initial=True,
                                    label=utils.EmployeeType.DISPLAY_MAP[
                                        utils.EmployeeType.INTERN],
                                    required=False)
  allow_contractor = forms.BooleanField(
      label=utils.EmployeeType.DISPLAY_MAP[utils.EmployeeType.CONTRACTOR],
      required=False)
  allow_vendor = forms.BooleanField(
      label=utils.EmployeeType.DISPLAY_MAP[utils.EmployeeType.VENDOR],
      required=False)
  allow_all = forms.BooleanField(label=_('None, allow everyone.'),
                                 required=False)
  contact_person = forms.CharField(widget=forms.TextInput(attrs={'size': 30}),
                                   label=_('Contact'), required=True)
  facilitator = forms.CharField(widget=forms.TextInput(attrs={'size': 30}),
                                label=_('Owners'), required=True)
  manager_approval = forms.BooleanField(
      label=_('Manager approval'), required=False)
  public_activity_creation = forms.BooleanField(
      label=_('Shared activity'), required=False)
  visible = forms.BooleanField(initial=True, label=_('Visible'),
                               required=False)

  def CreateOrUpdateProgram(self, current_user, program=None):
    """Creates or updates the program in the datastore from form data.

    This function should be called after the form validates the data format. The
    input data is used to construct or update the program properties and the
    entity is written to the datastore. Model specific checks are also performed
    before writing out the entity.

    Args:
      current_user: The user who is using ProgramForm to create the program.
      program: The program that needs to be updated with form data. If None then
          program doesn't exist and a new program needs to be created.

    Returns:
      The created program model object or None if data is invalid.
    """
    data = self.cleaned_data

    name = data['name'].strip()

    description = data['description'].strip()

    email_list = data['contact_person'].strip().split(',')
    contact_list = [utils.GetAppEngineUser(e.strip()) for e in email_list
                    if e.strip()]

    email_list = data['facilitator'].strip().split(',')
    facilitator_list = [utils.GetAppEngineUser(e.strip()) for e in email_list
                        if e.strip()]

    if not name:
      msg = [_('Invalid title')]
      self._errors['name'] = form_util.ValidationError(msg).messages

    if not contact_list or len(contact_list) > 1 or None in contact_list:
      msg = [_('Invalid email')]
      self._errors['contact_person'] = form_util.ValidationError(msg).messages

    if not facilitator_list or None in facilitator_list:
      msg = [_('Invalid emails')]
      self._errors['facilitator'] = form_util.ValidationError(msg).messages

    program_tags = []
    if data['instruction_type']: program_tags.append(data['instruction_type'])

    if data['level']: program_tags.append(data['level'])
    if data['department']: program_tags.append(data['department'])

    restrictions = []
    if data['allow_employee']:
      restrictions.append(utils.EmployeeType.EMPLOYEE)
    if data['allow_intern']: restrictions.append(utils.EmployeeType.INTERN)
    if data['allow_contractor']:
      restrictions.append(utils.EmployeeType.CONTRACTOR)
    if data['allow_vendor']: restrictions.append(utils.EmployeeType.VENDOR)

    program_rules = []

    if not data['allow_all']:  # Allow all not checked.
      if not restrictions:
        # At least one restriction should be selected.
        msg = [_('This field is required')]
        self._errors['allow_employee'] = form_util.ValidationError(msg).messages
      else:
        program_tags.extend(restrictions)
        # Employee restriction rule.
        program_rules.append(rules.RuleConfig(
            rules.RuleNames.EMPLOYEE_TYPE_RESTRICTION,
            {'employee_types': restrictions}))
    else:
      if restrictions:
        # Allow all and restrictions cannot be selected together.
        msg = [_('Cannot select restrictions when allowing everyone.')]
        self._errors['allow_employee'] = form_util.ValidationError(msg).messages

    if self._errors:
      return None

    # Manager approval rule.
    if data['manager_approval']:
      program_rules.append(rules.RuleConfig(
          rules.RuleNames.MANAGER_APPROVAL, {}))

    # Dont allow users to change activity registrations past the activity.
    program_rules.append(rules.RuleConfig(
        rules.RuleNames.LOCK_PAST_ACTIVITY, {}))

    public_activity_creation = data.get('public_activity_creation', False)
    visible = data.get('visible', True)

    properties = {
        'name': name,
        'description': description,
        'contact_list': contact_list,
        'facilitator_list': facilitator_list,
        'last_modified_by': current_user,
        'program_tags': program_tags,
        'rules': program_rules,
        'public_activity_creation': public_activity_creation,
        'visible': int(visible)
    }

    def UpdateProgramUnsafe(program_key):
      """Update existing program in a transaction."""
      program = db.get(program_key)
      if program.deleted or program.to_be_deleted:
        msg = [_('Cannot edit deleted or to be deleted activity.')]
        self._errors['name'] = form_util.ValidationError(msg).messages
        return None

      rule_engine.UpdateProgramOrActivityRules(
          program, properties.pop('rules'))
      for attribute, value in properties.items():
        setattr(program, attribute, value)

      program.put()
      return program

    if program is not None:
      return db.run_in_transaction(UpdateProgramUnsafe, program.key())
    else:
      properties['owner'] = current_user
      program = models.Program(**properties)
      program.put()
      return program

  @staticmethod
  def BuildPostData(program):
    """Create the post data to seed the form from an existing program."""
    post_data = {}
    post_data['name'] = program.name
    post_data['description'] = program.description

    program_tags = program.program_tags

    def AddTagChoices(field_name, choices):
      for choice in choices:
        if choice in program_tags:
          post_data[field_name] = choice
          break

    AddTagChoices('level', _LEVEL_TAGS)
    AddTagChoices('department', _DEPARTMENTS_TAGS)
    AddTagChoices('instruction_type', _TYPES_TAG)

    def AddBooleanChoice(tag_name, field_name):
      if tag_name in program_tags:
        post_data[field_name] = True
        return True
      return False

    employee_type_restriction = False
    if AddBooleanChoice(utils.EmployeeType.EMPLOYEE, 'allow_employee'):
      employee_type_restriction = True
    if AddBooleanChoice(utils.EmployeeType.INTERN, 'allow_intern'):
      employee_type_restriction = True
    if AddBooleanChoice(utils.EmployeeType.CONTRACTOR, 'allow_contractor'):
      employee_type_restriction = True
    if AddBooleanChoice(utils.EmployeeType.VENDOR, 'allow_vendor'):
      employee_type_restriction = True

    if not employee_type_restriction:
      post_data['allow_all'] = True

    if program.GetRule(rules.RuleNames.MANAGER_APPROVAL) is not None:
      post_data['manager_approval'] = True

    post_data['public_activity_creation'] = program.public_activity_creation
    post_data['visible'] = program.visible

    emails = ','.join([contact.nickname() for contact in program.contact_list])
    post_data['contact_person'] = emails
    emails = ','.join([contact.nickname()
                       for contact in program.facilitator_list])
    post_data['facilitator'] = emails

    return post_data


class ActivityScheduleForm(forms.Form):
  """Form used to create and edit an activity schedule and associated activity.

  This form is used to collect property values for a models.ActivitySchedule.
  It is to be used with formsets.

  Attributes:
    max_people: Max number of people who can register.
      Applies at the activity level, not schedule level.
    register_end_date: Last date for registration.
      Applies at the activity level, not schedule level.
    register_end_time: Last time for registration.
      Applies at the activity level, not schedule level.
    reserve_rooms: Bool that indicates if we need to reserve conference rooms.
    visible: Boolean indicating if the activity is visible for users.
    start_date: Schedule start_date.
    start_time: Schedule start_time.
    end_date: Schedule end_date.
    end_time: Schedule end_time.
    access_points: Comma separated access point keys.
    access_points_secondary: Comma separated access point keys for secondary
      locations.
    vc_bridge: VideoConference number.
    instructors: Comma separated list of instructor usernames/emails.
    notes: Notes for this schedule.
    schedule_key: Optional schedule's key to identify the schedule that needs to
      be updated. If None, a new schedule will be created.
  """

  def __init__(self, *args, **kwargs):
    super(ActivityScheduleForm, self).__init__(*args, **kwargs)
    self.access_points_cache = {}

  max_people = forms.IntegerField(min_value=1, initial='', required=False,
                                  label=_('Maximum registration'))

  register_end_date = forms.DateField(
      widget=forms.TextInput(attrs={'size': 10}),
      required=False, label=_('Registration deadline'))

  register_end_time = forms.TimeField(
      widget=forms.TextInput(attrs={'size': 8}),
      required=False, input_formats=('%H:%M', '%I:%M%p',))

  reserve_rooms = forms.BooleanField(initial=False, required=False,
                                     label=_('Reserve rooms'))
  visible = forms.BooleanField(initial=True, label=_('Visible'),
                               required=False)

  start_date = forms.DateField(
      widget=forms.TextInput(attrs={'size': 10}), required=True,
      label=_('When'), error_messages={'required': _REQUIRED_MSG_START_DATE,
                                       'invalid': _INVALID_MSG_START_DATE})

  start_time = forms.TimeField(
      widget=forms.TextInput(attrs={'size': 8}),
      input_formats=('%H:%M', '%I:%M%p',), required=True,
      error_messages={'required': _REQUIRED_MSG_START_TIME,
                      'invalid': _INVALID_MSG_START_TIME})

  end_date = forms.DateField(
      widget=forms.TextInput(attrs={'size': 10}), required=True, label=_('to'),
      error_messages={'required': _REQUIRED_MSG_END_DATE,
                      'invalid': _INVALID_MSG_END_DATE})

  end_time = forms.TimeField(
      widget=forms.TextInput(attrs={'size': 8}),
      input_formats=('%H:%M', '%I:%M%p',), required=True,
      error_messages={'required': _REQUIRED_MSG_END_TIME,
                      'invalid': _INVALID_MSG_END_TIME})

  access_points = forms.CharField(
      widget=forms.HiddenInput(), initial='',
      required=True, label=_('Primary location'),
  )
  access_points_secondary = forms.CharField(widget=forms.HiddenInput(),
                                            initial='', required=False,
                                            label=_('Other locations'))

  vc_bridge = forms.CharField(widget=forms.TextInput(attrs={'size': 25}),
                              required=False,
                              min_length=5, label=_('VC bridge'))

  instructors = forms.CharField(widget=forms.TextInput(attrs={'size': 25}),
                                required=True,
                                label=_('Instructors'))

  notes = forms.CharField(widget=forms.Textarea(attrs={'rows': 5, 'cols': 50}),
                          label=_('Notes'), required=False)

  schedule_key = forms.CharField(widget=forms.HiddenInput(), required=False)

  def IsDeleted(self):
    """Returns True if form is to be deleted."""
    field = self.fields[formsets.DELETION_FIELD_NAME]
    raw_value = self._raw_value(formsets.DELETION_FIELD_NAME)
    return field.clean(raw_value)

  def GetSchedule(self):
    """Returns the schedule associated with this form or None if new."""
    # We cache the schedule.
    if not hasattr(self, '_schedule'):
      field = self.fields['schedule_key']
      schedule_key = field.clean(self._raw_value('schedule_key'))
      if schedule_key:
        self._schedule = models.ActivitySchedule.get(schedule_key)
        self._schedule_copy = copy.copy(self._schedule)
      else:
        self._schedule = None

    return self._schedule

  def _GetUnmodifiedSchedule(self):
    if not self.GetSchedule():
      return None
    return self._schedule_copy

  def IntializeProperties(self, user, update_activity, activity=None,
                          program=None):
    """Initializes the activity and schedule properties from form data.

    This methods must be called before CreateOrUpdateXXX(). It performs
    validation of the form data.

    Args:
      user: The models.GlearnUser who originates this call.
      update_activity: Boolean. If True, the relevant activity will be
        created/updated.
      activity: The models.Activity for this schedule.
      program: The models.Program for this schedule.

    Returns:
      True if the form data is valid and successfully parsed, False otherwise.
      If False, the _errors dictionary is populated with errors to be shown to
      the end user.
    """
    assert activity or program
    if activity:
      program = activity.parent()

    if update_activity:
      self.__InitializeActivityProperties(user, program)

    if not self.IsDeleted():
      self.__InitializeScheduleProperties(program)

    if not self.IsDeleted() and self._errors:
      return False
    else:
      return True

  def __InitializeActivityProperties(self, user, program):
    """Initializes properties for the activity."""
    new_rules = []
    max_people_value = self._raw_value('max_people')
    max_people_value = self.fields['max_people'].clean(max_people_value)
    reserve_rooms_value = self._raw_value('reserve_rooms')
    reserve_rooms_value = self.fields['reserve_rooms'].clean(
        reserve_rooms_value)
    visible_value = self._raw_value('visible')
    visible_value = self.fields['visible'].clean(visible_value)
    register_end_date_value = self._raw_value('register_end_date')
    register_end_date_value = self.fields['register_end_date'].clean(
        register_end_date_value)
    register_end_time_value = self._raw_value('register_end_time')
    register_end_time_value = self.fields['register_end_time'].clean(
        register_end_time_value)

    # We only store max people information on the first form.
    if max_people_value:
      new_rules.append(rules.RuleConfig(
          rules.RuleNames.MAX_PEOPLE_ACTIVITY,
          {'max_people': max_people_value}))

    if register_end_date_value:
      register_end_date = register_end_date_value
      register_end_time = register_end_time_value
      if not register_end_time:
        register_end_time = datetime.time.min
      register_end_datetime = datetime.datetime.combine(
          register_end_date, register_end_time)
      seconds_to_epoch = time.mktime(
          user.GetUtcTime(register_end_datetime).timetuple())

      # Rule config with no restriction on start time and end time as specified.
      new_rules.append(rules.RuleConfig(
          rules.RuleNames.TIME_REGISTER_BY_ACTIVITY,
          {'start_time': time.mktime(datetime.datetime.min.timetuple()),
           'end_time': seconds_to_epoch}))
    elif register_end_time_value:
      msg = _('Register deadline time given without date')
      error_messages = form_util.ValidationError(msg).messages
      self._errors['register_end_time'] = error_messages

      return  # Stop processing.

    self.activity_properties = {'parent': program,
                                'name': program.name,
                                'program': program,
                                'last_modified_by': users.get_current_user(),
                                'rules': new_rules,
                                'owner': users.get_current_user(),
                                'reserve_rooms': reserve_rooms_value,
                                'visible': int(visible_value)}

  def __InitializeScheduleProperties(self, program):
    """Initializes the schedule properties."""
    data = self.cleaned_data

    access_points = []
    access_points_secondary = []
    if data['access_points']:
      access_points = data['access_points'].strip().split(',')
      access_points = [db.Key(ap.strip()) for ap in access_points]
    if data['access_points_secondary']:
      access_points_secondary = data['access_points_secondary']
      access_points_secondary = access_points_secondary.strip().split(',')
      access_points_secondary = [db.Key(ap.strip())
                                 for ap in access_points_secondary]

    if data['vc_bridge']:
      vc_ap = models.AccessPoint.GetAccessPointFromUri(data['vc_bridge'])

      if not vc_ap:
        # We create a new access point for this vc bridge
        vc_ap = models.AccessPoint(type=utils.AccessPointType.VC,
                                   uri=data['vc_bridge'],
                                   tags=[utils.AccessPointType.VC])
        vc_ap.put()

      access_points.append(vc_ap.key())

    inst_emails = [inst.strip() for inst in data['instructors'].split(',')
                   if inst.strip()]
    instructor_list = [utils.GetAppEngineUser(mail) for mail in inst_emails]

    if None in instructor_list:
      # Instructors are invalid, we cannot create the schedule object
      msg = [_('Invalid instructor(s)')]
      self._errors['instructors'] = form_util.ValidationError(msg).messages

    start_time = data['start_time']
    start_date = data['start_date']
    start_datetime = datetime.datetime.combine(start_date, start_time)

    end_time = data['end_time']
    end_date = data['end_date']
    end_datetime = datetime.datetime.combine(end_date, end_time)

    # Check start time is before end time
    if start_datetime >= end_datetime:
      msg = _('Date/Time out of order')
      self._errors['end_date'] = form_util.ValidationError(msg).messages

    # In case users are incorrect at this point we need to return
    # because we will not be able to instantiate new ActivitySchedule/Activity
    if self._errors:
      return

    access_point_tags = set()
    access_point_location_tags = set()

    for ap in models.AccessPoint.get(access_points+access_points_secondary):
      self.access_points_cache[ap.key()] = ap  # Cache for later use.
      access_point_tags.update(ap.tags)
      if ap.tags:
        access_point_location_tags.add(ap.tags[0])

    primary_access_point = self.access_points_cache[access_points[0]]
    schedule_properties = {
        'start_time': utils.GetUtcTime(start_datetime,
                                       primary_access_point.GetTimeZone()),
        'end_time': utils.GetUtcTime(end_datetime,
                                     primary_access_point.GetTimeZone()),
        'primary_instructors': instructor_list,
        'access_points': access_points,
        'access_points_secondary': access_points_secondary,
        'access_point_tags': list(access_point_tags),
        'access_point_location_tags': access_point_location_tags,
        'notes': data['notes'].strip(),
        'program': program,
        'last_modified_by': users.get_current_user(),
    }

    # We validate at the schedule level - not the form level.
    # We add transient owner for validation purposes. The owner is only avail.
    # in the first form of the ActivitySchedule formset in the current workflow.
    # So for validation purposes, we add dummy owner here.
    schedule_properties['owner'] = users.get_current_user()
    schedule = models.ActivitySchedule(**schedule_properties)
    # We remove transient owner
    schedule_properties.pop('owner')
    model_errors = schedule.ValidateInstance()

    if model_errors:
      for schedule_property, string_error_list in model_errors.items():
        validation_error = form_util.ValidationError(string_error_list)
        self._errors[schedule_property] = validation_error.messages
        return

    self.schedule_properties = schedule_properties

  def PrepareActivity(self, activity=None):
    """Creates or updates the activity in the datastore from form data.

    Args:
      activity: Optional models.Activity for this schedule to update. If None,
        the activity will be created.

    Returns:
      The updated/created models.Activity.
    """

    assert self.activity_properties
    if activity:
      activity = db.get(activity.key())
      assert not activity.deleted and not activity.to_be_deleted

      rule_engine.UpdateProgramOrActivityRules(
          activity, self.activity_properties.pop('rules'))

      # We update activity properties
      for attribute, value in self.activity_properties.items():
        if attribute != 'parent' and attribute != 'owner':
          setattr(activity, attribute, value)
    else:
      activity = models.Activity(**self.activity_properties)

    return activity

  def PrepareSchedule(self, activity):
    """Creates or updates the activity schedule in the datastore from form data.

    Args:
      activity: The models.Activity for this schedule.

    Returns:
      Tuple of (models.ActivitySchedule, models.ActivitySchedule). The first
          entity is the unsaved new schedule, the second is the old schedule
          previous to the updates done to by the form submit.
    """
    schedule = self.GetSchedule()

    if self.IsDeleted():
      # In case a user creates a new timeslot in the front end and deletes it,
      # then it is possible that it was never in the datastore to start with.
      return (None, schedule)

    assert self.schedule_properties

    # Update activity reference on schedule.
    self.schedule_properties['parent'] = activity
    # Update owner reference on schedule
    self.schedule_properties['owner'] = activity.owner

    if schedule:
      old_schedule = self._GetUnmodifiedSchedule()
      # Update existing schedule
      for attribute, value in self.schedule_properties.items():
        if attribute != 'parent':
          setattr(schedule, attribute, value)
      return (schedule, old_schedule)
    else:
      # Create a new schedule
      schedule = models.ActivitySchedule(**self.schedule_properties)
      return (schedule, None)

  @staticmethod
  def BuildPostData(user, schedule, index=-1):
    """Creates the post data to seed the form from an existing schedule.

    Args:
      user: models.GlearnUser editing the form.
      schedule: A models.ActivitySchedule.
      index: Optional index of the form if used within a formset.

    Returns:
      The POST data dictionary filled with values from the schedule.
    """
    if index != -1:
      prefix = 'form-' + str(index) + '-'
    else:
      prefix = ''
    post_data = {}

    aps = models.AccessPoint.GetAccessPointFromKeys(schedule.access_points)

    post_data[prefix+'schedule_key'] = schedule.key()

    start_time = utils.GetLocalTime(schedule.start_time, aps[0].GetTimeZone())
    end_time = utils.GetLocalTime(schedule.end_time, aps[0].GetTimeZone())
    post_data[prefix+'start_time'] = start_time
    post_data[prefix+'end_time'] = end_time
    # We break down the date/time for the SplitDateTimeWidget.
    # For some reason, the widget does not work with formsets when not breaking
    post_data[prefix+'start_date'] = start_time.strftime('%Y-%m-%d')
    post_data[prefix+'start_time'] = start_time.strftime('%I:%M%p')
    post_data[prefix+'end_date'] = end_time.strftime('%Y-%m-%d')
    post_data[prefix+'end_time'] = end_time.strftime('%I:%M%p')

    if index == 0:
      parent_activity = schedule.parent()
      for rule in parent_activity.rules:
        if rule.rule_name == rules.RuleNames.MAX_PEOPLE_ACTIVITY:
          post_data[prefix+'max_people'] = rule.parameters['max_people']
        elif rule.rule_name == rules.RuleNames.TIME_REGISTER_BY_ACTIVITY:
          register_end_datetime = datetime.datetime.fromtimestamp(
              rule.parameters['end_time'])
          register_end_datetime = user.GetLocalTime(register_end_datetime)
          register_end_date = register_end_datetime.strftime('%Y-%m-%d')
          register_end_time = register_end_datetime.strftime('%I:%M%p')
          post_data[prefix+'register_end_date'] = register_end_date
          post_data[prefix+'register_end_time'] = register_end_time

      post_data[prefix+'reserve_rooms'] = parent_activity.reserve_rooms
      post_data[prefix+'visible'] = parent_activity.visible

    access_points = []
    for ap in aps:
      if ap.type == utils.AccessPointType.VC:
        # The VC bridges are stored as primary access points - not secondary
        post_data[prefix+'vc_bridge'] = ap.uri
      elif ap.type == utils.AccessPointType.ROOM:
        access_points.append(str(ap.key()))
    post_data[prefix+'access_points'] = ','.join(access_points)
    ap_secondary = [str(ap) for ap in schedule.access_points_secondary]
    post_data[prefix+'access_points_secondary'] = ','.join(ap_secondary)

    instructor_list = [inst.nickname() for inst in schedule.primary_instructors]
    post_data[prefix+'instructors'] = ', '.join(instructor_list)
    if schedule.notes:
      post_data[prefix+'notes'] = schedule.notes

    return post_data


class ActivityScheduleFormSet(formsets.BaseFormSet):
  """Custom formset for ActivitySchedule."""

  # Invalid method name since we override django API.
  # pylint: disable-msg=C6409
  def add_fields(self, form, index):
    super(ActivityScheduleFormSet, self).add_fields(form, index)
    # Overriding the DELETE field to make it hidden
    name = formsets.DELETION_FIELD_NAME
    form.fields[name] = formsets.BooleanField(widget=forms.HiddenInput(),
                                              required=False)

  def __CreateUpdateSchedules(self, activity=None):
    """Create/Update schedules, to be run in a transaction.

    Args:
      activity: Activity to update. If None will create one.

    Returns:
      models.Activity that is created/updated.
    """
    first_form = True

    activity_to_be_created = not activity
    schedule_tuples = []
    access_points_cache = {}
    update_user_registrations = False
    notify_users = False
    for form in self.forms:
      if first_form:
        activity = form.PrepareActivity(activity)
        if activity_to_be_created:
          # We only store activity if it has to be created. If it is updated,
          # the activity will be stored down the road in this method
          # after start_time and end_time have been updated.
          activity.put()
        first_form = False

      if activity_to_be_created:
        # We should not be updating a schedule with a new activity
        assert form.GetSchedule() is None

      new_schedule, old_schedule = form.PrepareSchedule(activity)
      if new_schedule or old_schedule:
        schedule_tuples.append((new_schedule, old_schedule))
        access_points_cache.update(form.access_points_cache)
        # We figure out if we need to update user registrations because of
        # the change in schedule, as well as if we need to notify users.
        if new_schedule and old_schedule:
          # A schedule was updated
          old_aps = set(old_schedule.access_points +
                        old_schedule.access_points_secondary)
          new_aps = set(new_schedule.access_points +
                        new_schedule.access_points_secondary)
          if not old_aps.issubset(new_aps):
            # some access points got deleted
            logging.debug('New set of access points %s is more restrictive than'
                          ' previous set %s', new_aps, old_aps)
            update_user_registrations = True
            notify_users = True
          else:
            # The set of access points did not change, and schedule is still
            # available. We check if time in schedule changed in order to notify
            # users
            if (new_schedule.start_time != old_schedule.start_time or
                new_schedule.end_time != old_schedule.end_time):
              logging.debug('Schedule times changed, notifying users')
              notify_users = True
        else:
          # Schedule was added  for a previously existing activity.
          if new_schedule and not activity_to_be_created:
            logging.debug('A schedule was added')
            update_user_registrations = True
            notify_users = True
          if old_schedule:  # Schedule on an existing activity deleted.
            logging.debug('A schedule was deleted')
            update_user_registrations = True
            notify_users = True

    activity.start_time = None
    activity.end_time = None
    for new_schedule, old_schedule in schedule_tuples:
      if new_schedule is None:  # Old schedule should be deleted.
        # This function is executed in a transaction so calling unsafe method
        # below is ok.
        old_schedule.DeleteUnsafeAndWrite(activity.last_modified_by)
      else:
        new_schedule.put()
        if not activity.start_time:
          activity.start_time = new_schedule.start_time
        else:
          activity.start_time = min(activity.start_time,
                                    new_schedule.start_time)
        if not activity.end_time:
          activity.end_time = new_schedule.end_time
        else:
          activity.end_time = max(activity.end_time, new_schedule.end_time)

    # Update times on activity.
    activity.put()

    if update_user_registrations or notify_users:
      logging.debug('Need to update user registrations, kicking off task')
      deferred.defer(rule_engine.SyncRegistrationsWithActivity,
                     str(activity.key()), notify_users,
                     _transactional=True)
    return activity

  def CreateUpdateSchedules(self, activity=None):
    """Create/Update schedules.

    Args:
      activity: Activity to update. If None will create one.

    Returns:
      Created/updated activity.
    """

    def CreateUpdateSchedulesUnsafe():
      """Wrapper to be run in activity lock."""
      return db.run_in_transaction(self.__CreateUpdateSchedules, activity)

    if activity:
      # We lock on the  activity before trying to make any modification
      lock = models.Activity.GetLock(activity)
      activity = lock.RunSynchronous(CreateUpdateSchedulesUnsafe)
    else:
      activity = CreateUpdateSchedulesUnsafe()

    return activity

  def _PopulateAccessPointsCache(self):
    """Forces the population of access points into memory."""
    for form in self.forms:
      schedule = form.GetSchedule()
      if schedule:
        form.access_points_cache.update(zip(schedule.access_points,
                                            db.get(schedule.access_points)))
        form.access_points_cache.update(
            zip(schedule.access_points_secondary,
                db.get(schedule.access_points_secondary)))

  def IsScheduleAvailable(self):
    """Returns True iff at least one schedule is available."""
    return False in [form.IsDeleted() for form in self.forms]

  # Invalid method name because overriding django.
  # pylint: disable-msg=C6409
  def clean(self):
    # Do cross form validation
    if not self.IsScheduleAvailable():
      msg = _('Cannot delete every timeslot from an activity.')
      raise form_util.ValidationError(msg)
    self._ValidateActivityFields()

  def _ValidateActivityField(self, field_name):
    # Accessing protected members of individual forms to force validation
    # even when form is deleted.
    # pylint: disable-msg=W0212
    try:
      value = self.forms[0]._raw_value(field_name)
      value = self.forms[0].fields[field_name].clean(value)
    except form_util.ValidationError, e:
      self.forms[0]._errors[field_name] = e.messages
      # We raise an error so that formset validation will fail
      raise form_util.ValidationError('')

  def _ValidateActivityFields(self):
    """Validates fields at the activity level (stored on form #0 of formset)."""
    if self.forms[0].IsDeleted():
      # We validate activity fields. This check is not performed when the first
      # form is deleted on the front end since all activity related
      # attributes are stored at the form-0 level and forms validation is
      # bypassed for deleted forms.
      self._ValidateActivityField('max_people')
      self._ValidateActivityField('register_end_date')
      self._ValidateActivityField('register_end_time')
      self._ValidateActivityField('reserve_rooms')

  def PrepareCreateUpdate(self, user, program, activity=None):
    """Validates the formset data before a CreateUpdateData call.

    This method must be called before CreateUpdateData and includes a call to
    is_valid.

    Args:
      user: A models.GlearnUser.
      program: A models.Program.
      activity: An optional models.Activity to be updated. If not provided, a
        new activity is to be created.

    Returns:
      True iff the formset data is valid and successfully parsed.
      If False, the formset is populated with errors to be shown to the user.
    """
    # Triggering a full_clean so it performs formset validation on top of
    # individual form validation.
    self.full_clean()

    if not self.is_valid():
      return False

    first_form = True
    valid_data = True
    for form in self.forms:
      # We start by building properties/validating data. We update the activity
      # only when considering the first form.
      res = form.IntializeProperties(user, first_form, activity,
                                     program)
      # We don't break on invalid data because each form will enrich the
      # error messages when the data is invalid.
      valid_data = valid_data and res
      first_form = False
    non_deleted_forms = [f for f in self.forms if not f.IsDeleted()]
    if valid_data:
      # We check that schedules do not overlap
      end_time = datetime.datetime.min
      for form in sorted(non_deleted_forms,
                         key=lambda x: x.schedule_properties['start_time']):
        if form.schedule_properties['start_time'] < end_time:
          self._non_form_errors = _('Timeslots cannot overlap.')
          valid_data = False
          break
        end_time = form.schedule_properties['end_time']

    # Populate the APCache before starting the transaction. The access points
    # belong to a different entity group and need to be queried outside the
    # different transactions which happen when updating an activity.
    self._PopulateAccessPointsCache()

    if valid_data:
      # We check that every timeslot has the same set of primary tags for its
      # access points
      schedule_tag_sets = [f.schedule_properties['access_point_location_tags']
                           for f in non_deleted_forms]
      access_points_cache = {}
      for form in non_deleted_forms:
        access_points_cache.update(form.access_points_cache)
      if activity:
        ref_tags = set()
        # We had a previous activity / schedules, we use the existing set of
        # office locations
        ref_schedule = activity.ActivitySchedulesQuery().get()
        ref_ap_keys = (ref_schedule.access_points +
                       ref_schedule.access_points_secondary)
        for ap_key in ref_ap_keys:
          ap = access_points_cache.get(ap_key, None)
          assert ap
          ref_tags.add(ap.tags[0])
      else:
        # We use the first timeslot as our reference
        ref_tags = schedule_tag_sets[0]

      # We check that every schedule has at least the same locations as the
      # reference set
      # We check that if there is a new location, it is available on every
      # schedule
      index = 0
      common_locations = None
      for tag_set in schedule_tag_sets:
        if common_locations is None:
          common_locations = tag_set
        else:
          common_locations = common_locations.intersection(tag_set)

      for tag_set in schedule_tag_sets:
        if common_locations and common_locations != tag_set:
          # This timeslot is different from every other one
          # We have new locations which are not on every timeslot
          valid_data = False
          # if this is a new location, we alert user that it must be on every
          # other timeslot
          additional_locations = tag_set - common_locations
          if not additional_locations.issubset(ref_tags):
            msg = 'Locations %s not present on every other timeslot'
            msg %= [str(tag).upper() for tag in additional_locations]
            logging.info(msg)
            msg = form_util.ValidationError(msg).messages
            non_deleted_forms[index].global_error = msg
        elif not ref_tags.issubset(tag_set):
          # make sure that we include all reference locations
          missing_tags = ref_tags.difference(tag_set)
          msg = _('Office locations must include %s')
          # We format tags to be upper case
          msg %= [str(tag).upper() for tag in missing_tags]
          logging.info(msg)
          msg = form_util.ValidationError(msg).messages
          non_deleted_forms[index].global_error = msg
          valid_data = False
        index += 1

    if valid_data:
      # We build the activity access point tags as intersection of schedule tags
      intersect_tags = None
      for form in non_deleted_forms:
        access_point_tags = form.schedule_properties['access_point_tags']
        if intersect_tags is None:
          intersect_tags = set(access_point_tags)
        else:
          intersect_tags = intersect_tags.intersection(access_point_tags)
      tags = list(intersect_tags)
      self.forms[0].activity_properties['access_point_tags'] = tags

    return valid_data

  @staticmethod
  def BuildPostData(user, activity):
    """Creates the post data to seed a formset from an existing activity.

    Args:
      user: models.GlearnUser editing the form.
      activity: A models.Activity

    Returns:
      The POST data dictionary filled with ActivitySchedules from the activity.
    """
    query = activity.ActivitySchedulesQuery()
    index = 0
    formset_data = {}
    for schedule in query:
      formdata = ActivityScheduleForm.BuildPostData(user, schedule, index)
      index += 1
      formset_data.update(formdata)

    formset_data['form-TOTAL_FORMS'] = str(index)
    formset_data['form-INITIAL_FORMS'] = str(index)

    return formset_data


