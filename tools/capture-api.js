/*
 * Schulmanager API Recorder
 * =========================
 * Zeigt dir (und mir) die ECHTEN moduleName/endpointName/parameters + Response-STRUKTUR
 * jedes /api/calls-Requests an — OHNE deine persönlichen Inhalte und OHNE deinen Login-Token.
 *
 * SO GEHT'S:
 *   1. login.schulmanager-online.de öffnen und normal einloggen.
 *   2. F12 druecken -> Reiter "Konsole" / "Console".
 *   3. Den GESAMTEN Code unten hineinkopieren und Enter druecken.
 *   4. Im Schulmanager nacheinander auf die Module klicken:
 *      Stundenplan, Hausaufgaben, Noten, Nachrichten, Fehlzeiten, Elternbriefe, Zahlungen, Klassenbuch ...
 *   5. In der Konsole erscheint pro Modul eine Zeile [SMAPI] <modul> / <endpoint>.
 *   6. Rechtsklick in die Konsole -> "Alle Nachrichten speichern" (oder alles markieren + kopieren)
 *      und mir den Text schicken.
 *
 * SICHERHEIT: Das Snippet liest NUR moduleName/endpointName/parameters und die STRUKTUR
 * (Schlüssel + Typen) der Antwort. Es liest NICHT den Inhalt (keine Namen/Noten/Texte) und
 * NICHT den Authorization-Header. Alles laeuft nur lokal in deinem Browser-Tab.
 */
(() => {
  const schemaOf = (v, depth = 0) => {
    if (v === null || v === undefined) return typeof v;
    if (Array.isArray(v)) return v.length ? ["array(" + v.length + ")", schemaOf(v[0], depth + 1)] : "array(0)";
    if (typeof v === "object") {
      if (depth > 5) return "object(…)";
      const o = {};
      for (const k of Object.keys(v).slice(0, 50)) o[k] = schemaOf(v[k], depth + 1);
      return o;
    }
    if (typeof v === "string") return "string";
    return typeof v;
  };

  const log = (reqBody, resBody) => {
    try {
      (reqBody.requests || []).forEach((r, i) => {
        const result = (resBody.results || [])[i] || {};
        console.log(
          "%c[SMAPI] " + r.moduleName + " / " + r.endpointName,
          "color:#0a0;font-weight:bold",
          { parameters: r.parameters, status: result.status, responseSchema: schemaOf(result.data) }
        );
      });
    } catch (e) { /* ignore */ }
  };

  const isCalls = (u) => typeof u === "string" && u.indexOf("/api/calls") !== -1;

  // --- fetch() abfangen ---
  const origFetch = window.fetch;
  window.fetch = async (...args) => {
    const [input, init] = args;
    const url = typeof input === "string" ? input : (input && input.url);
    const res = await origFetch(...args);
    try {
      if (isCalls(url) && init && init.body) {
        const clone = res.clone();
        log(JSON.parse(init.body), await clone.json());
      }
    } catch (e) { /* ignore */ }
    return res;
  };

  // --- XMLHttpRequest abfangen (axios nutzt XHR) ---
  const XO = XMLHttpRequest.prototype.open;
  const XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u, ...rest) { this.__smurl = u; return XO.call(this, m, u, ...rest); };
  XMLHttpRequest.prototype.send = function (body) {
    if (isCalls(this.__smurl)) {
      this.addEventListener("load", () => {
        try { log(JSON.parse(body), JSON.parse(this.responseText)); } catch (e) { /* ignore */ }
      });
    }
    return XS.call(this, body);
  };

  console.log("%c[SMAPI] Recorder aktiv – klick jetzt durch die Module. Danach Konsole kopieren & schicken.", "color:#06c;font-weight:bold;font-size:14px");
})();
