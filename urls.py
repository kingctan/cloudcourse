#!/usr/bin/python2.4
#
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

"""Url patterns file that maps url patterns to views."""

from django.conf.urls import defaults
from django.contrib import admin
from ragendja import urlsauto
from ragendja.auth import urls as r_auth_urls

handler404 = defaults.handler404
handler500 = defaults.handler500

admin.autodiscover()

urlpatterns = r_auth_urls.urlpatterns
urlpatterns += defaults.patterns(
    '',
    ('^admin/', defaults.include(admin.site.urls)),
)
urlpatterns += urlsauto.urlpatterns
