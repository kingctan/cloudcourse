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


"""Configures core.Models with the django admin site."""

from django.contrib import admin
from django.utils import translation

from core import models

_ = translation.ugettext


# Django/patch automatically uses a class named UserAdmin to map users for the
# admin interface.
# The AUTH_ADMIN_MODULE variable in settings.py contains the module where this
# class is defined.
class UserAdmin(admin.ModelAdmin):
  """Class to define how to edit users in admin interface.

  The django patch looks for the UserAdmin attribute in the module defined by
  the property AUTH_USER_ADMIN in settings.py.

  """
  fieldsets = (
      (('Personal info'), {'fields': ('user', 'timezone', 'course_creator',
                                      'location', 'date_joined')}),
      (('Permissions'), {'fields': ('is_active', 'is_staff')})
  )
  list_display = ('email', 'username', 'is_staff')
  list_filter = ('is_staff', 'is_active')
  search_fields = ('user', 'username')


class ProgramAdmin(admin.ModelAdmin):
  """Admin interface for models.Program."""
  fieldsets = (
      (('Global'), {'fields': ('name', 'description', 'owner',
                               'creation_time', 'program_tags',
                               'visible', 'deleted')}),
      (('Details'), {'fields': ('last_modified_by', 'last_modified'),
                     'classes': ['collapse']}),
      )
  list_display = ('name', 'creation_time', 'deleted')
  list_filter = ('deleted',)
  search_fields = ('name',)


class ActivityAdmin(admin.ModelAdmin):
  """Admin interface for models.Activity."""
  fieldsets = (
      (('Global'), {'fields': ('name', 'owner', 'start_time', 'end_time',
                               'visible', 'deleted',
                               'rules', 'access_point_tags')}),
      (('Details'), {'fields': ('creation_time', 'last_modified_by',
                                'last_modified'),
                     'classes': ['collapse']}),
      )
  list_display = ('name', 'deleted')
  list_filter = ('deleted',)
  search_fields = ('name',)


class ActivityScheduleAdmin(admin.ModelAdmin):
  """Admin interface for models.ActivitySchedule."""
  fieldsets = ((('Global'), {'fields': ('start_time', 'end_time',
                                        'deleted', 'access_points')}),)
  list_display = ('start_time', 'end_time', 'deleted')


class AcessPointAdmin(admin.ModelAdmin):
  """Admin interface for models.AccessPoint."""
  fieldsets = ((('Global'), {'fields': ('uri', 'type', 'tags', 'location',
                                        'timezone',
                                        'rules', 'deleted')}),)
  list_display = ('uri', 'location', 'deleted')

  def _DeleteSelected(self, request, queryset):
    for access_point in queryset:
      access_point.Delete()
    self.message_user(request,
                      '%s access points marked as deleted' % len(queryset))

  # pylint: disable-msg=W0612
  # short_description is used by django framework
  _DeleteSelected.short_description = _('Mark as deleted')

  def _RemoveSelected(self, request, queryset):
    for access_point in queryset:
      access_point.delete()
    self.message_user(request, '%s access points removed' % len(queryset))

  # pylint: disable-msg=W0612
  # short_description is used by django framework
  _RemoveSelected.short_description = _('Remove selected access points')

  actions = [_DeleteSelected, _RemoveSelected]

  # pylint: disable-msg=C6409
  # invalid method name, overriding django method
  def get_actions(self, request):
    """Overriding method."""
    actions = super(AcessPointAdmin, self).get_actions(request)
    if not request.user.is_superuser:
      del actions['_RemoveSelected']
    return actions


class UserRegistrationAdmin(admin.ModelAdmin):
  """Admin interface for models.UserRegistration."""
  fieldsets = ((('Global'), {'fields': ('user', 'activity', 'queue_time')}),)
  list_display = ('user', 'queue_time', 'activity')


class ConfigurationAdmin(admin.ModelAdmin):
  """Admin interface for models.Configuration."""
  fieldsets = ((('Global'), {'fields': ('config_key', 'config_value')}),)
  list_display = ('config_key', 'config_value')
  actions = ['delete_selected']


admin.site.register(models.Program, ProgramAdmin)
admin.site.register(models.Activity, ActivityAdmin)
admin.site.register(models.ActivitySchedule, ActivityScheduleAdmin)
admin.site.register(models.AccessPoint, AcessPointAdmin)
admin.site.register(models.UserRegistration, UserRegistrationAdmin)
admin.site.register(models.Configuration, ConfigurationAdmin)

# Disabling django default delete action because it is too simple.
admin.site.disable_action('delete_selected')

