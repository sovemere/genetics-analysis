/*
 * Dashboard components (roadmap M4.5, M4.6, M4.7, M4.8).
 *
 * Alpine here is the **CSP build** (see static/vendor/VENDOR.yaml), which evaluates no
 * strings. That has one consequence and it shapes this entire file: component logic must be
 * registered with `Alpine.data(name, factory)` and referenced by name from the markup.
 * Inline expressions do not work -- `x-on:click="open = !open"` is silently inert, while
 * `x-on:click="toggle"` calls the method below. There is no console error for the first
 * form, which is why this is written down here and in the vendor manifest rather than left
 * to be rediscovered.
 *
 * Registration happens on `alpine:init`, not at load. base.html loads this file before the
 * Alpine bundle, both deferred, so this listener is attached before Alpine starts and every
 * component exists by the time Alpine walks the DOM. Calling `Alpine.data(...)` at top level
 * would dereference an `Alpine` that is not there yet.
 *
 * **Nothing here is required for the page to work.** Every control has a server-side path:
 * the run selector duplicates as links, the grid controls are a GET form with a submit
 * button, and a card face is an anchor to that card's own page. The CSP would refuse a
 * cross-origin request anyway, and `tests/web/test_static.py` fails on the shapes that
 * fetch.
 */
document.addEventListener('alpine:init', () => {
  /*
   * The run selector. Navigates on change rather than swapping content over htmx: a run is
   * a whole page of state -- banner, nav counts, every section -- so a URL per run is what
   * makes a specific run linkable, reloadable and back-button-able.
   */
  Alpine.data('runselector', () => ({
    open(event) {
      const id = event.target.value;
      if (!id) {
        return;
      }
      /*
       * `encodeURIComponent`, even though `check_run_id` has already proved a stored run id
       * is a plain directory name. The id here came out of a `<select>` in a document, not
       * out of the store, and building a URL from page content without encoding it is the
       * habit that is wrong the one time the assumption does not hold.
       */
      window.location.assign('/runs/' + encodeURIComponent(id));
    },
  }));

  /*
   * The grid controls (M4.7). Submitting the form is what applies an arrangement, and the
   * form has a real submit button -- this only saves a click on the two selects, where
   * changing the value and then having to press Apply reads as a control that did not
   * work. The filter checkboxes deliberately do *not* auto-submit: reloading the page
   * between each of thirteen sections would make choosing several of them unusable.
   */
  Alpine.data('gridcontrols', () => ({
    submit(event) {
      const form = event.target.form || event.target.closest('form');
      if (form) {
        form.requestSubmit ? form.requestSubmit() : form.submit();
      }
    },
  }));

  /*
   * The card modal (M4.6). Owns `#card-modal`, which htmx swaps a fragment into; the
   * component sits on the host rather than inside the fragment so the escape-key listener
   * survives every swap.
   *
   * Closing empties the host rather than hiding it, so nothing invisible is left holding a
   * genotype in the DOM after the reader has closed it.
   */
  Alpine.data('cardmodal', () => ({
    close() {
      /*
       * `getElementById`, not `this.$el`. `$el` is the element the *directive* is on, and
       * these methods are called from the close button and the backdrop, which are inside
       * the swapped fragment -- so `this.$el.innerHTML = ''` would empty the button and
       * leave the modal standing. The host has one id, which `hx-target` already names, so
       * addressing it by that id is also the one name for it.
       */
      const host = document.getElementById('card-modal');
      if (!host || host.innerHTML === '') {
        return;
      }
      host.innerHTML = '';
      setBackgroundInert(false);
      const openerId = host.dataset.opener;
      if (openerId) {
        const opener = document.getElementById(openerId);
        if (opener) {
          opener.focus();
        }
        delete host.dataset.opener;
      }
    },
  }));

  /*
   * The theme toggle (M4.8). Three states, not two: `system` is a real choice and the
   * default, so a two-way toggle would make following the OS setting unreachable once
   * somebody had picked either explicit theme.
   *
   * `theme.js` has already applied the stored value before first paint; this reads back
   * what it did rather than keeping a second copy of that decision.
   */
  Alpine.data('themetoggle', () => ({
    theme: document.documentElement.getAttribute('data-theme') || 'system',
    get label() {
      return { system: 'System', light: 'Light', dark: 'Dark' }[this.theme] || 'System';
    },
    get icon() {
      return { system: '◐', light: '☀', dark: '☾' }[this.theme] || '◐';
    },
    cycle() {
      const next = { system: 'light', light: 'dark', dark: 'system' }[this.theme] || 'system';
      this.theme = next;
      if (next === 'system') {
        document.documentElement.removeAttribute('data-theme');
      } else {
        document.documentElement.setAttribute('data-theme', next);
      }
      try {
        if (next === 'system') {
          window.localStorage.removeItem('genetics-theme');
        } else {
          window.localStorage.setItem('genetics-theme', next);
        }
      } catch (error) {
        /* Storage unavailable; the choice applies to this page and is not remembered. */
      }
    },
  }));
});

/*
 * `aria-modal="true"` on the card dialog tells a screen reader that everything outside it is
 * unavailable. Nothing was making that true: a keyboard user could tab straight out of the
 * dialog into the grid behind it, and the announcement was simply wrong -- markup asserting
 * something the page does not do, which is the same defect class as a card explaining an
 * absence it has not established.
 *
 * `inert` is what makes the claim true: it removes a subtree from the tab order, from hit
 * testing and from the accessibility tree in one attribute. Applied to every top-level
 * sibling of the host rather than to a named list of them, so a section added to the page
 * later is covered without anyone remembering this function exists.
 */
function setBackgroundInert(on) {
  const host = document.getElementById('card-modal');
  if (!host) {
    return;
  }
  for (const element of document.body.children) {
    if (element === host) {
      continue;
    }
    if (on) {
      element.setAttribute('inert', '');
    } else {
      element.removeAttribute('inert');
    }
  }
}

/*
 * Focus moves into the modal when one opens, and the element that opened it is remembered
 * so focus can go back on close. Written against an htmx event rather than as an Alpine
 * `x-init` on the fragment, because Alpine initialises swapped-in markup through a mutation
 * observer whose ordering relative to the swap is not something to depend on for the thing
 * that decides where a keyboard user is standing.
 */
document.addEventListener('htmx:afterSwap', (event) => {
  const host = document.getElementById('card-modal');
  if (!host || event.target !== host) {
    return;
  }
  setBackgroundInert(true);
  const opener = event.detail && event.detail.requestConfig && event.detail.requestConfig.elt;
  if (opener) {
    if (!opener.id) {
      opener.id = 'opener-' + Math.random().toString(36).slice(2);
    }
    host.dataset.opener = opener.id;
  }
  const dialog = host.querySelector('.modal');
  if (dialog) {
    dialog.focus();
  }
});
