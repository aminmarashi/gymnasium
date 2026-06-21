/* App state, mirroring the prototype's DCLogic state. Theme is persisted to
   localStorage; the model defaults to a cheap configured model, else the first
   one opencode reports. */
(function () {
  var THEME_KEY = 'gym.theme';

  function defaultTheme() {
    var saved = null;
    try { saved = localStorage.getItem(THEME_KEY); } catch (e) {}
    if (saved === 'light' || saved === 'dark') return saved;
    // Phone defaults light, desktop dark (per the handoff).
    return window.matchMedia('(min-width: 901px)').matches ? 'dark' : 'light';
  }

  window.State = {
    user: null,
    screen: 'feed',           // feed | reader | saved | map
    density: 'comfort',       // comfort | compact
    theme: defaultTheme(),
    feed: [],
    item: null,               // current reader item (full dict)
    summaryTerms: [],         // terms to underline in the reader
    glossary: {},             // term(lower) -> kb entry id, for underlining
    // conversation
    panelOpen: false,
    selText: '',
    mode: 'explain',          // explain | summarize | ask
    answer: null,             // {lead, body, analogy?}
    thread: [],               // [{role:'user'|'assistant', content}]
    savedEntryId: null,       // set once the entry is persisted
    justSaved: false,
    draft: '',
    affordance: null,         // {x, y} for the floating toolbar
    // models
    models: { providers: [] },
    model: null,
    modelMenuOpen: false,
    // kb / map
    kbEntries: [],
    kbQuery: '',
    mapData: { nodes: [], edges: [] },
    // misc
    busy: false,

    saveTheme: function () {
      try { localStorage.setItem(THEME_KEY, this.theme); } catch (e) {}
    },
    isDesktop: function () { return window.matchMedia('(min-width: 901px)').matches; },
    modelName: function (id) {
      id = id || this.model;
      var provs = (this.models && this.models.providers) || [];
      for (var i = 0; i < provs.length; i++) {
        var ms = provs[i].models || [];
        for (var j = 0; j < ms.length; j++) {
          if (ms[j].id === id) return ms[j].name;
        }
      }
      return id || 'Model';
    }
  };
})();
