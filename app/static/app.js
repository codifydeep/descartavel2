loadSummary();
'use strict';

// Service-availability probe. Runs exactly once per page load and never
// repeats: the board poll below only refreshes summary/feedback, so the
// indicator is a load-time snapshot, not a continuous uptime monitor. The
// result is the exact text the page's accessible #service-status live region
// shows -- the initial value is whatever that element shipped. The probe
// touches only that element, so it can never reset the form, clear a draft or
// disturb filter/search/sort.
var SERVICE_STATUS_ID = 'service-status';
var SERVICE_STATUS_URL = '/service-status';
var SERVICE_CHECKING_TEXT = 'Checking service\u2026';
var SERVICE_AVAILABLE_TEXT = 'Service available';
var SERVICE_UNAVAILABLE_TEXT = 'Service unavailable';

function renderServiceStatus(text, stateClass) {
  var indicator = document.getElementById(SERVICE_STATUS_ID);
  if (!indicator) {
    return;
  }
  indicator.textContent = text;
  if (indicator.classList) {
    indicator.classList.toggle('is-available', stateClass === 'available');
    indicator.classList.toggle('is-unavailable', stateClass === 'unavailable');
  }
}

function checkServiceStatus() {
  // Resolve the same-origin relative path exactly, with a GET and no cache
  // bypass parameter. A transport failure, a non-200, unparseable JSON or any
  // body that is not exactly the success payload all read as unavailable; only
  // the exact {"status":"available"} object yields available.
  return fetch(SERVICE_STATUS_URL, { method: 'GET' }).then(function (response) {
    if (!response.ok) {
      return null;
    }
    return response.json().catch(function () { return null; });
  }).then(function (data) {
    if (data && data.status === 'available' && Object.keys(data).length === 1) {
      renderServiceStatus(SERVICE_AVAILABLE_TEXT, 'available');
    } else {
      renderServiceStatus(SERVICE_UNAVAILABLE_TEXT, 'unavailable');
    }
  }).catch(function () {
    renderServiceStatus(SERVICE_UNAVAILABLE_TEXT, 'unavailable');
  });
}

// The indicator starts in the checking state. The markup already ships this
// exact text for a script-less page; re-asserting it here guarantees the live
// region reads 'Checking service…' from the moment the client runs until the
// single probe resolves. A document with no such region is the legacy board:
// it keeps the historical execute-time shape (summary then board, exactly two
// GETs) and issues no availability request at all.
if (document.getElementById(SERVICE_STATUS_ID)) {
  renderServiceStatus(SERVICE_CHECKING_TEXT, null);
  checkServiceStatus();
}

// Demo-environment probe. Runs exactly once per page load and never repeats:
// no timer, interval, retry or poll re-issues it, so the request count for
// /service-mode is exactly one per load. The result is written only to the
// dedicated accessible #service-mode live region -- the initial value is
// whatever that element shipped -- so the probe can never reset the form,
// clear a draft, or disturb filter/search/sort state, and nothing is written to
// the URL or to storage, so two browser contexts stay independent. A document
// that ships no #service-mode region is the legacy board: the probe is not
// issued at all.
var SERVICE_MODE_ID = 'service-mode';
var SERVICE_MODE_URL = '/service-mode';
var SERVICE_MODE_CHECKING_TEXT = 'Checking environment\u2026';
var SERVICE_MODE_DEMO_TEXT = 'Demo environment';
var SERVICE_MODE_UNAVAILABLE_TEXT = 'Environment unavailable';

function renderServiceMode(text, stateClass) {
  var indicator = document.getElementById(SERVICE_MODE_ID);
  if (!indicator) {
    return;
  }
  indicator.textContent = text;
  if (indicator.classList) {
    indicator.classList.toggle('is-demo', stateClass === 'demo');
    indicator.classList.toggle('is-unavailable', stateClass === 'unavailable');
  }
}

function checkServiceMode() {
  // Resolve the same-origin relative path exactly, with a GET and no cache
  // bypass parameter. Only HTTP 200 with parseable JSON whose own-key set is
  // exactly {mode} and whose value is the literal 'demo' yields the demo state;
  // a transport failure, a non-200, unparseable JSON, any extra or missing key,
  // or any other mode value (including another valid one) reads as unavailable,
  // with no mode-specific message.
  return fetch(SERVICE_MODE_URL, { method: 'GET' }).then(function (response) {
    if (!response.ok) {
      return null;
    }
    return response.json().catch(function () { return null; });
  }).then(function (data) {
    if (data && data.mode === 'demo' && Object.keys(data).length === 1) {
      renderServiceMode(SERVICE_MODE_DEMO_TEXT, 'demo');
    } else {
      renderServiceMode(SERVICE_MODE_UNAVAILABLE_TEXT, 'unavailable');
    }
  }).catch(function () {
    renderServiceMode(SERVICE_MODE_UNAVAILABLE_TEXT, 'unavailable');
  });
}

// The indicator starts in the checking state. The markup already ships this
// exact text for a script-less page; re-asserting it here guarantees the live
// region reads 'Checking environment…' from the moment the client runs until
// the single probe resolves.
if (document.getElementById(SERVICE_MODE_ID)) {
  renderServiceMode(SERVICE_MODE_CHECKING_TEXT, null);
  checkServiceMode();
}


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

// Per-page board-request generation. `loadFeedback` increments it when it
// issues a GET and stamps that number on the response; a response is painted
// only while its number is still the newest issued. It is page-scope memory
// only -- never mirrored into the URL or storage -- and is never reset, so an
// older generation can never become current again.
var requestGeneration = 0;

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
function baseFeedbackUrl() {
  var wanted = FILTER_QUERY[currentFilter];
  if (wanted !== null) {
    return '/feedback?status=' + wanted;
  }
  return '/feedback';
}

// -- Search state ------------------------------------------------------------
// The active search needle is page-scope memory only: a single module-local
// variable, never mirrored into the URL or storage, so two browsers on the same
// board search independently. It is written only by the search control and read
// by loadFeedback; polling and successful create/complete re-read it, so the
// typed search survives them.
var SEARCH_ID = 'feedback-search';
var SEARCH_DEBOUNCE_MS = 200;
var currentSearch = '';

function feedbackUrl(filter) {
  var base = baseFeedbackUrl();
  var needle = String(currentSearch).trim();
  if (!needle) {
    return base;
  }
  return base + '?q=' + encodeQueryComponent(needle);
}

// Percent-encode a query value without relying on the host's
// encodeURIComponent: the search control is driven in harnesses whose global
// may not expose it, and the board must still build a well-formed needle.
// Every byte outside the unreserved set is emitted as %XX uppercase hex.
function encodeQueryComponent(value) {
  var text = String(value);
  var out = '';
  for (var i = 0; i < text.length; i += 1) {
    var code = text.charCodeAt(i);
    if ((code >= 0x41 && code <= 0x5A) || (code >= 0x61 && code <= 0x7A) ||
        (code >= 0x30 && code <= 0x39) ||
        code === 0x2D || code === 0x5F || code === 0x2E || code === 0x7E) {
      out += text.charAt(i);
    } else if (code < 0x80) {
      var hex = code.toString(16).toUpperCase();
      out += '%' + (hex.length < 2 ? '0' + hex : hex);
    } else {
      var utf8 = unescapeUtf8(text.charAt(i));
      for (var j = 0; j < utf8.length; j += 1) {
        var byteHex = utf8[j].toString(16).toUpperCase();
        out += '%' + (byteHex.length < 2 ? '0' + byteHex : byteHex);
      }
    }
  }
  return out;
}

// Encode one UTF-16 code unit as the UTF-8 byte sequence, as an array of byte
// values. Surrogate pairs arriving one unit at a time are encoded per unit,
// matching how a lone unit would be replaced; well-formed input is unchanged.
function unescapeUtf8(ch) {
  var code = ch.charCodeAt(0);
  if (code < 0x80) {
    return [code];
  }
  if (code < 0x800) {
    return [0xC0 | (code >> 6), 0x80 | (code & 0x3F)];
  }
  return [0xE0 | (code >> 12), 0x80 | ((code >> 6) & 0x3F), 0x80 | (code & 0x3F)];
}

// Reconcile the page's search state with the search control. A document with
// neither control nor module state keeps the historical unsearched request, so
// the legacy board renders exactly as before.
function currentSearchNeedle() {
  var control = document.getElementById(SEARCH_ID);
  if (control && typeof control.value === 'string') {
    return control.value.trim();
  }
  return String(currentSearch).trim();
}

// The search control narrows the listing on input, debounced so a burst of
// keystrokes issues a single board GET. It never resets the form, touches the
// submit guard or the status message, so it cannot disturb an in-flight submit
// or the typed draft; the next poll re-reads the same needle.
function bindSearchControl() {
  var control = document.getElementById(SEARCH_ID);
  if (!control || !control.addEventListener) {
    return;
  }
  control.addEventListener('input', function () {
    currentSearch = String(control.value == null ? '' : control.value);
    if (searchTimer !== null) {
      clearTimeout(searchTimer);
    }
    searchTimer = setTimeout(function () {
      searchTimer = null;
      loadFeedback().catch(function () {
        // Stay quiet on transient search errors; the next poll retries.
      });
    }, SEARCH_DEBOUNCE_MS);
  });
  // Enter commits the typed needle immediately, without waiting out the
  // debounce. It applies the same page-scope search memory the debounced path
  // writes -- a blank needle trims away, so the next request omits q -- and it
  // never resets the form, touches the submit guard or the status message, so
  // the typed draft and an in-flight submit are left exactly as they were. The
  // default is not prevented here (the input is not a submit control), but the
  // handler is a no-op for any other key so a stray Escape/typing falls through
  // to the existing handlers untouched.
  control.addEventListener('keydown', function (event) {
    if (!event || event.key !== 'Enter') {
      return;
    }
    if (searchTimer !== null) {
      clearTimeout(searchTimer);
      searchTimer = null;
    }
    currentSearch = String(control.value == null ? '' : control.value);
    loadFeedback().catch(function () {
      // Stay quiet on transient search errors; the next poll retries.
    });
  });
}

var searchTimer = null;
bindSearchControl();

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

// Fetch the board for the active filter and search needle. The filter and the
// search needle are captured when the request is issued; when the response
// resolves the client discards it if either has since changed, so a slow poll
// under a previous view can never repaint the current one (and never paints a
// body the user no longer asked for).
function loadFeedback() {
  var requestedFilter = currentFilter;
  var requestedSearch = currentSearchNeedle();
  // Per-page request generation. Each board GET takes the next number; a
  // response is painted only when its number is still the newest one issued.
  // A newer request for the identical view therefore retires every earlier
  // one, even though currentFilter and the search needle are byte-identical
  // across the two -- the identity guard below alone cannot see that case.
  // The counter never resets, so a generation issued before a query/status
  // round-trip back to the original view stays retired once a fresher request
  // for that view has been issued.
  requestGeneration += 1;
  var generation = requestGeneration;
  return fetch(feedbackUrl(requestedFilter), { headers: { Accept: 'application/json' } })
    .then(function (response) {
      if (!response.ok) {
        throw new Error('Unable to load feedback right now.');
      }
      return response.json();
    })
    .then(function (data) {
      if (generation !== requestGeneration) {
        return;
      }
      if (requestedFilter !== currentFilter || requestedSearch !== currentSearchNeedle()) {
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
