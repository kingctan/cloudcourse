// Copyright 2009 Google Inc. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS-IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

/**
 * @fileoverview Collection of methods to manage the students roster.
*
 */

goog.provide('roster');

goog.require('goog.array');
goog.require('goog.dom');
goog.require('goog.dom.classes');
goog.require('goog.dom.forms');
goog.require('goog.events');
goog.require('goog.events.EventType');
goog.require('goog.events.KeyCodes');
goog.require('goog.net.EventType');
goog.require('goog.net.XhrIo');
goog.require('goog.string');
goog.require('goog.ui.Dialog');
goog.require('goog.ui.MenuButton');


/**
 * Shows/hides session details.
 * @export
 */
roster.toggleSessionDetails = function() {
  var sessionDiv = goog.dom.$('id_session-details');
  var showLink = goog.dom.$('id_show-details');
  var hideLink = goog.dom.$('id_hide-details');
  goog.dom.classes.toggle(sessionDiv, 'hidden');
  goog.dom.classes.toggle(showLink, 'hidden');
  goog.dom.classes.toggle(hideLink, 'hidden');
};


/**
 * Toggles all elements with the given class under given parent.
 *
 * @param {string} parent Element ID of parent to be considered.
 * @param {string} className of elements to be toggled.
 * @export
 */
roster.toggleClass = function(parent, className) {
  var parentDiv = goog.dom.$(parent);
  var elements = parentDiv.getElementsByClassName(className);
  for (var i = 0, element; element = elements[i]; i++) {
    goog.dom.classes.toggle(element, 'hidden');
  }
};


/**
 * Updates the display of the students based on user selection.
 * @export
 */
roster.updateRosterDisplay = function() {
  var parentDiv = goog.dom.$('roster-list');
  var students = parentDiv.getElementsByClassName('student');
  var showEnrolled = goog.dom.$('checkbox-enrolled').checked;
  var showWaitlisted = goog.dom.$('checkbox-waitlisted').checked;
  var showNoshow = false;
  var checkboxNoshow = goog.dom.$('checkbox-noshow');
  if (checkboxNoshow != null) {
    showNoshow = goog.dom.$('checkbox-noshow').checked;
  }
  var showAttended = false;
  var checkboxAttended = goog.dom.$('checkbox-attended');
  if (checkboxAttended != null) {
    showAttended = goog.dom.$('checkbox-attended').checked;
  }
  var totalCount = students.length;
  for (var i = 0, student; student = students[i]; i++) {

    if (showEnrolled && goog.dom.classes.has(student, 'enrolled') ||
        showWaitlisted && goog.dom.classes.has(student, 'waitlisted') ||
        showNoshow && goog.dom.classes.has(student, 'noshow') ||
        showAttended && goog.dom.classes.has(student, 'attended')) {
      goog.dom.classes.remove(student, 'hidden');

    } else {
      totalCount--;
      // we should not display this student, and remove it from
      // selection
      function input(node) {
        return node.type == 'checkbox';
      }
      var inputs = goog.dom.findNodes(student, input);
      if (inputs.length > 0) {
        // remove student from selection.
        inputs[0].checked = false;
      }
      goog.dom.classes.add(student, 'hidden');
    }

  }
  var studentsCount = goog.dom.$('students-count');
  if (studentsCount != null) {
    studentsCount.textContent = totalCount;
  }
};


/**
 * Toggles selection for all visible students.
 * @export
 */
roster.toggleSelectAll = function() {
  var parentDiv = goog.dom.$('roster-list');
  var selected = goog.dom.$('checkbox-select-all').checked;
  var students = parentDiv.getElementsByClassName('checkbox-select');
  for (var i = 0, student; student = students[i]; i++) {
    if (!goog.dom.classes.has(student.parentNode.parentNode, 'hidden')) {
      student.checked = selected;
    }
  }
};


/**
 * Sends email with given subject to selected students.
 *
 * @param {string} userEmail Email address of user initiating the request.
 * @param {string} subject of the email.
 * @export
 */
roster.emailAll = function(userEmail, subject) {
  dialog.hideConfirm();
  var students = roster.getSelectedStudents();
  if (students.length != 0) {
    var url = goog.string.buildString(
        'https://mail.google.com/mail/b/', userEmail,
        '/?AuthEventSource=Internal&view=cm&tf=0&to=',
        students.join(','), '&su=', subject);
    window.open(url);
  } else {
    dialog.showConfirm('No students selected.');
  }
};


/**
 * Returns an array of emails of selected students.
 *
 * @return {Array.<string>} an array of emails of selected students.
 * @export
 */
roster.getSelectedStudents = function() {
  var roster = goog.dom.$('roster-list');
  var students = roster.getElementsByClassName('checkbox-select');
  var res = [];
  var count = 0;
  for (var i = 0, student; student = students[i]; i++) {
    if (student.checked) {
      res[count++] = student.id;
    }
  }
  return res;
};


/**
 * Forces a status change for selected users.
 *
 * @param {string} url Url to use for unenrollment.
 * @param {boolean} enroll true when we want to enroll, false for unenroll.
 * @export
 */
roster.forceRegisterStatus = function(url, enroll) {
  var students = roster.getSelectedStudents();
  if (students.length > 0) {
    var emails = students.join(' ');
    url += escape(emails);

    var action = enroll ? 'enroll' : 'unenroll';
    var question = goog.string.buildString('Are you sure you want to ', action,
                                           ' ', students.length, ' students ?');
    var title = goog.string.buildString('Confirm ', action);
    dialog.confirmAction(question, url, title);
  } else {
    dialog.showConfirm('No students selected.');
  }
};


/**
 * Adds the users from the input to the list after validation.
 *
 * @param {string} url Url to validate emails.
 * @param {Function} callback_func callback when http response returns.
 * @export
 */
roster.addUsersToList = function(url, callback_func) {
  var input = goog.dom.$('id-emails');
  var emails = goog.string.collapseWhitespace(input.value);
  if (emails != '') {
    dialog.showConfirm('Checking users, please wait...');

    var data = 'emails=' + emails;
    goog.net.XhrIo.send(url, function() {
      var inputs = this.getResponseJson();
      var count = 0;
      for (var i = 0, input; input = inputs[i]; i++) {
        var html = goog.string.buildString(
            '<span class="roster-user-added" id="',
            input['email'], '">', input['name'], ' (', input['email'],
            ')</span> <a href="javascript:void;" ',
            'onClick="javascript:roster.removeUser(this)" class="remove" ',
            'alt="Remove ', input['name'], '" title="Remove ', input['name'],
            '"></a>');
        var li = goog.dom.createElement('li');
        li.innerHTML = html;
        var list = goog.dom.$('list-add');
        list.appendChild(li);
        count++;
      }
      dialog.hideConfirm();
      callback_func();
    }, 'POST', data);
  } else {
    callback_func();
  }
  input.value = '';
};


/**
 * Records user attendance to a session.
 *
 * @param {string} url Url used for attendance.
 * @param {boolean} attended Whether user attended or not showed.
 * @param {string} email Email of user to record attendance for.
 * @export
 */
roster.attendance = function(url, attended, email) {
  dialog.showConfirm('Recording attendance...');
  roster.attendanceMulti_(url, attended, [email]);
};


/**
 * Records attendance for multiple users.
 *
 * @param {string} url Url used for attendance.
 * @param {boolean} attended Whether user attended or not showed.
 * @param {Array.<string>} students Array of student emails.
 * @private
 */
roster.attendanceMulti_ = function(url, attended, students) {
  var data = 'emails=' + students.join(' ');

  goog.net.XhrIo.send(url, function() {
    var msg = 'no show';
    if (attended) {
      msg = 'attended';
    }
    var results = this.getResponseJson();
    for (var i = 0, email; email = students[i]; i++) {
      var student = goog.dom.$(email).parentNode.parentNode;
      if (results[email]) {
        dialog.showConfirm(email + ' recorded as ' + msg);
        if (attended) {
          goog.dom.classes.swap(student, 'noshow', 'attended');
        } else {
          goog.dom.classes.swap(student, 'attended', 'noshow');
        }
        goog.dom.$('attended-' + email).checked = attended;
        goog.dom.$('noshow-' + email).checked = !attended;
      } else {
        dialog.showConfirm('Could not record attendance. Try again later');
        // attendance record failed, we switch back the
          // radio buttons
          // to their previous states.
          goog.dom.$('attended-' + email).checked = goog.dom.classes.has(
              student, 'attended');
          goog.dom.$('noshow-' + email).checked = goog.dom.classes.has(
              student, 'noshow');
        }
      }
      roster.updateRosterDisplay();
    }, 'POST', data);
};


/**
 * Records attendance for multiple users.
 *
 * @param {string} url Url used for attendance.
 * @param {boolean} attended Whether user attended or not showed.
 * @export
 */
roster.attendanceMulti = function(url, attended) {
  var students = roster.getSelectedStudents();
  if (students.length > 0) {
    dialog.hideConfirm();
    roster.attendanceMulti_(url, attended, students);
  } else {
    dialog.showConfirm('No students selected.');
  }
};


/**
 * Removes user from list of users to be added.
 *
 * @param {Element} element Element to be removed.
 * @export
 */
roster.removeUser = function(element) {
  dialog.hideConfirm();
  goog.dom.removeNode(element.parentNode);
};


/**
 * Initializes listeners for the roster page.
 *
 * @param {string} url Url used for validating user emails.
 * @export
 */
roster.initListeners = function(url) {
  goog.events.listen(goog.dom.$('id-emails'), goog.events.EventType.KEYUP,
                     function(e) {
    if (e.keyCode == goog.events.KeyCodes.ENTER) {
      roster.addUsersToList(url, function() {});
    }
  });
};


/**
 * Helper function to enroll students async.
 *
 * @param {Array.<string>} emails Array of student emails.
 * @private
 */
roster.enrollStudents_ = function(emails) {
  var bucketSize = 5;
  var urlSubmit = goog.dom.$('id_form').action;
  // submit by batches
  var buckets = [];
  var bucket = [];
  for (var i = 0; i < emails.length; i++) {
    bucket.push(emails[i]);
    if ((i + 1) % bucketSize == 0) {
      buckets.push(bucket);
    bucket = [];
  }
  }
  if (bucket.length > 0) {
    buckets.push(bucket);
  }
  var currentBucket = 0;
  var successEnroll = [];

  var emailInput = document.getElementById('user_emails');
  var formsHelper = goog.dom.forms;
  var registerForm = goog.dom.$('id_form');

  var xhr = new goog.net.XhrIo();
  xhr.setTimeoutInterval(30000);

  var handleError = function() {
    currentBucket++;
    window.setTimeout(processBatch, 0);
  };

  var processBatch = function() {
  if (xhr.isActive()) {
    window.setTimeout(processBatch, 100);
    return;
  }
  if (currentBucket < buckets.length) {
    var successMsg = goog.string.buildString('Enrolling ',
                                             successEnroll.length + 1, '/',
                                             emails.length, '...');
    dialog.showConfirm(successMsg);
    emailInput.value = buckets[currentBucket].join(',');
    xhr.send(urlSubmit, 'POST', formsHelper.getFormDataString(registerForm));
  } else {
    // job finished
    var msg = goog.string.buildString(
        successEnroll.length, ' / ', emails.length, ' users enrolled.');
    dialog.showConfirm(msg);
  }
  };

  var batchListener = function() {
  if (xhr.getStatus() == 200) {
    var enrolledFromBatch = xhr.getResponseJson()['enrolled'];
    for (var i = 0, student; student = enrolledFromBatch[i]; i++) {
      var studentDiv = goog.dom.$(student);
      goog.dom.classes.remove(studentDiv, 'roster-user-added');
      goog.dom.classes.add(studentDiv, 'roster-user-enrolled');
      var removeLink = studentDiv.parentNode.lastChild;
      goog.dom.classes.remove(removeLink, 'remove');
      goog.dom.classes.add(removeLink, 'enrolled');
    }
    goog.array.extend(successEnroll, xhr.getResponseJson()['enrolled']);
    }
    currentBucket++;
    window.setTimeout(processBatch, 0);
  };

  goog.events.listen(xhr, goog.net.EventType.TIMEOUT, handleError);
  goog.events.listen(xhr, goog.net.EventType.ERROR, handleError);
  goog.events.listen(xhr, goog.net.EventType.COMPLETE, batchListener);
  processBatch();
};


/**
 * Enrolls students to the roster.
 *
 * @param {string} url Url used for user registration.
 */
roster.enrollStudents = function(url) {
  var rosterList = goog.dom.$('list-add');
  var students = rosterList.getElementsByClassName('roster-user-added');
  dialog.hideConfirm();
  if (students.length == 0) {
    dialog.showConfirm('No students selected.');
    return;
  }
  var emails = [];
  for (var i = 0, student; student = students[i]; i++) {
    emails[i] = student.id;
  }
  var notify = goog.dom.$('checkbox-notifications').checked ? '1' : '0';
  var forceStatus = goog.dom.$('checkbox-force-status').checked ? '1' : '0';
  var data = goog.string.buildString('emails=', emails.join(','), '&notify=',
                                     notify, '&force_status=', forceStatus);


  goog.net.XhrIo.send(url, function() {

      var formBody = this.getResponseJson().body;
      var confirmDialog = new goog.ui.Dialog();
      confirmDialog.setDisposeOnHide(true);
      confirmDialog.setContent(formBody);
      confirmDialog.setTitle('Confirm registration');
      confirmDialog.setButtonSet(goog.ui.Dialog.ButtonSet.OK_CANCEL);
      goog.events.listen(confirmDialog, goog.ui.Dialog.SELECT_EVENT,
          function(e) {
            if (e.key == 'ok') {
              roster.enrollStudents_(emails);
            }
          }
      );
      goog.events.listen(window, goog.events.EventType.UNLOAD, function() {
        goog.events.removeAll()
      });
      confirmDialog.setVisible(true);
    }, 'POST', data);
};


/**
 * Add students to the roster.
 *
 * @param {string} urlValidate Url used for email validation.
 * @param {string} urlEnroll Url used for user enrollment.
 * @export
 */
roster.addStudents = function(urlValidate, urlEnroll) {
  // we start by validating users from the input form and then enroll
  // students.
  roster.addUsersToList(urlValidate, function() {
    roster.enrollStudents(urlEnroll);
  });
};


/**
 * Initializes the mark as menu button.
 * @param {boolean} enabled Whether the menu button is enabled or not.
 * @export
 */
roster.initMarkAsButton = function(enabled) {
  var button = new goog.ui.MenuButton('Mark attendance');
  button.decorate(goog.dom.$('markAsMenuButton'));
  button.setEnabled(enabled);
};


/**
 * Initializes the force status menu button.
 * @export
 */
roster.initForceStatusButton = function() {
  var button = new goog.ui.MenuButton('Force status');
  button.decorate(goog.dom.$('forceStatusButton'));
  button.setEnabled(true);
};
