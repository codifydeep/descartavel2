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

function setStatus(message, isError) {
  status.textContent = message || '';
  status.classList.toggle('is-error', Boolean(isError));
}

function renderItems(items) {
  list.innerHTML = '';
  if (!items.length) {
    emptyState.hidden = false;
    return;
  }
  emptyState.hidden = true;
  items.forEach(function (item) {
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

function loadFeedback() {
  return fetch('/feedback', { headers: { Accept: 'application/json' } })
    .then(function (response) {
      if (!response.ok) {
        throw new Error('Unable to load feedback right now.');
      }
      return response.json();
    })
    .then(function (data) {
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

function setSubmitting(pending) {
  isSubmitting = pending;
  if (submitButton) {
    submitButton.disabled = pending;
  }
}

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
