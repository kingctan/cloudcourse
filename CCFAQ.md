## General FAQ ##


**How is the user timezone set and how can it be changed?**
> Timezones are based off the user's country-city code provided by the user info service. Users can click on settings to change the location and hence their timezone.


**How do I search for activities and sessions?**
> There is no out of the box search feature. If the search service is implemented user can search on the site. Else users have to go by the "All activities" on the left navigation.


**What happens if I’m on the waitlist?**
> You will receive an email that tells you which position you are on the waitlist. If a seat opens up, you will receive an email confirming your enrollment. If a seat does not becomes available you will not be notified.


**Does declining the calendar invite unregister the user from a sessoin?
> NO**


**What happens in a  manager approval workflow?**
> The manager will be sent an email with a link to approve/deny registration for a user. The manager can also come to the site and click on "approvals" link to see a list of approvals waiting for her. If the manager declines the user is unregistered automatically and informed of the decision. The user can try the process again. If the manager approves the user clears the approval state and is evaluated for other business rules like maximum enrollment in a session etc.


**What automated emails does the system send to participants?**
> User waitlist/register/unregister operations. Session edits/deletes that trigger updates to registered students. Manager approval request to manager and user.


## Course Owner FAQ ##


**How to bypass manager approvals/max enrollment and enroll people into a session?**
> Two options. You can use the bulk enroll students link on the roster screen and then check the "Force-register students without waitlist management" box. Or once the students are already enrolled and placed on the waitlist you can use the "Force Status" drop down on the roster screen to change the status to enrolled.


**I accidentally deleted an activity/session. Can I undo it ?**
> No, once you delete an activity/session it is gone for good. You would need to recreate the activity/session from scratch.


**When do I delete an activity?**
> Deleting an activity implies that the activity never existed and all sessions under it were dummy or never happened and no sessions will happen in the future. If this is not true then just consider making the activity invisible and stop using the activity. Do not delete to just deprecate an activity.


**When do I delete a session?**
> If the session happened in the past then deleting the session is equivalent to saying it never actually happened. If the session is in the future then it amounts to cancelling the session.


**What happens when I delete an activity/session?**
> First a background process kicks off to unregister all users who were ever registered in this course and unregistered from it. An email goes out to the users that the activity/session is canceled. Once this process is done the activity/session is deleted and cannot be reached anyfurther. If the idea is to just make the activity/session to be canceled or deprecated then consider making them invisible by editing them.


**Will the participants be notified when I edit my session?**
> Yes,  they will receive an email informing of the updates you’ve made in the sessions and update their calendar entries as well.


**I want to publicize a particular session but the activity page has too many sessions, how do I link directly to a session?**
> To find the specific URL for a session click on the "link" icon of a session. This will give a page describing just this session. This URL can be shared/advertised to your audience to come and register.


**I don't see the room I want to schedule listed as an option, what do I do?**
> The room information is collected from the room info service. The service should be updated to provide the most up to date information on rooms. The service can be called using a cron job periodically (not configured by default). Or site administrators can click on Admin interface > Access Points > Reload Rooms to load the rooms again through rooms info service.