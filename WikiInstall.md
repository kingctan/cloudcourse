# Install Instructions #

## Pre-requisites ##

Get [Google App Engine SDK](http://code.google.com/appengine/downloads.html) for python.

## Configure and Build ##

  1. [Get the code](http://code.google.com/p/cloudcourse/downloads/list).
  1. Update app.yaml: `<appid>` should be replaced with your App Engine app id.
  1. Update settings.py: Configure `ADMIN_EMAIL` and `CALENDAR_BATCH_EVENT_FEED`. See [details](WikiCustomization.md) if you need more info.
  1. Update core/data/timezones.json  and core/data/rooms.json files to configure the system with correct room and timezone information respectively. The files come with example data.
  1. Run make.sh. Make sure it has execute permissions (chmod +x make.sh). This will compile the javascript and css files. (compiled files will be suffixed by the version from app.yaml). This should be done on subsequent application uploads if there are any changes to the javascript/css/app.yaml files. If you are running on Windows just adapt the script accordingly (it running basic commands).


## Deployment ##

Assuming you have created an application of the app id specified in the app.yaml and have the Google App Engine SDK for python installed you can now [upload the app](http://code.google.com/appengine/docs/python/tools/uploadinganapp.html#Uploading_the_App).

`$GOOGLE_APPENGINE_SDK_DIR/appcfg.py update $CLOUD_COURSE_DIR`


## Post Deployment Setup ##

  1. Log in to your `CloudCourse` deployment with an admin/App Engine developer account.
  1. Populate the database with room information. Click on the upper right corner `Admin interface` then on `Access points` then on `Load rooms`. This triggers a process that reads rooms from your core/data/rooms.json file and creates entries in datastore.
  1. Authorize the system to access Google Calendar (calendar specified in CALENDAR\_BATCH\_EVENT\_FEED in the settings.py file above). Go back to the `Admin interface` and click on `Configuration`. Then click `Get calendar token` and login with the account information who has write access to the calendar. You should see a calendar token in the configuration list.


**That's it!** To make sure that everything works correctly try to [create an activity](CreateActivity.md).

For more information on Google App Engine SDK
[click here](http://code.google.com/appengine/docs/python/gettingstarted/devenvironment.html).