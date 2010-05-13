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


"""Urls to view mappings."""

from django.conf.urls import defaults

from core import ajax
from core import tasks
from core import views

handler404 = defaults.handler404
handler500 = defaults.handler500


rootpatterns = defaults.patterns(
    '',
    (r'^$', views.Home, {}, 'Home'),

    # Backend trigger URLs, all urls that are triggered by the taskqueue and
    # cron job should be place here with the prefix 'tasks/'.
    (r'^tasks/offline/$', tasks.ProcessOfflineTask, {}, 'ProcessOfflineTask'),
    (r'^tasks/clean/registeredusersentity/(?P<config_key>.+)$',
     tasks.DeleteProgramOrActivity, {}, 'DeleteProgramOrActivity'),
    (r'^tasks/conferencerooms/startcollection/$',
     views.BeginConferenceRoomsStorage,
     {}, 'ConferenceRoomsCollect'),
    (r'^tasks/performquerywork/(?P<work_name>.+)$',
     tasks.PerformQueryWorkTask, {}, 'PerformQueryWorkTask'),
    (r'^_ah/queue/deferred$', views.RunDeferred, {}, 'DontResolveInCode'),

    # Admin interface URLs
    (r'^conferencerooms/load/(?P<query_offset>.+)/(?P<num_rooms>.+)$',
     views.FetchAndStoreConferenceRooms, {}, 'ConferenceRoomsLoad'),
    (r'^conferencerooms/constructaccesspointsinfo/$',
     views.ConstructAccessPointsInfo, {}, 'ConstructAccessPointsInfo'),

    # General URLs.
    (r'^ajax/validateemails/$', ajax.ValidateEmails, {},
     'ValidateEmails'),
    (r'^systemstatus/$', views.SystemStatus, {}, 'SystemStatus'),
    (r'^managerapprovals/$', views.ShowManagerApprovals, {},
     'ShowManagerApprovals'),
    (r'^owned/$', views.ShowOwned, {}, 'ShowOwned'),
    (r'^learning/$', views.ShowLearning, {}, 'ShowLearning'),
    (r'^teaching/$', views.ShowTeaching, {}, 'ShowTeaching'),
    (r'^all/$', views.ShowPrograms, {}, 'ShowPrograms'),
    (r'^search/$', views.Search, {}, 'Search'),
    (r'^token/store/', views.StoreCalendarSessionToken, {},
     'StoreCalendarSessionToken'),
    (r'^calendar/token/update/$', views.UpdateCalendarSessionToken,
     {}, 'UpdateCalendarSessionToken'),
    (r'^settings/$', views.UpdateSettings, {}, 'Settings'),
    (r'^reset/task/reset_datastore_sync$', views.ResetDatastoreSync,
     {}, 'ResetDatastoreSync'),

    # Activity related URLs (models.Program in code)
    (r'^ajax/deleteprogrampopup/(?P<program_key>.+)$',
     ajax.DeleteProgramPopupForm, {}, 'DeleteProgramPopupForm'),
    (r'^create/activity/$', views.CreateProgram, {}, 'CreateProgram'),
    (r'^delete/activity/(?P<program_key>.+)$', views.DeleteProgram, {},
     'DeleteProgram'),
    (r'^activity/(?P<program_key>.+)$', views.ShowProgram, {}, 'ShowProgram'),
    (r'^update/activity/(?P<program_key>.+)$', views.UpdateProgram, {},
     'UpdateProgram'),

    # Roster related urls
    (r'^ajax/attendance/(?P<activity_key>.+)/(?P<attended>.+)$',
     ajax.UserAttendance, {}, 'UserAttendance'),
    (r'^roster/enroll/(?P<activity_key>.+)$', views.RosterEnroll, {},
     'RosterEnroll'),
    (r'^roster/print/(?P<activity_key>.+)/(?P<order_by>.+)$',
     views.PrintRoster, {}, 'PrintRoster'),
    (r'^roster/show/(?P<activity_key>.+)/(?P<order_by>.+)$',
     views.ShowRoster, {}, 'ShowRoster'),

    # Registration URLs
    (r'^ajax/registerpopupmultiple/(?P<program_key>.+)/(?P<activity_key>.+)$',
     ajax.RegisterPopupFormMultiple, {}, 'RegisterPopupFormMultiple'),
    (r'^ajax/registerpopup/(?P<program_key>.+)/(?P<activity_key>.+)$',
     ajax.RegisterPopupForm, {}, 'RegisterPopupFormSingle'),
    (r'^unregisterusers/(?P<activity_key>.+)/(?P<users>.+)$',
     views.UnregisterUsers, {}, 'UnregisterUsers'),
    (r'^changestatustoenrolled/(?P<activity_key>.+)/(?P<users>.+)$',
     views.ChangeUserStatusToEnrolled, {}, 'ChangeUserStatusToEnrolled'),
    (r'^register/$', views.UserRegister, {}, 'UserRegister'),
    (r'^ajax/register/$', ajax.UserRegister, {}, 'UserRegisterAjax'),
    (r'^unregister/(?P<program_key>.+)/(?P<activity_key>.+)$',
     views.UserUnregister, {}, 'UserUnregister'),

    # Session related URLs (models.Activity in code)
    (r'^ajax/deleteactivitypopup/(?P<activity_key>.+)$',
     ajax.DeleteActivityPopupForm, {}, 'DeleteActivityPopupForm'),
    (r'^create/session/(?P<program_key>.+)$', views.CreateActivity, {},
     'CreateActivity'),
    (r'^delete/session/(?P<activity_key>.+)$', views.DeleteActivity, {},
     'DeleteActivity'),
    (r'^session/(?P<activity_key>.+)$', views.ShowActivity, {}, 'ShowActivity'),
    (r'^update/session/(?P<activity_key>.+)$', views.UpdateActivity, {},
     'UpdateActivity'),
)
