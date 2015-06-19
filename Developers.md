This page shows how to get started with `CloudCourse` development.

# Introduction #

`CloudCourse` is built with Python and App Engine.
It uses some third party dependencies:
  * [GData](http://code.google.com/p/gdata-python-client/downloads/list)
  * [Closure library](http://code.google.com/closure/library/docs/gettingstarted.html) and the [Closure compiler](http://code.google.com/closure/compiler/)
  * [App Engine patch](http://code.google.com/p/app-engine-patch/downloads/list)
  * [pytz](http://code.google.com/p/gae-pytz/)

The [binaries](http://code.google.com/p/cloudcourse/downloads/list) include all necessary dependencies.
If you build `CloudCourse` yourself, you will need to download them manually. The easiest way to set up the dependencies is to look at a `CloudCourse` binary and replicate the same folder structure for dependencies.

# Getting the code #

[Check out the code](http://code.google.com/p/cloudcourse/source/checkout) from subversion.

# Start development #

## Code structure ##
The bulk of the code is located under the 'core' directory.
Look at the `core/urlsauto.py` module to see all the entry points in the application.

The application entry points are split into 3 categories:
  * `core/tasks.py` contains entry points for everything related to tasks/cron jobs
  * `core/ajax.py` contains every function which is called in an ajax fashion from the client
  * `core/views.py` handles every other http request

We are using the django templating system. All templates are located under `core/templates`

## Static resources ##

All static resources (scripts, styles, images) are located under `core/static`

Before deploying the application in production, javascript files need to be compiled using the closure compiler and the css files need to be concatenated in one bundle.

There is a helper script `make.sh` which does the job. The output js and css files are tagged with the version number of the application (from `app.yaml`).

When developing on your local server, the js/css files are served directly from the original source files. When running on App Engine servers, the js/css are served from the compiled bundles.

You can change this behavior by changing the debug mode in `core/context_processors.py`

# Contributions #

We love contributions. New features, bug fixes, crazy ideas... you name it! If you want write access to svn, contact us.