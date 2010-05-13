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
 * @fileoverview Creates common editor.
*
 */
goog.provide('editor');
goog.require('goog.dom');
goog.require('goog.editor.Field');
goog.require('goog.editor.plugins.BasicTextFormatter');
goog.require('goog.editor.plugins.LinkDialogPlugin');
goog.require('goog.editor.plugins.UndoRedo');
goog.require('goog.locale');
goog.require('goog.ui.Tooltip');
goog.require('goog.ui.editor.DefaultToolbar');
goog.require('goog.ui.editor.ToolbarController');


/**
 * Create common editor for selected DIV.
 *
 * @param {string} fieldId DIV id of editable contents.
 * @param {string} toolbarId DIV id of toolbar.
 * @param {string} inputId INPUT id of the form description field.
 * @param {string} submitId SUBMIT id of the form.
 * @constructor
 * @export
 */
editor.Editor = function(fieldId, toolbarId, inputId, submitId) {
  /**
   * Element ID that editor's content will be placed.
   *
   * @type {string}
   * @private
   */
  this.fieldId_ = fieldId;

  /**
   * Element ID that editor's toolbar will be placed.
   *
   * @type {string}
   * @private
   */
  this.toolbarId_ = toolbarId;

  /**
   * Element ID that of the input field.
   *
   * @type {string}
   * @private
   */
  this.inputId_ = inputId;

  /**
   * Element ID that of the submit button.
   *
   * @type {string}
   * @private
   */
  this.submitId_ = submitId;

  /**
   * Editable field object.
   *
   * @type {TR_EditableField}
   * @private
   */
  this.field_;

  /**
   * Editable toolbar object.
   *
   * @type {TR_EditorToolbar}
   * @private
   */
  this.editorToolbar_;

  this.field_ = new goog.editor.Field(this.fieldId_);
  // Add toolbar and link it to editable field.
  var toolbar = goog.ui.editor.DefaultToolbar.makeDefaultToolbar(
      goog.dom.$(this.toolbarId_));
  this.editorToolbar_ = new goog.ui.editor.ToolbarController(
      this.field_, toolbar, goog.locale.getLocale());

  // Add plugins
  this.field_.registerPlugin(new goog.editor.plugins.BasicTextFormatter());
  this.field_.registerPlugin(new goog.editor.plugins.UndoRedo());
  this.field_.makeEditable();
  /**
   * For form edits, take the initial data from the hidden description field and
   * copy it on the editor.
   */
  this.field_.setHtml(false, goog.dom.$(inputId).value);

  /**
   * Add submit listener to copy the data from the editor back to the
   * hidden description form field.
   */
  goog.events.listen(goog.dom.$(this.submitId_), goog.events.EventType.CLICK,
                     goog.bind(this.copyToFormField, this));
};


/**
 * Copies content of editor to form field.
 */
editor.Editor.prototype.copyToFormField = function() {
  var contents = this.field_.getCleanContents();
  goog.dom.$(this.inputId_).value = contents;
};


/**
 * Creates a tooltip.
 *
 * @param {string} element Id of the element to add the tooltip.
 * @param {string} txt Text of the tooltip.
 * @export
 */
editor.createTooltip = function(element, txt) {
  new goog.ui.Tooltip(element, txt);
};
