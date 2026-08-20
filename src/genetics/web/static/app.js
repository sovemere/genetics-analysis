/*
 * Dashboard components (roadmap M4.5).
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
 * Nothing in this file fetches. The page is server-rendered and navigation is ordinary
 * links; the CSP would refuse a cross-origin request anyway, and `tests/web/test_static.py`
 * fails on the shapes that fetch.
 */
document.addEventListener('alpine:init', () => {
  /*
   * The run selector. Navigates on change rather than swapping content over htmx: a run is
   * a whole page of state -- banner, nav counts, every section -- so a URL per run is what
   * makes a specific run linkable, reloadable and back-button-able. htmx earns its place at
   * M4.6, where a card modal is genuinely a fragment.
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
});
