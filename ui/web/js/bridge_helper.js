/**
 * RadioAI Studio Pro — Bridge Helper
 *
 * Include in every HTML page:
 *   <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
 *   <script src="js/bridge_helper.js"></script>
 *
 * Provides:
 *   callBridge(method, ...args) — returns data or null
 *   navigateTo(page)            — navigate via bridge or direct
 *   window.bridge               — auto-connected QWebChannel bridge
 *   Auto clock update
 *   Auto station name/location update from DB
 */

var bridge = null;
var _bridgeReady = false;
var _onBridgeReady = [];

// ── Core bridge call — handles sync + Promise, parses {success, data} ──
function callBridge(method) {
  if (!bridge) return null;
  var args = Array.prototype.slice.call(arguments, 1);
  try {
    var raw = bridge[method].apply(bridge, args);
    // Handle Promise return (newer Qt)
    if (raw && typeof raw.then === 'function') {
      // For async, return null synchronously — use callBridgeAsync for Promise
      console.log('callBridge: got Promise for ' + method + ', use callBridgeAsync instead');
      return null;
    }
    if (!raw) return null;
    var result = JSON.parse(raw);
    if (!result.success) {
      console.error('Bridge error [' + method + ']:', result.error);
      return null;
    }
    return result.data;
  } catch (e) {
    console.error('Bridge failed [' + method + ']:', e);
    return null;
  }
}

// ── Async bridge call — for newer Qt that returns Promises ──
function callBridgeAsync(method, args, callback) {
  if (!bridge) { if (callback) callback(null); return; }
  try {
    var result = bridge[method].apply(bridge, args || []);
    if (result && typeof result.then === 'function') {
      result.then(function(raw) {
        if (!raw) { if (callback) callback(null); return; }
        try {
          var parsed = JSON.parse(raw);
          if (callback) callback(parsed.success ? parsed.data : null);
        } catch (e) { if (callback) callback(null); }
      }).catch(function() { if (callback) callback(null); });
    } else {
      // Sync fallback
      if (!result) { if (callback) callback(null); return; }
      try {
        var parsed = JSON.parse(result);
        if (callback) callback(parsed.success ? parsed.data : null);
      } catch (e) { if (callback) callback(null); }
    }
  } catch (e) { if (callback) callback(null); }
}

// ── Navigation ──────────────────────────────────────────────────────
// Build absolute file URL from current page location
function _resolvePageUrl(page) {
  // Get directory of current page
  var href = window.location.href;
  var dir = href.substring(0, href.lastIndexOf('/') + 1);
  return dir + page + '.html';
}

function navigateTo(page) {
  if (bridge) {
    try {
      var result = bridge.navigate(page);
      // If it returns a Promise, the Python side handles it
      if (result && typeof result.then === 'function') return;
      // If void/undefined, Python got the signal
      return;
    } catch (e) {}
  }
  // Fallback: direct file navigation with absolute URL
  window.location.href = _resolvePageUrl(page);
}

function goBack() {
  window.location.href = _resolvePageUrl('control_panel');
}

function goToSettings() {
  var dir = window.location.href.substring(0, window.location.href.lastIndexOf('/') + 1);
  window.location.href = dir + 'control_panel.html#settings';
}

function goToScheduling() {
  var dir = window.location.href.substring(0, window.location.href.lastIndexOf('/') + 1);
  window.location.href = dir + 'control_panel.html#scheduling';
}

// ── Clock (applies saved date/time format, IST timezone fixed) ───────
var _savedDateFormat = null;
var _savedTimeFormat = null;

function updateClock() {
  var now = new Date();
  var clockEl = document.getElementById('clock-time') || document.getElementById('clock');
  var dateEl = document.getElementById('clock-date');

  // Time display — applies 12h/24h format
  if (clockEl) {
    var hours = now.getHours();
    var mins = String(now.getMinutes()).padStart(2, '0');
    var secs = String(now.getSeconds()).padStart(2, '0');

    if (_savedTimeFormat === '12h') {
      var ampm = hours >= 12 ? 'PM' : 'AM';
      var h12 = hours % 12 || 12;
      clockEl.textContent = String(h12).padStart(2, '0') + ':' + mins + ':' + secs + ' ' + ampm;
    } else {
      clockEl.textContent = String(hours).padStart(2, '0') + ':' + mins + ':' + secs;
    }
  }

  // Date display — applies DD/MM/YYYY, MM/DD/YYYY, YYYY-MM-DD, DD-MMM-YYYY
  if (dateEl) {
    var d = now.getDate();
    var m = now.getMonth();
    var y = now.getFullYear();
    var dayName = ['Sunday','Monday','Tuesday','Wednesday','Thursday','Friday','Saturday'][now.getDay()];
    var monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    var monthShort = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var dd = String(d).padStart(2, '0');
    var mm = String(m + 1).padStart(2, '0');
    var dateStr;

    if (_savedDateFormat === 'MM/DD/YYYY') {
      dateStr = dayName + ', ' + mm + '/' + dd + '/' + y;
    } else if (_savedDateFormat === 'YYYY-MM-DD') {
      dateStr = dayName + ', ' + y + '-' + mm + '-' + dd;
    } else if (_savedDateFormat === 'DD-MMM-YYYY') {
      dateStr = dayName + ', ' + dd + '-' + monthShort[m] + '-' + y;
    } else {
      dateStr = dayName + ', ' + d + ' ' + monthNames[m] + ' ' + y;
    }
    dateEl.textContent = dateStr;
  }
}

// ── Auto-load station name + formats on every page ──────────────────
function _updateStationInfo(s) {
  if (!s) return;

  // Apply date/time format globally
  if (s.date_format) _savedDateFormat = s.date_format;
  if (s.time_format) _savedTimeFormat = s.time_format;
  updateClock(); // Apply immediately

  var name = s.station_name || 'RadioAI Studio';
  var loc = s.station_location || (s.station_city ? s.station_city + ', ' + (s.station_region || '') : '');

  // Update ALL elements with class "station-name" (covers every page)
  var nameEls = document.querySelectorAll('.station-name');
  for (var i = 0; i < nameEls.length; i++) {
    if (nameEls[i].tagName !== 'INPUT') nameEls[i].textContent = name;
  }

  // Update ALL elements with class "station-loc"
  var locEls = document.querySelectorAll('.station-loc');
  for (var i = 0; i < locEls.length; i++) {
    locEls[i].textContent = loc;
  }

  // Studio screen has different classes
  var el = document.querySelector('.hdr-station-name');
  if (el) el.textContent = name;
  el = document.querySelector('.hdr-station-loc');
  if (el) el.textContent = loc;

  // Studio NOW ON AIR bar
  el = document.querySelector('.now-on-air-bar');
  if (el) el.innerHTML = '\u25b6 NOW ON AIR \u2014 ' + name + ' \u2014 ' + (s.station_frequency || '91.5 MHz');
}

// ── Bridge auto-connect ─────────────────────────────────────────────
function onBridgeReady(fn) {
  if (_bridgeReady) { fn(); }
  else { _onBridgeReady.push(fn); }
}

(function _autoConnect() {
  updateClock();
  setInterval(updateClock, 1000);

  if (typeof qt === 'undefined' || !qt.webChannelTransport) {
    console.log('No Qt bridge — browser mode');
    return;
  }

  new QWebChannel(qt.webChannelTransport, function(channel) {
    bridge = channel.objects.bridge;
    _bridgeReady = true;

    // Load station settings on every page
    callBridgeAsync('get_all_settings', [], function(data) {
      if (data) _updateStationInfo(data);
    });

    // Fire any waiting callbacks
    for (var i = 0; i < _onBridgeReady.length; i++) {
      try { _onBridgeReady[i](); } catch (e) {}
    }
    _onBridgeReady = [];
  });
})();
