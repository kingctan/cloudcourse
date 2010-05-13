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
 * @fileoverview Collection of methods to manage sessions for activities.
*
 */

goog.provide('sessions');

goog.require('goog.dom');
goog.require('goog.dom.TagName');
goog.require('goog.dom.classes');
goog.require('goog.events');
goog.require('goog.events.EventType');
goog.require('goog.i18n.DateTimeFormat');
goog.require('goog.i18n.DateTimeParse');
goog.require('goog.locale');
goog.require('goog.locale.formatting');
goog.require('goog.string');
goog.require('goog.ui.AutoComplete.ArrayMatcher');
goog.require('goog.ui.AutoComplete.Basic');
goog.require('goog.ui.AutoComplete.InputHandler');
goog.require('goog.ui.AutoComplete.Renderer');
goog.require('goog.ui.InputDatePicker');
goog.require('goog.ui.LabelInput');
goog.require('goog.ui.Tooltip');


/**
 * Deletes a timeslot from set of forms.
 *
 * @param {Element} element within timeslot that should be deleted.
 * @export
 */
sessions.deleteTimeslot = function(element) {
  element = sessions.getEnclosingTimeslot_(element);
  goog.dom.classes.add(element, 'hidden');

  function input(node) {
    return node.nodeName == goog.dom.TagName.INPUT;
  }
  var inputs = goog.dom.findNodes(element, input);

  for (var i = 0, node; node = inputs[i]; i++) {
    if (node.name.indexOf('-DELETE') != -1) {
      // We mark the entry as deleted
      node.value = '1';
    }
  }
  // remove active form so we don t use it for any more cloning
  goog.dom.classes.remove(element, 'active_form');
};


/**
 * Returns the enclosing timeslot for the given element.
 * @private
 * @param {Element} element Element containing target timeslot.
 * @return {Element} enclosing timeslot which contains the given element.
 */
sessions.getEnclosingTimeslot_ = function(element) {
  // look up top level timeslot div
  while (!goog.dom.classes.has(element, 'timeslot-wrapper')) {
    element = element.parentNode;
  }
  return element;
};


/**
 * Hides a timeslot if deleted.
 *
 * @private
 * @param {string} divId Id of the timeslot div to process.
 * @return {boolean} True if timeslot was hidden.
 */
sessions.processDeletedTimeslot_ = function(divId) {
  var timeslot = goog.dom.$(divId);

  function input(node) {
    return node.nodeName == goog.dom.TagName.INPUT;
  }
  var inputs = goog.dom.findNodes(timeslot, input);

  for (var i = 0, node; node = inputs[i]; i++) {
    if (node.name.indexOf('-DELETE') != -1) {
      if (node.value == '1') {
        // form is deleted, we hide it
        goog.dom.classes.add(timeslot, 'hidden');
        goog.dom.classes.remove(timeslot, 'active_form');
        return true;
      }
    }
  }
  return false;
};


/**
 * Clones a given timeslot.
 *
 * @param {Element} element within timeslot that should be cloned.
 * @export
 */
sessions.cloneTimeslot = function(element) {
  element = sessions.getEnclosingTimeslot_(element);
  var total = goog.dom.$('id_form-TOTAL_FORMS').value;

  var newElement = element.cloneNode(true);
  // we extract index of form from id = id_timeslot_XXX
  var index = element.id.substring(12);
  // we set the correct id on the new element
  newElement.id = 'id_timeslot_' + total;
  function input(node) {
    return (node.nodeName == goog.dom.TagName.INPUT ||
            node.nodeName == goog.dom.TagName.SELECT ||
            node.nodeName == goog.dom.TagName.TEXTAREA ||
            node.nodeName == goog.dom.TagName.UL ||
            node.nodeName == goog.dom.TagName.IMG);
  }
  var inputs = goog.dom.findNodes(newElement, input);

  for (var i = 0, node; node = inputs[i]; i++) {
    // Check if the node id is part of a form set or of interest to us.
    if (node.id.indexOf('id_form-') == -1) {
      continue;
    }
    // Format of id is 'id_' + name
    node.id = node.id.replace('-' + index + '-', '-' + total + '-');
    node.name = node.id.substring(3, node.id.length)

    if (node.name.indexOf('schedule_key') != -1) {
      // We don't clone the schedule key
      node.value = '';
    }
  }
  total++;

  goog.dom.$('id_form-TOTAL_FORMS').value = total;
  goog.dom.$('id_form-INITIAL_FORMS').value = total;

  // We insert the new element after the original one
  goog.dom.insertSiblingAfter(newElement, element);

  // Initialize the timeslot.
  sessions.initializeTimeslot_('id_form-' + (total - 1));
};


/**
 * Initialize javascript objects within a new timeslot section.
 *
 * @private
 * @param {string} formPrefix prefix of the formset id.
 */
sessions.initializeTimeslot_ = function(formPrefix) {
  // Add date pickers.
  sessions.addDatePicker(formPrefix + '-start_date');
  sessions.addDatePicker(formPrefix + '-end_date');

  // Add auto completes for locations.
  sessions.addAutoComplete_(formPrefix);

  // Create tooltip instances.
  var tooltip = 'The location where the instructor is present.';
  tooltip += 'Only one primary location is allowed.';
  sessions.createTooltip(formPrefix + '-tt-loc', tooltip);
  tooltip = 'Other locations that support VC or some connection';
  tooltip += ' to the primary room.'
  sessions.createTooltip(formPrefix + '-tt-loc-secondary', tooltip);
  tooltip = 'Specific details for a timeslot.';
  tooltip += ' This will be visible to students.';
  sessions.createTooltip(formPrefix + '-tt-notes', tooltip);
};


/**
 * Adds a date picker to input fields.
 *
 * @param {string} inputId ID of the input to decorate.
 * @export
 */
sessions.addDatePicker = function(inputId) {
  registerDateTimeConstants(goog.locale.DefaultDateTimeConstants, 'en');
  var PATTERN = 'yyyy-MM-dd';
  var formatter = new goog.i18n.DateTimeFormat(PATTERN);
  var parser = new goog.i18n.DateTimeParse(PATTERN);
  var picker = new goog.ui.InputDatePicker(formatter, parser);
  var input = goog.dom.getElement(inputId)
  picker.decorate(input);
};



sessions.getTimezoneElement_ = function(element) {
  element = sessions.getEnclosingTimeslot_(element);
  // drill down the timezone indicator from the timeslot
  function input(node) {
    return goog.dom.classes.has(node, 'timezone-indicator');
  }
  var results = goog.dom.findNodes(element, input);
  return results[0];
};


/**
 * Creates a new AutoComplete Input Handler. The handler works with two
 * list nodes. It adds its result to the first list when the result is not
 * already available on the other list.
 *
 * @private
 * @param {Element} textNode The node which contains text input.
 * @param {Element} listNodeSelf The list node which receives the result.
 * @param {Element} listNodeOther The other list node.
 * @param {boolean} singleSelectOnly If True, will allows only one value in the
 *          target list node.
 * @constructor
 * @extends {goog.ui.AutoComplete.InputHandler}
 */
sessions.CustomInputHandler_ = function(textNode, listNodeSelf,
        listNodeOther, singleSelectOnly) {
  goog.ui.AutoComplete.InputHandler.call(this, null, null, true);
  this.textNode = textNode;
  this.listNodeSelf = listNodeSelf;
  this.listNodeOther = listNodeOther;
  this.singleSelectOnly = singleSelectOnly;
};
goog.inherits(sessions.CustomInputHandler_,
              goog.ui.AutoComplete.InputHandler);


/**
 * Handles autocomplete user selection.
 *
 * @param {string} row the access point name that was selected by the user.
 */
sessions.CustomInputHandler_.prototype.selectRow = function(row) {
  this.textNode.value = '';
  sessions.addLocation_(row, this.listNodeSelf, this.listNodeOther,
                           this.singleSelectOnly);
};


/**
 * Adds a given access point name to the current list of locations shown.
 *
 * @private
 * @param {string} newLocationName name of the access point to be added.
 * @param {Element} listNodeSelf list node to which we need to add the
 *          room.
 * @param {Element} listNodeOther list node where we need to check for room
 *          duplicity.
 * @param {boolean} singleSelectOnly to add at most one location.
 */
sessions.addLocation_ = function(newLocationName, listNodeSelf,
        listNodeOther, singleSelectOnly) {
  var roomsSelf = sessions.getCurrentLocations_(listNodeSelf);
  var added = false;

  if (singleSelectOnly && roomsSelf.length > 0) {
    // we don t add location if a primary is already selected
    return;
  }

  var roomsOther = sessions.getCurrentLocations_(listNodeOther);
  var currentRooms = roomsSelf.concat(roomsOther)

  var foundRoom = false;
  for (var i = 0, room; room = currentRooms[i]; ++i) {
    if (newLocationName == room) {
      foundRoom = true;
    }
  }
  if (!foundRoom) {
    var li = goog.dom.createElement('li');

    var html = '<li><div><span>' + newLocationName;
    html += '</span><a class="remove-location" href="javascript:void;"'
    html += ' onClick="javascript:sessions.removeLocation(this)">';
    html += '</a></div></li>';
    li.innerHTML = html;

    listNodeSelf.appendChild(li);
    sessions.adjustLocationDisplayClass_(listNodeSelf);
    if (singleSelectOnly) {
      // only update timezones for primary location
      sessions.getTimezoneElement_(listNodeSelf).innerHTML =
          sessions.getAccessPointNameToTimezoneMap_()[newLocationName];
    }
  }
};


/**
 * Gets the string list of access point names that are currently selected.
 *
 * @private
 * @param {Element|Node} listNode holds the currents selected access point.
 * @return {Array.<string>} List of string room names that are currently
 *   selected.
 */
sessions.getCurrentLocations_ = function(listNode) {
  function spanFunc(node) {
    return node.nodeName == goog.dom.TagName.SPAN;
  }

  var roomNames = [];
  var spanNodes = goog.dom.findNodes(listNode, spanFunc);
  for (var i = 0, spanNode; spanNode = spanNodes[i]; ++i) {
    roomNames[i] = spanNode.textContent;
  }

  return roomNames;
};


/**
 * Removes a location from current selected list.
 *
 * @param {Element} element node whose parent contains the location to be
 *          removed.
 * @export
 */
sessions.removeLocation = function(element) {
  var liNode = element.parentNode.parentNode.parentNode;
  var listNode = liNode.parentNode;
  if (listNode.id.indexOf('_secondary') == -1) {
    sessions.getTimezoneElement_(element).innerHTML = '';
  }
  goog.dom.removeNode(liNode);
  sessions.adjustLocationDisplayClass_(listNode);
};


/**
 * Assign alternate 'even' and 'odd' classes to acccess point list for better
 * readability.
 *
 * @private
 * @param {Element} listNode holds the currents selected access point.
 */
sessions.adjustLocationDisplayClass_ = function(listNode) {
  var childNodes = listNode.childNodes;
  var classNames = ['even', 'odd'];
  for (var i = 0, child; child = childNodes[i]; ++i) {
    var addClass = classNames[i % 2];
    var removeClass = classNames[1 - (i % 2)];
    goog.dom.classes.remove(child, removeClass);
    goog.dom.classes.add(child, addClass);
  }
};


/**
 * Configure the custom location autocomplete UI.
 *
 * @private
 * @param {string} formPrefix prefix of the formset id.
 */
sessions.addAutoComplete_ = function(formPrefix) {
  var addAutoCompleteLocations = function(inputId, inputIdOther,
                                          singleSelectOnly) {
    var matcher = new goog.ui.AutoComplete.ArrayMatcher(
        sessions.accessPointNames_, true);
    var renderer = new goog.ui.AutoComplete.Renderer();

    var textNode = goog.dom.$(inputId + '-text');
    var listNodeSelf = goog.dom.$(inputId + '-list');
    var listNodeOther = goog.dom.$(inputIdOther + '-list');

    var inputHandler = new sessions.CustomInputHandler_(
            textNode, listNodeSelf, listNodeOther, singleSelectOnly)
    var ac = new goog.ui.AutoComplete(matcher, renderer, inputHandler);
    ac.setMaxMatches(16);

    inputHandler.attachAutoComplete(ac);
    inputHandler.attachInputs(textNode);
  };

  // Add auto complete for primary locations.
  addAutoCompleteLocations(formPrefix + '-access_points',
                           formPrefix + '-access_points_secondary', true);
  // Add auto complete for secondary locations.
  addAutoCompleteLocations(formPrefix + '-access_points_secondary',
                           formPrefix + '-access_points', false);
};


/**
 * Copy the locations from hidden form element on to session page dom.
 *
 * @private
 * @param {string} inputId id of the formset access points input.
 * @param {boolean} singleSelectOnly to copy at most one location.
 */
sessions.copyLocationsToUI_ = function(inputId, singleSelectOnly) {
  var inputNode = goog.dom.$(inputId);
  var listNode = goog.dom.$(inputId + '-list');

  var keyToNameMap = sessions.getAccessPointKeyToNameMap_();
  var inputKeys = inputNode.value.split(',');
  for (var i = 0, accessPointKey; accessPointKey = inputKeys[i]; ++i) {
    // If we cannot find a room name associated with access point key
    // then we use the access point key itself as the room name. This can happen
    // when  the room is not valid anymore and the models.ActivitySchedule still
    // has it.
    var roomName = keyToNameMap[accessPointKey];
    if (!roomName) {
      roomName = accessPointKey;
    }
    sessions.addLocation_(roomName, listNode, null, singleSelectOnly);
  }
};


/**
 * Copy all the session page location selections onto corresponding form hidden
 * elements.
 *
 * @private
 */
sessions.copyLocationsToForm_ = function() {
  function ulFunc(node) {
    return node.nodeName == goog.dom.TagName.UL;
  }

  var nameToKeyMap = sessions.getAccessPointNameToKeyMap_();
  var listNodesDiv = goog.dom.$$(null, 'list-add', null);
  for (var i = 0, listNodeDiv; listNodeDiv = listNodesDiv[i]; ++i) {
    var listNode = goog.dom.findNodes(listNodeDiv, ulFunc)[0];
    var currentRooms = sessions.getCurrentLocations_(listNode);

    var keyArray = new Array();
    for (var j = 0, currentRoom; currentRoom = currentRooms[j]; ++j) {
      // It is possible that the room name is actually an access point key.
      // This can happen when the access points room name is missing and the key
      // was used instead for display purposes.
      keyArray[j] = nameToKeyMap[currentRoom];
      if (!keyArray[j]) {
        keyArray[j] = currentRoom;
      }
    }

    // The list node's id should be of the form formPrefix+'access_points-list'
    // By removing '-list' we get the id of the form field that is used to
    // submit the access point keys.
    var inputNodeId = listNode.id.replace('-list', '');
    var inputNode = goog.dom.$(inputNodeId);
    inputNode.value = keyArray.join(',');
  }
};


/**
 * Creates a tooltip.
 *
 * @param {string} element Id of the element to add the tooltip.
 * @param {string} txt content Text of the tooltip.
 * @export
 */
sessions.createTooltip = function(element, txt) {
  new goog.ui.Tooltip(element, txt);
};


/**
 * Adds a listener that copies access point names into the form input on submit.
 *
 * @private
 * @param {string} submitButtonId Id of the form submit button.
 */
sessions.addSubmitListener_ = function(submitButtonId) {
  goog.events.listen(goog.dom.$(submitButtonId),
                     goog.events.EventType.CLICK,
                     goog.bind(sessions.copyLocationsToForm_, null));
};


/**
 * Stores access points key, name and timezone data for use in the module.
 *
 * @private
 * @param {Array.<string>} accessPointKeys all available access point key names.
 * @param {Array.<string>} accessPointNames all available access point names.
 * @param {Array.<string>} accessPointTimezones all available timezones that
 *   correspond to to accessPointNames.
 */
sessions.storeData_ = function(
    accessPointKeys, accessPointNames, accessPointTimezones) {
  sessions.accessPointKeys_ = accessPointKeys;
  sessions.accessPointNames_ = accessPointNames;
  sessions.accessPointTimezones_ = accessPointTimezones;
  sessions.accessPointNameToTimezoneMap_ = null;
  sessions.accessPointKeyToNameMap_ = null;
  sessions.accessPointNameToKeyMap_ = null;
};


/**
 * Provides an object that maps access point names to their timezone names.
 *
 * @private
 * @return {Object.<string>} an object that maps access point keys to their
 *   corresponding timezone names.
 */
sessions.getAccessPointNameToTimezoneMap_ = function() {
  if (!sessions.accessPointNameToTimezoneMap_) {
    sessions.accessPointNameToTimezoneMap_ = new Object();
    for (var i = 0, accessPoint; accessPoint = sessions.accessPointNames_[i];
         ++i) {
      sessions.accessPointNameToTimezoneMap_[accessPoint] =
          sessions.accessPointTimezones_[i];
    }
  }
  return sessions.accessPointNameToTimezoneMap_;
};


/**
 * Provides an object that maps access point keys to their corresponding names.
 *
 * @private
 * @return {Object.<string>} an object that maps access point keys to their
 *   corresponding names.
 */
sessions.getAccessPointKeyToNameMap_ = function() {
  if (!sessions.accessPointKeyToNameMap_) {
    sessions.accessPointKeyToNameMap_ = new Object();
    for (var i = 0, accessPointKey;
         accessPointKey = sessions.accessPointKeys_[i]; ++i) {
      sessions.accessPointKeyToNameMap_[accessPointKey] =
          sessions.accessPointNames_[i];
    }
  }
  return sessions.accessPointKeyToNameMap_;
};


/**
 * Provides an object that maps access point names to their corresponding keys.
 *
 * @private
 * @return {Object.<string>} an object that maps access point names to their
 *   corresponding keys.
 */
sessions.getAccessPointNameToKeyMap_ = function() {
  if (!sessions.accessPointNameToKeyMap_) {
    sessions.accessPointNameToKeyMap_ = new Object();
    for (var i = 0, accessPointName;
         accessPointName = sessions.accessPointNames_[i]; ++i) {
      sessions.accessPointNameToKeyMap_[accessPointName] =
          sessions.accessPointKeys_[i];
    }
  }
  return sessions.accessPointNameToKeyMap_;
};


/**
 * Initialize the session page and add UI elements to formsets.
 *
 * This function has to be called before using the rest of the functions.
 *
 * @param {number} totalFormsets the number of formsets in the page.
 * @param {Array.<string>} accessPointKeys all available access point key names.
 * @param {Array.<string>} accessPointNames all available access point names.
 * @param {Array.<string>} accessPointTimezones all available timezones that
 *   correspond to to accessPointNames.
 * @export
 */
sessions.initializePage = function(totalFormsets, accessPointKeys,
                                      accessPointNames, accessPointTimezones) {
  sessions.storeData_(accessPointKeys, accessPointNames,
      accessPointTimezones);

  sessions.addDatePicker('id_form-0-register_end_date');

  for (var i = 0; i < totalFormsets; i++) {
    if (!sessions.processDeletedTimeslot_('id_timeslot_' + i)) {
      var formPrefix = 'id_form-' + i;
      sessions.initializeTimeslot_(formPrefix);
      sessions.copyLocationsToUI_(formPrefix + '-access_points', true);
      sessions.copyLocationsToUI_(
          formPrefix + '-access_points_secondary', false);
    }
  }

  var tooltipText = goog.string.buildString(
      'A timeslot represents a scheduled block for a session.',
      ' You can schedule multiple timeslots for one session.',
      ' For example, you can create a multi-day session by creating a',
      ' timeslot for each day.'
  );
  sessions.createTooltip('id-adding-timeslots', tooltipText);

  var tooltipText2 = goog.string.buildString(
      'Reserve rooms on the calendar for each individual timeslot.',
      ' Private rooms and rooms needing special privileges cannot be booked.'
  );
  sessions.createTooltip('id-reserve-rooms', tooltipText2);

  var tooltipText3 = goog.string.buildString(
      'If unchecked the session is made invisible. If checked the session',
      ' inherits the visibility setting of the activity.'
  );
  sessions.createTooltip('id-visible', tooltipText3);

  sessions.addSubmitListener_('id_submit_forms');
};
