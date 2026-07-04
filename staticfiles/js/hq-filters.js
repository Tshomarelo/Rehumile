/* Rehumile TMW — Shared list-filtering helpers (search debounce + query-string builder) */
(function () {
  window.HQFilters = {
    /**
     * Returns a debounced version of fn — fires `ms` after the last call.
     * Used on search inputs so we don't re-fetch on every keystroke.
     */
    debounce: function (fn, ms) {
      ms = ms || 350;
      var t;
      return function () {
        var args = arguments, ctx = this;
        clearTimeout(t);
        t = setTimeout(function () { fn.apply(ctx, args); }, ms);
      };
    },

    /**
     * Builds a URL query string from a plain object, skipping empty/null/undefined values.
     * qs({status:'sent', search:'', company:'abc'}) -> "status=sent&company=abc"
     */
    qs: function (params) {
      var usp = new URLSearchParams();
      Object.keys(params || {}).forEach(function (k) {
        var v = params[k];
        if (v !== '' && v !== null && v !== undefined) usp.set(k, v);
      });
      return usp.toString();
    },
  };
})();
