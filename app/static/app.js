loadSummary();
'use strict';

// Feedback board client. Lists feedback, submits new items, toggles completion,
// and polls the API so a second browser stays in sync.
//
// The initial summary refresh is the first statement the script runs, so the
// counts are requested as soon as the script executes; loadSummary is a hoisted
// function declaration, so calling it before its definition is safe.

var FORM_ID = 'feedback-form';
var LIST_ID = 'feedback-list';
var EMPTY_ID = 'empty-state';
var STATUS_ID = 'form-status';
var POLL_MS = 2000;

var form = document.getElementById(FORM_ID);
var list = document.getElementById(LIST_ID);
var emptyState = document.getElementById(EMPTY_ID);
// Bind the status region with `let`, not `var`: a top-level `var status` is the
// native `Window.status` property (a string), which would silently coerce this
// element and break every setStatus write. `let` keeps it a block-scoped local
// so the element reference survives.
let status = document.getElementById(STATUS_ID);

// -- Filter state ------------------------------------------------------------
// The active filter is page-scope memory only: a single module-local variable,
// never mirrored into the URL or into storage, so two browsers on the same
// board filter independently. It is written only by the filter control and read
// by loadFeedback/renderItems; polling and successful create/complete re-read
// it, so the selection survives them.
var FILTER_ALL = 'all';
var currentFilter = FILTER_ALL;

var FILTER_CONTROL_IDS = {
  all: 'filter-all',
  open: 'filter-open',
  completed: 'filter-completed'
};

var FILTER_QUERY = { all: null, open: 'open', completed: 'completed' };

// Identity of the empty message per filter. All keeps the historical generic
// copy so an empty board reads exactly as before; the narrowed filters say
// which filter produced the empty list.
var EMPTY_MESSAGES = {
  all: 'No feedback yet. Add the first item using the form above.',
  open: 'No open feedback right now. Everything submitted has been completed.',
  completed: 'No completed feedback yet. Mark an item complete and it will show here.'
};

function emptyMessageFor(filter) {
  return EMPTY_MESSAGES[filter] || EMPTY_MESSAGES[FILTER_ALL];
}

// Build the board GET for the active filter. All omits the status parameter
// entirely (byte-compatible with the legacy request); open/completed append the
// single status query parameter the backend contract accepts.
function feedbackUrl(filter) {
  var wanted = FILTER_QUERY[filter];
  return wanted === null ? '/feedback' : '/feedback?status=' + wanted;
}

// Resolve a filter-control id back to the filter it selects. The reverse of
// FILTER_CONTROL_IDS; anything outside the three controls resolves to null.
var FILTER_BY_CONTROL_ID = {};
Object.keys(FILTER_CONTROL_IDS).forEach(function (filter) {
  FILTER_BY_CONTROL_ID[FILTER_CONTROL_IDS[filter]] = filter;
});

// -- Filter control ----------------------------------------------------------
// Exactly one filter control is armed at a time: the active tab reports
// aria-pressed="true" and, for observer parity, carries the is-active class,
// while every other control is forced off. This makes the pressed state a
// truthful, addressable expression of the page-scope currentFilter.
function setActiveFilterControl(filter) {
  Object.keys(FILTER_CONTROL_IDS).forEach(function (name) {
    var control = document.getElementById(FILTER_CONTROL_IDS[name]);
    if (!control) {
      return;
    }
    var active = name === filter;
    control.setAttribute('aria-pressed', active ? 'true' : 'false');
    if (control.classList) {
      control.classList.toggle('is-active', active);
    }
  });
}

// Apply a selected filter. The filter is page-scope memory only: nothing is
// written to the URL or to storage, so two browsers on the same board may hold
// different selections independently. Re-selecting the active filter is a
// no-op that issues no requests; this keeps a switch from disturbing an
// in-flight submit or the typed draft, because this path never resets the
// form, touches the submit guard, or sets the status message.
function applyFilter(filter) {
  if (filter !== FILTER_ALL && filter !== 'open' && filter !== 'completed') {
    return;
  }
  if (filter === currentFilter) {
    return;
  }
  currentFilter = filter;
  setActiveFilterControl(filter);
  // Refresh the board and the whole-board counters for the new selection. The
  // counters stay whole-board, so a switch never narrows them.
  loadSummary();
  loadFeedback().catch(function () {
    // Stay quiet on transient filter-switch errors; the next poll retries.
  });
}

// The filter buttons are bound directly by id. A delegation fallback on the
// shared #feedback-filter root covers a document that renders the buttons
// without ids, so the control is still addressable either way. Both paths read
// the same three ids and call applyFilter, so they cannot diverge.
function bindFilterControls() {
  Object.keys(FILTER_CONTROL_IDS).forEach(function (name) {
    var control = document.getElementById(FILTER_CONTROL_IDS[name]);
    if (!control) {
      return;
    }
    control.addEventListener('click', function () {
      applyFilter(name);
    });
  });

  var root = document.getElementById('feedback-filter');
  if (root && root.addEventListener) {
    root.addEventListener('click', function (event) {
      var target = event && event.target;
      var id = target && target.id;
      if (id && FILTER_BY_CONTROL_ID[id]) {
        applyFilter(FILTER_BY_CONTROL_ID[id]);
      }
    });
  }
}

bindFilterControls();
setActiveFilterControl(currentFilter);

// -- Sort state --------------------------------------------------------------
// The active sort order is page-scope memory only: a single module-local
// variable, never mirrored into the URL or into storage, so two browsers on the
// same board sort independently. It is written only by the sort control and read
// by renderItems; polling, filter changes and successful create/complete all
// re-render, so the selection survives them.
var SORT_ID = 'sort-feedback';
var SORT_NEWEST = 'newest-first';
var SORT_OLDEST = 'oldest-first';
// The active order mirrors the control. On load the select's own value is
// adopted, so the markup ships Newest first as the default; a document without
// the control (or with an unrecognised value) keeps the natural fetched order,
// so the legacy board renders exactly as before and the historical DOM shape
// stays byte-compatible.
var currentSort = null;
// The last board the active filter produced, used to re-render on a sort switch
// without a refetch. It is only ever a reference to the freshly fetched array.
var lastItems = [];

// Order the rendered rows by the numeric feedback id: descending for Newest
// first, ascending for Oldest first. Sorting always uses the number, never a
// timestamp, the fetched order, a string compare, the URL or storage. The
// fetched array is never mutated: the rows are copied before they are ordered,
// so an unfiltered "all" response is left byte-for-byte as it arrived and a
// caller that reuses the array sees no reorder.
function sortedForView(items) {
  var rows = items.slice();
  if (currentSort !== SORT_NEWEST && currentSort !== SORT_OLDEST) {
    return rows;
  }
  rows.sort(function (a, b) {
    return currentSort === SORT_OLDEST ? a.id - b.id : b.id - a.id;
  });
  return rows;
}

// Apply a selected sort order. The order is page-scope memory only: nothing is
// written to the URL or to storage, and re-selecting the active order is a
// no-op. A switch re-renders the rows already on screen for the active filter
// from the last fetched board, so it never refetches, never resets the form,
// never touches the submit guard and never disturbs an in-flight submit or the
// typed draft. (The next poll re-renders into the same order.)
function applySort(sort) {
  if (sort !== SORT_NEWEST && sort !== SORT_OLDEST) {
    return;
  }
  if (sort === currentSort) {
    return;
  }
  currentSort = sort;
  renderItems(lastItems);
}

// Bind the native select's change event. The control is addressed by id so a
// document that omits it (or an older page) keeps the natural fetched order
// without error. The select's shipped value is adopted as the starting order --
// the markup selects Newest first -- so the default view is Newest first while
// an unrecognised starting value simply stays natural until the user chooses.
function bindSortControl() {
  var control = document.getElementById(SORT_ID);
  if (!control || !control.addEventListener) {
    return;
  }
  if (control.value === SORT_NEWEST || control.value === SORT_OLDEST) {
    currentSort = control.value;
  }
  control.addEventListener('change', function () {
    applySort(control.value);
  });
}

bindSortControl();

function setStatus(message, isError) {
  status.textContent = message || '';
  status.classList.toggle('is-error', Boolean(isError));
}

function renderItems(items) {
  // Remember the last board the active filter produced so a sort switch can
  // re-render it without refetching (and without touching the draft or guard).
  lastItems = items || [];
  list.innerHTML = '';
  if (!items.length) {
    // The message names the active filter, so an empty filtered result explains
    // itself rather than reusing the generic "no feedback yet" copy.
    emptyState.textContent = emptyMessageFor(currentFilter);
    emptyState.hidden = false;
    return;
  }
  emptyState.hidden = true;
  sortedForView(items).forEach(function (item) {
    var entry = document.createElement('li');
    entry.className = 'feedback-item' + (item.completed ? ' is-complete' : '');

    var label = document.createElement('span');
    label.className = 'feedback-title';
    label.textContent = item.title;
    entry.appendChild(label);

    var toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'complete-button';
    toggle.textContent = item.completed ? 'Completed' : 'Mark complete';
    toggle.disabled = item.completed;
    toggle.addEventListener('click', function () {
      completeItem(item.id);
    });
    entry.appendChild(toggle);

    list.appendChild(entry);
  });
}

// Fetch the board for the active filter. The filter is captured when the
// request is issued; when the response resolves the client discards it if the
// active filter has since changed, so a slow poll under a previous filter can
// never repaint the current view (and never paints a body the user no longer
// asked for).
function loadFeedback() {
  var requestedFilter = currentFilter;
  return fetch(feedbackUrl(requestedFilter), { headers: { Accept: 'application/json' } })
    .then(function (response) {
      if (!response.ok) {
        throw new Error('Unable to load feedback right now.');
      }
      return response.json();
    })
    .then(function (data) {
      if (requestedFilter !== currentFilter) {
        return;
      }
      renderItems(data.items || []);
    });
}

// Read the board counts into the accessible summary region. The region is
// resolved first so a board served without it stays inert, and it reports
// aria-busy while the counts are in flight. Transient failures keep the
// previous counts; the next refresh retries.
function loadSummary() {
  var region = document.getElementById('feedback-summary');
  if (!region) {
    return Promise.resolve();
  }
  region.setAttribute('aria-busy', 'true');
  return fetch('/feedback/summary', { headers: { Accept: 'application/json' } })
    .then(function (response) {
      if (!response.ok) {
        throw new Error('Unable to load the summary right now.');
      }
      return response.json();
    })
    .then(function (data) {
      region.querySelector('#summary-total').textContent = data.total;
      region.querySelector('#summary-open').textContent = data.open;
      region.querySelector('#summary-completed').textContent = data.completed;
    })
    .catch(function () {
      // Stay quiet on transient summary errors; the next refresh retries.
    })
    .then(function () {
      region.setAttribute('aria-busy', 'false');
    });
}

function completeItem(id) {
  return fetch('/feedback/' + id + '/complete', { method: 'POST' })
    .then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          throw new Error(data.error || 'Unable to update that item.');
        }
        return data;
      });
    })
    .then(function () {
      loadSummary();
      return loadFeedback();
    })
    .catch(function (error) {
      setStatus(error.message, true);
    });
}

// The form's Submit control and a pending guard. While a valid submission POST
// is in flight the button is disabled and further submit events -- including
// programmatically dispatched ones -- are ignored, so exactly one POST is issued
// per attempt. The guard is cleared on every exit path (success, HTTP failure or
// transport failure) so a later attempt can proceed; empty-title validation
// returns before the guard is set, so it never locks the form.
var submitButton = form.querySelector('button[type="submit"]');
var isSubmitting = false;

// Announce the pending state to assistive technology on the form itself: the
// attribute is the string 'false' at rest and 'true' only while a valid POST
// is unresolved. It is written on the same transitions as the guard, so every
// exit path (success, HTTP failure, transport failure) closes it and a later
// retry re-announces 'true'.
function setBusy(pending) {
  form.setAttribute('aria-busy', pending ? 'true' : 'false');
}

function setSubmitting(pending) {
  isSubmitting = pending;
  if (submitButton) {
    submitButton.disabled = pending;
  }
  setBusy(pending);
}

setBusy(false);

function submitFeedback(event) {
  event.preventDefault();

  if (isSubmitting) {
    return;
  }

  var title = form.elements.title.value.trim();
  var description = form.elements.description.value.trim();

  if (!title) {
    setStatus('Please enter a title before submitting.', true);
    return;
  }

  setSubmitting(true);
  setStatus('Submitting...', false);
  fetch('/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: title, description: description })
  })
    .then(function (response) {
      return response.json().catch(function () { return {}; }).then(function (data) {
        if (!response.ok) {
          throw new Error(data.error || 'Unable to submit feedback.');
        }
        return data;
      });
    })
    .then(function () {
      form.reset();
      setStatus('Thanks! Your feedback was added.', false);
      loadSummary();
      return loadFeedback();
    })
    .catch(function (error) {
      setStatus(error.message, true);
    })
    .then(function () {
      setSubmitting(false);
    });
}

form.addEventListener('submit', submitFeedback);

// Keyboard dismissal. A keydown with key 'Escape' that bubbles to the form// dismisses the current status message and its is-error class -- but only while
// no submission is pending, so the 'Submitting...' message stays visible for an
// unresolved POST and the pending guard (button, aria-busy, POST) is untouched.
// Clearing reuses setStatus, which coerces the text and toggles is-error off;
// typed title/description, the board, focus and the enabled button are left
// exactly as they were, and no submit, reload or form reset occurs. Any other
// key falls through, and a repeated Escape with an empty status is a no-op.
function dismissStatusOnEscape(event) {
  if (event.key !== 'Escape') {
    return;
  }
  if (isSubmitting) {
    return;
  }
  setStatus('', false);
}

form.addEventListener('keydown', dismissStatusOnEscape);

loadFeedback().catch(function (error) {
  setStatus(error.message, true);
});

// Poll so every open board reflects changes made in another browser.
setInterval(function () {
  loadSummary();
  loadFeedback().catch(function () {
    // Stay quiet on transient polling errors; the next tick retries.
  });
}, POLL_MS);
