#!/bin/bash
# Copyright 2010 Google Inc. All Rights Reserved.
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

#

APP_VERSION=`grep ^version: app.yaml | awk {'print $2'}`

echo 'Compiling javascript...'
./closure-library-read-only/closure/bin/build/closurebuilder.py -c third_party/compiler.jar \
--output_file=core/static/scripts/scripts_compiled_$APP_VERSION.js \
-i core/static/scripts/approvals.js \
-i core/static/scripts/dialog.js \
-i core/static/scripts/editor.js \
-i core/static/scripts/roster.js \
-i core/static/scripts/search.js \
-i core/static/scripts/sessions.js \
--root=. \
-o compiled \
#-f --compilation_level -f ADVANCED_OPTIMIZATIONS \

echo 'Creating css'
cat closure-library-read-only/closure/goog/css/editortoolbar.css closure-library-read-only/closure/goog/css/toolbar.css core/static/styles/datepicker.css  core/static/styles/dialog.css  core/static/styles/main.css  core/static/styles/roster.css  core/static/styles/sessions.css > core/static/styles/styles_compiled_$APP_VERSION.css
echo 'All tasks completed.'