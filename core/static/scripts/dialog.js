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
 * @fileoverview Collection of utilities around dialogs.
*
 */

goog.provide('dialog');

goog.require('goog.dom');
goog.require('goog.dom.classes');
goog.require('goog.events.EventType');
goog.require('goog.net.XhrIo');
goog.require('goog.ui.Dialog');


/**
 * Dialog to confirm a generic action
 *
 * @param {string} message that asks the user to confirm the action.
 * @param {string} gotoUrl is the page redirect url on user confirmation.
 * @param {string} title Title of the dialog.
 * @export
 */
dialog.confirmAction = function(message, gotoUrl, title) {
  var confirmDialog = new goog.ui.Dialog();
  confirmDialog.setContent(message);
  confirmDialog.setTitle(title);

  confirmDialog.setButtonSet(goog.ui.Dialog.ButtonSet.OK_CANCEL);

  goog.events.listen(confirmDialog, goog.ui.Dialog.SELECT_EVENT, function(e) {
    if (e.key == 'ok') {
      window.location = gotoUrl;
    }
  });
  goog.events.listen(window, goog.events.EventType.UNLOAD, function() {
    goog.events.removeAll()
  });
  confirmDialog.setVisible(true);
};


/**
 * Dialog to confirm action. Retrieves html content through ajax call.
 *
 * @param {string} url Url to use to render html content.
 * @param {string} title Title of the dialog.
 * @param {string} opt_content Post data. If available, will use POST instead of
 *          GET.
 * @export
 */
dialog.confirmAjaxDialog = function(url, title, opt_content) {
  var method = 'GET';
  if (opt_content) {
    method = 'POST';
  }
  //TODO(user): add loading indicator
  goog.net.XhrIo.send(url, function() {

    var formBody = this.getResponseJson().body;
    var confirmDialog = new goog.ui.Dialog();
    confirmDialog.setDisposeOnHide(true);
    confirmDialog.setContent(formBody);
    confirmDialog.setTitle(title);
    confirmDialog.setButtonSet(goog.ui.Dialog.ButtonSet.OK_CANCEL);

    goog.events.listen(confirmDialog, goog.ui.Dialog.SELECT_EVENT, function(e) {
      if (e.key == 'ok') {
        document.getElementById('id_form').submit();
      }
    });
    goog.events.listen(window, goog.events.EventType.UNLOAD, function() {
      goog.events.removeAll()
    });
    confirmDialog.setVisible(true);
  }, method, opt_content);
};


/**
 * Hides confirmation message.
 * @export
 */
dialog.hideConfirm = function() {
  var confirmDiv = goog.dom.$('confirm-msg');
  confirmDiv.textContent = '';
  goog.dom.classes.add(confirmDiv, 'hidden');
};


/**
 * Show confirmation message.
 *
 * @param {string} txt Text to show.
 * @export
 */
dialog.showConfirm = function(txt) {
  var confirmDiv = goog.dom.$('confirm-msg');
  confirmDiv.textContent = txt;
  goog.dom.classes.remove(confirmDiv, 'hidden');
};


/**
 * Show/hide rooms with given id.
 *
 * @param {string} id of the rooms section to display.
 * @param {boolean} show whether to show or hide the rooms.
 * @export
 */
dialog.displayRooms = function(id, show) {
  var showRoomsDiv = goog.dom.$('more_locations_' + id);
  var hideRoomsDiv = goog.dom.$('less_locations_' + id);
  if (show) {
    goog.dom.classes.remove(showRoomsDiv, 'hidden');
    goog.dom.classes.add(hideRoomsDiv, 'hidden');
  } else {
    goog.dom.classes.add(showRoomsDiv, 'hidden');
    goog.dom.classes.remove(hideRoomsDiv, 'hidden');
  }
};

