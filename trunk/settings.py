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


"""Settings file for django and django_appengine_patch.

The settings file is similar to the example settings file provided by
django_appengine_patch. It configures django and the patch to work with
appengine.
"""

# The django_appengine_patch needs the settings_post and settings_pre imports
# for it to support it features.
# pylint: disable-msg=W0401
# pylint: disable-msg=C6203
from ragendja.settings_pre import *
import appenginepatcher
from appenginepatcher import appid

import django

# Increase this when you update your media on the production site, so users
# don't have to refresh their cache. By setting this your MEDIA_URL
# automatically becomes /media/MEDIA_VERSION/
MEDIA_VERSION = 1
SECRET_KEY = 'any-key-goes-here'
USE_I18N = False
LANGUAGE_CODE = 'en'

ROOT_URLCONF = 'urls'

ADMIN_MEDIA_PREFIX = ('/adminmedia/')

TEMPLATE_CONTEXT_PROCESSORS = (
    'django.core.context_processors.auth',
    'django.core.context_processors.media',
    'django.core.context_processors.request',
    'django.core.context_processors.i18n',
    'core.context_processors.Debug'
)

TEMPLATE_DIRS = ('core.templates',)

MIDDLEWARE_CLASSES = (
    #'google.appengine.ext.appstats.recording.AppStatsDjangoMiddleware',
    'core.middleware.Cache',
    'core.middleware.ExceptionHandler',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'ragendja.auth.middleware.GoogleAuthenticationMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'ragendja.sites.dynamicsite.DynamicSiteIDMiddleware',
    'django.contrib.redirects.middleware.RedirectFallbackMiddleware',
    'ragendja.middleware.LoginRequiredMiddleware',
)


AUTH_USER_MODULE = 'core.django_config_user'
AUTH_ADMIN_MODULE = 'core.admin'
AUTH_ADMIN_USER_AS_SUPERUSER = True

GLOBALTAGS = (
    'ragendja.templatetags.ragendjatags',
    'django.templatetags.i18n',
)

INSTALLED_APPS = (
    'django.contrib.auth',
    'django.contrib.sessions',
    'django.contrib.admin',
    'appenginepatcher',
    'core',
    'ragendja'
)

LOGIN_URL = '/account/login/'
LOGOUT_URL = '/account/logout/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

LOGIN_REQUIRED_PREFIXES = (
    '/'
)
NO_LOGIN_REQUIRED_PREFIXES = (
    '/account/login',
    '/tasks',
    '/_ah/queue/deferred'
)

# List apps which should be left out from app settings and urlsauto loading
IGNORE_APP_SETTINGS = IGNORE_APP_URLSAUTO = (
)

# Remote access to production server (e.g., via manage.py shell --remote)
DATABASE_OPTIONS = {
    # Change domain (default: <remoteid>.appspot.com)
    'remote_host': appid + '.appspot.com',
}
if not appenginepatcher.on_production_server:
  DATABASE_OPTIONS['remote_host'] = 'localhost:8080'

# Email used as sender for every email sent.
ADMIN_EMAIL = '<user>@<domain>'

# Batch calendar gdata feed to the calendar that should contain the events.
CALENDAR_BATCH_EVENT_FEED = ('/calendar/feeds/<your_role_account>@gmail.com'
                             '/private/full/batch')

# Departments choices shown to user during create activity.
FORM_DEPARTMENT_CHOICES = [('eng', 'Engineering'),
                           ('sales', 'Sales'),
                           ('other', 'Other')]

SERVICE_PROVIDER_MODULES = {
    'user_info_service': ('core.user_info_service', '_UserInfoService'),
    'datastore_sync_service': ('core.sync_service', '_SyncService'),
    'search_service': ('core.search_service', '_SearchService'),
    'room_info_service': ('core.room_info_service', '_JsonRoomInfoService')
}

# This file contains the timezone information.
TIMEZONES_FILE_LOCATION = 'core/data/timezones.json'

LOGO_LOCATION = '/images/logo/logo_160.png'
HELP_URL = 'http://code.google.com/p/cloudcourse/'
# The django_appengine_patch needs the settings_post and settings_pre imports
# for it to function well and support it features.
# pylint: disable-msg=C6204
from ragendja.settings_post import *
