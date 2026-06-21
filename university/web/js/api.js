/* Thin fetch wrappers for the Gymnasium API. Same-origin cookie auth.
   A 401 anywhere bounces the user back to the login page. */
(function () {
  function onUnauthorized() {
    if (window.location.pathname !== '/login.html') {
      window.location.href = '/';
    }
  }

  function request(method, path, body) {
    var opts = { method: method, headers: {}, credentials: 'same-origin' };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (r) {
      if (r.status === 401) { onUnauthorized(); throw new Error('unauthorized'); }
      var ct = r.headers.get('Content-Type') || '';
      if (ct.indexOf('application/json') !== -1) {
        return r.json().then(function (data) {
          if (!r.ok) { throw Object.assign(new Error(data.error || 'request failed'), { data: data }); }
          return data;
        });
      }
      if (!r.ok) { throw new Error('request failed'); }
      return r;
    });
  }

  window.API = {
    me: function () { return request('GET', '/api/me'); },
    logout: function () { return request('POST', '/api/logout', {}); },
    models: function () { return request('GET', '/api/models'); },
    feed: function (kind, opts) {
      opts = opts || {};
      var q = [];
      if (kind) q.push('kind=' + encodeURIComponent(kind));
      if (opts.added) q.push('added=1');
      ['q', 'sort', 'author', 'company', 'publication', 'language', 'limit'].forEach(function (k) {
        if (opts[k] != null && opts[k] !== '') q.push(k + '=' + encodeURIComponent(opts[k]));
      });
      return request('GET', '/api/feed' + (q.length ? '?' + q.join('&') : ''));
    },
    addItem: function (payload) { return request('POST', '/api/items', payload); },
    deleteItem: function (id) { return request('DELETE', '/api/items/' + id); },
    facets: function (kind) {
      return request('GET', '/api/feed/facets?kind=' + encodeURIComponent(kind));
    },
    item: function (id) { return request('GET', '/api/item/' + id); },
    documentUrl: function (id) { return '/api/item/' + id + '/document'; },
    markdown: function (id) {
      return fetch('/api/item/' + id + '/markdown', { credentials: 'same-origin' }).then(function (r) {
        if (r.status === 401) { onUnauthorized(); throw new Error('unauthorized'); }
        if (r.status === 404) return null;
        if (!r.ok) throw new Error('request failed');
        var source = r.headers.get('X-Markdown-Source') || null;
        return r.text().then(function (text) { return { text: text, source: source }; });
      });
    },
    uploadMarkdown: function (id, file) {
      return fetch('/api/item/' + id + '/markdown', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'text/markdown' }, body: file
      }).then(function (r) {
        if (r.status === 401) { onUnauthorized(); throw new Error('unauthorized'); }
        if (!r.ok) throw new Error('upload failed');
        return r.json();
      });
    },
    summarize: function (itemId, model) { return request('POST', '/api/summarize', { item_id: itemId, model: model }); },
    ask: function (payload) { return request('POST', '/api/ask', payload); },
    chat: function (payload) { return request('POST', '/api/chat', payload); },
    chatThread: function (itemId) { return request('GET', '/api/chat?item_id=' + encodeURIComponent(itemId)); },
    kb: function () { return request('GET', '/api/kb'); },
    kbGet: function (id) { return request('GET', '/api/kb/' + id); },
    kbSearch: function (q) { return request('GET', '/api/kb/search?q=' + encodeURIComponent(q)); },
    kbSave: function (payload) { return request('POST', '/api/kb/save', payload); },
    map: function () { return request('GET', '/api/map'); },
    mapEdgeAdd: function (src, dst) { return request('POST', '/api/map/edge', { src: src, dst: dst }); },
    mapEdgeDelete: function (id) { return request('DELETE', '/api/map/edge/' + id); },
    mapPosition: function (conceptId, x, y) { return request('POST', '/api/map/position', { concept_id: conceptId, x: x, y: y }); },
    mapAiLinks: function (model) { return request('POST', '/api/map/ai-links', { model: model }); },
    refresh: function (kind, days) { return request('POST', '/api/refresh', { kind: kind, days: days }); },
    refreshStatus: function () { return request('GET', '/api/refresh/status'); }
  };
})();
