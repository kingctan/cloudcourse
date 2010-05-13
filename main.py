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



from pytz.gae import pytz

from appengine_django_patch.common.appenginepatch import main as aep_main
# Weird circular dependency problem come up when using different appengine
# tools like appcfg for data download and when trying to run under python 2.4.
# The models import alleviates some of these problems. Not sure why.
from django.contrib.auth import models


def main():
  aep_main.main()


if __name__ == '__main__':
  main()
