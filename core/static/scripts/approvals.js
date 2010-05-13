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
 * @fileoverview Collection of methods to handle manager approvals.
*
 */

goog.provide('approvals');
goog.require('dialog');

goog.require('goog.dom');


/**
 * Toggles between selecting everything and selecting nothing in approvals page.
 *
 * @export
 */
approvals.toggleAllPendingApprovals = function() {
  var masterSelect = goog.dom.$('id-select-all');
  var checked = masterSelect.checked;

  // Set all pending approval.
  var listSelect = goog.dom.$$(null, 'approve-select', null);
  for (var i = 0, select; select = listSelect[i]; ++i) {
    select.checked = checked;
  }
};


/**
 * Submits manager approval choices.
 *
 * @param {boolean} isApprove true if manager approves, false if declined.
 * @export
 */
approvals.submitManagerApprovals = function(isApprove) {
  // Get approvals that were selected.
  var idList = new Array();
  var listSelect = goog.dom.$$(null, 'approve-select', null);
  for (var i = 0, select; select = listSelect[i]; ++i) {
    if (select.checked) {
      idList.push(select.id);
    }
  }

  approvals.submitManagerApprovalsForIds_(idList, isApprove);
};


/**
 * Submits manager approval for a given approval id.
 *
 * @param {string} approveId for which to submit approval.
 * @param {boolean} isApprove true if manager approves, false if declined.
 * @export
 */
approvals.submitManagerApprovalForId = function(approveId, isApprove) {
  var idList = [approveId];
  approvals.submitManagerApprovalsForIds_(idList, isApprove);
};


/**
 * Submits manager approval for given approval ids.
 *
 * @private
 * @param {Array.<string>} idList array of approval ids.
 * @param {boolean} isApprove true if manager approves, false if declined.
 */
approvals.submitManagerApprovalsForIds_ = function(idList, isApprove) {
  if (idList.length) {
    goog.dom.$('id-approval-keys').value = idList.join(',');
    var approve = '0';
    if (isApprove) {
      approve = '1';
    }
    goog.dom.$('id-approve').value = approve;
    goog.dom.$('id-approval-form').submit();
  }
  else {
    dialog.showConfirm('No student selected.');
  }
};
