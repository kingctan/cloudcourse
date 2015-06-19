Check here for [installation instructions](WikiInstall.md)

# Settings.py #

  * ADMIN\_EMAIL: Administrative email used as sender for every email sent.
  * CALENDAR\_BATCH\_EVENT\_FEED: Google calendar gdata feed url. Calendar events are created on this calendar for activity sessions.
  * HELP\_URL: Link presented for help on the site, can be pointed to a user customized help site.
  * LOGO\_LOCATION: Image that is displayed as the site logo.
  * SERVICE\_PROVIDER\_MODULES: Maps services used by the site to implementing modules. These modules can be customized/rewritten to fit your requirements.
  * TIMEZONES\_FILE\_LOCATION: Cloudcourse needs to know the timezones of users and room in the system to manage time display and cross timezone sessions. This should point to a .json file with mappings from country\_city codes that users and rooms can have to the pytz timezone name they are mapped to.


# Services #

The following services can be custom written and replaced easily on the site. The service modules can be customized in settings.py file user SERVICE\_PROVIDER\_MODULES.

### Datastore Sync Service ###

This service is used to actively notify datastore changes to an external system. Useful to notify external system of new courses, registrations and their changes etc. The default module provided doesn't communicate to any external site. Interface defined in `core.service_interfaces.DatastoreSyncService`.

### Search Service ###

This service is used to search activities and their sessions. The default module doesn't provided any search functionality, users need to write their own preferred search mechanism and decide what model properties to search on etc. Interface defined in `core.service_interfaces.SearchService`.

### Room Info Service ###

This service is used to inform the site of the conference rooms that are available for scheduling sessions. The service can be setup to be called periodically to update the list of rooms available on a regular basis. Site admins can also manually call for the rooms in the system to be updated by click on "Admin interface > Access Points > Load Rooms" this would start a background process that will update the rooms by querying the rooms info service. Interface defined in `core.service_interfaces.RoomInfoService`.

### User Info Service ###

This service is used to to gather user information. This service is used both to evaluate business rules and to display user information. Information like user employment types, employee manager etc is provided by this service. Interface defined in `core.service_interfaces.UserInfoService`.

# Advanced customization #

It is possible to further customize Cloud Course, with some more work.

## Email ##

Cloud Course is configured to replace mailto links with gmail links automatically. If you want to use regular `<href=mailto:>` links instead:

  * Update `core/templatetags/format.py` emailUrl method.
  * Update `core/static/scripts/roster.js` roster.emailAll method.

## Calendar updates ##

Cloud Course is integrated with Google Calendar to update user calendars.
By default, the calendar has to be on the same domain as the application instance. So if your application is restricted to domain.com your calendar should also be available on the same domain. This behavior is controlled by `calendar.CalendarTokenRequestUrl`.

If you want to integrate with a different backend than Google Calendar, look at calendar.py module and replace relevant methods.
