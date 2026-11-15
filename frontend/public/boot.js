// Runs before the bundle (external file: the server's CSP is script-src 'self', no inline scripts).
// Dark only: always set the dark theme before first paint and drop any legacy stored 'light' choice.
(function () {
  document.documentElement.dataset.theme = 'dark';
  try {
    if (localStorage.getItem('uhd-theme') !== null) localStorage.removeItem('uhd-theme');
  } catch (e) {}
})();
// Language before first paint (I18N.md §1): ?lang= > localStorage uhd-lang > default. Keep the default in sync with
// DEFAULT_LOCALE in src/i18n/locale.ts.
(function () {
  var DEFAULT = 'en';
  var l = null;
  try {
    var v = (new URLSearchParams(location.search).get('lang') || '').toLowerCase();
    if (v === 'ua' || v.indexOf('uk') === 0) l = 'uk'; else if (v.indexOf('en') === 0) l = 'en';
    if (!l) { var st = localStorage.getItem('uhd-lang'); if (st === 'en' || st === 'uk') l = st; }
  } catch (e) {}
  document.documentElement.lang = l || DEFAULT;
})();
// Start the first requests while the JS bundle is still downloading (QA R3-3: slow 3G).
// The app takes these promises once (src/api/prefetch.ts); on any failure it simply refetches.
(function () {
  try {
    var q = new URLSearchParams(location.search);
    if (q.get('area')) return;
    var zone = q.get('zone') || 'kyiv-pozniaky';
    // same rule as sendsPlaceId in src/api/types.ts (QA R4-2)
    var usePlaceId = function (id, kind) { kind = kind || ''; return kind.indexOf('geocoder') !== 0 && (id.indexOf('osm:') !== 0 || kind === 'city'); };
    var j = function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); };
    var place = fetch('/api/places/' + encodeURIComponent(zone) + '?lang=en', { headers: { Accept: 'application/json' } }).then(j);
    window.__uhdPre = {
      meta: fetch('/api/meta?lang=en', { headers: { Accept: 'application/json' } }).then(j),
      zone: zone,
      place: place,
      analyze: place.then(function (p) {
        return fetch('/api/analyze?lang=en', { method: 'POST', headers: { Accept: 'application/json', 'Content-Type': 'application/json' }, body: JSON.stringify(usePlaceId(zone, p.kind) ? { place_id: zone } : { geometry: p.geometry }) }).then(j);
      }),
    };
    for (var k in window.__uhdPre) if (window.__uhdPre[k] && window.__uhdPre[k].catch) window.__uhdPre[k].catch(function () {});
  } catch (e) {}
})();
