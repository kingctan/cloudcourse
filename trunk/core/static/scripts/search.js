// Copyright 2010 Google Inc. All Rights Reserved.
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
 * @fileoverview Functions required for the search UI.
*
 */

goog.provide('search');

goog.require('goog.date');
goog.require('goog.dom');
goog.require('goog.dom.classes');
goog.require('goog.string');


/**
 * Show/hide advanced search options.
 *
 * @param {boolean} show true to show and false to hide advanced Search.
 * @export
 */
search.showAdvancedSearch = function(show) {
  var advancedSearchDiv = goog.dom.$('advanced-search-div');
  var showAdvancedSearch = goog.dom.$('show-advanced-search');
  var hideAdvancedSearch = goog.dom.$('hide-advanced-search');
  if (show) {
    goog.dom.classes.remove(advancedSearchDiv, 'hidden');
    goog.dom.classes.remove(hideAdvancedSearch, 'hidden');
    goog.dom.classes.add(showAdvancedSearch, 'hidden');
  } else {
    goog.dom.classes.add(advancedSearchDiv, 'hidden');
    goog.dom.classes.add(hideAdvancedSearch, 'hidden');
    goog.dom.classes.remove(showAdvancedSearch, 'hidden');
  }

  // Make sure to reset any advanced settings.
  search.clearAdvancedOptions(true);
};


/**
 * Add locations to the locations select form input.
 *
 * @param {Array.<string>} searchLocations locations user can filter on.
 * @param {string} selectedLocation location to choose by default.
 * @export
 */
search.initializeLocations = function(searchLocations, selectedLocation) {
  var searchLocationsSelect = goog.dom.$('id-search-locations');

  // Clear any existing locations.
  goog.dom.removeChildren(searchLocationsSelect);

  var attributes = {'value': '', 'id': 'id-search-location-empty'};
  var option = goog.dom.createDom('option', attributes, 'Select a location');
  goog.dom.appendChild(searchLocationsSelect, option);

  for (var i = 0, searchLocation; searchLocation = searchLocations[i]; ++i) {
    var attributes_ = {'value': searchLocation};
    attributes_.id = 'id-search-location-' + searchLocation;
    if (searchLocation == selectedLocation) {
      attributes_.selected = 'selected';
    }
    var option_ = goog.dom.createDom('option', attributes_, searchLocation);
    goog.dom.appendChild(searchLocationsSelect, option_);
  }
};


/**
 * Submits the search form.
 *
 * @param {string} searchLocation location user wants to filter search on.
 * @param {boolean} limitMonth set time filter up to a month from now.
 * @export
 */
search.submitSearch = function(searchLocation, limitMonth) {
  if (searchLocation) {
    var selectOption = goog.dom.$('id-search-location-' + searchLocation);
    if (selectOption) {
      selectOption.selected = true;
    } else {
      goog.dom.$('id-search-location-empty').selected = true;
    }
  }
  if (limitMonth) {
    var today = new goog.date.Date();
    var monthInterval = new goog.date.Interval(goog.date.Interval.MONTHS, 1);
    var monthLater = new goog.date.Date();
    monthLater.add(monthInterval);
    goog.dom.$('id-search-start-date').value = search.dateToStr_(today);
    goog.dom.$('id-search-end-date').value = search.dateToStr_(
        monthLater);
  }
  goog.dom.$('id-search-form').submit();
};


/**
 * Clears the advanced search options if advanced options is not shown in UI or
 * if asked to forcibly clear them using the forceClear parameter.
 *
 * @param {boolean} forceClear clear the advanced options without checking.
 * @export
 */
search.clearAdvancedOptions = function(forceClear) {
  if (forceClear ||
      goog.dom.classes.has(goog.dom.$('advanced-search-div'), 'hidden')) {
    goog.dom.$('id-search-location-empty').selected = true;
    goog.dom.$('id-search-start-date').value = '';
    goog.dom.$('id-search-end-date').value = '';
  }
};


/**
 * Converts date to yyyy-mm-dd format.
 *
 * @param {goog.date.Date} dateObj date to convert to yyyy-mm-dd format.
 * @return {string} yyyy-mm-dd formatted string.
 * @private
 */
search.dateToStr_ = function(dateObj) {
  var dateStr = goog.string.buildString(
      dateObj.getFullYear(), '-',
      goog.string.padNumber(dateObj.getMonth() + 1, 2), '-',
      goog.string.padNumber(dateObj.getDate(), 2));
  return dateStr;
};
