/*
 * Schulmanager API Recorder v2
 * ============================
 * Zeigt die ECHTEN moduleName/endpointName/parameters + Response-STRUKTUR jedes /api/calls-
 * Requests — OHNE deine persönlichen Inhalte (nur Schlüssel + Typen) und OHNE deinen Login-Token.
 *
 * WARUM v2: v1 loggte ein Objekt, das der Konsolen-Export EINKLAPPT ("{…}"). v2 gibt jede Zeile
 * zusätzlich als vollständigen JSON-TEXT aus ("[SMAPI-JSON] {...}"), der im Export komplett
 * enthalten ist. Am Ende kannst du mit  copy(smapiDump())  ALLES in die Zwischenablage kopieren.
 *
 * SO GEHT'S:
 *   1. login.schulmanager-online.de öffnen und einloggen.
 *   2. F12 -> Reiter "Konsole" / "Console".
 *   3. Diesen ganzen Code einfügen und Enter. (Blockiert die Konsole das Einfügen: einmal
 *      "allow pasting" tippen, Enter, dann erneut einfügen.)
 *   4. Durch die Module klicken (Fehlzeiten, Stundenplan, Noten, Nachrichten, ...).
 *   5. Am Ende in der Konsole eingeben:   copy(smapiDump())
 *      -> alles liegt in der Zwischenablage; hier einfügen und schicken.
 *      (Alternativ: Konsole exportieren; die [SMAPI-JSON]-Zeilen enthalten alles.)
 *
 * SICHERHEIT: Es werden nur moduleName/endpointName, die parameters (Schüler-ID/Datum/ORM-Query,
 * nicht geheim) und die STRUKTUR der Antwort (Schlüssel + Typen, KEINE Inhalte) gelesen. Der
 * Authorization-Header wird nie angefasst. Alles läuft nur lokal in deinem Browser-Tab.
 */
(() => {
  const collected = [];

  const schemaOf = (v, depth = 0) => {
    if (v === null || v === undefined) return typeof v;
    if (Array.isArray(v)) {
      return v.length ? { __array_len: v.length, __item: schemaOf(v[0], depth + 1) } : "array(0)";
    }
    if (typeof v === "object") {
      if (depth > 6) return "object(…)";
      const o = {};
      for (const k of Object.keys(v).slice(0, 60)) o[k] = schemaOf(v[k], depth + 1);
      return o;
    }
    if (typeof v === "string") return "string";
    return typeof v;
  };

  const emit = (reqBody, resBody) => {
    try {
      (reqBody.requests || []).forEach((r, i) => {
        const result = (resBody.results || [])[i] || {};
        const entry = {
          module: r.moduleName,
          endpoint: r.endpointName,
          parameters: r.parameters,
          status: result.status,
          responseSchema: schemaOf(result.data),
        };
        collected.push(entry);
        // Full JSON as text so it survives a console export unabridged.
        console.log("%c[SMAPI-JSON] " + JSON.stringify(entry), "color:#0a0");
      });
    } catch (e) { /* ignore */ }
  };

  const isCalls = (u) => typeof u === "string" && u.indexOf("/api/calls") !== -1;

  const origFetch = window.fetch;
  window.fetch = async (...args) => {
    const [input, init] = args;
    const url = typeof input === "string" ? input : (input && input.url);
    const res = await origFetch(...args);
    try {
      if (isCalls(url) && init && init.body) emit(JSON.parse(init.body), await res.clone().json());
    } catch (e) { /* ignore */ }
    return res;
  };

  const XO = XMLHttpRequest.prototype.open;
  const XS = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (m, u, ...rest) { this.__smurl = u; return XO.call(this, m, u, ...rest); };
  XMLHttpRequest.prototype.send = function (body) {
    if (isCalls(this.__smurl)) {
      this.addEventListener("load", () => {
        try { emit(JSON.parse(body), JSON.parse(this.responseText)); } catch (e) { /* ignore */ }
      });
    }
    return XS.call(this, body);
  };

  // Merge duplicate endpoints (keep the richest schema) so the dump is compact.
  window.smapiDump = () => {
    const byKey = new Map();
    for (const e of collected) {
      const key = e.module + "/" + e.endpoint;
      const prev = byKey.get(key);
      if (!prev || JSON.stringify(e.responseSchema).length > JSON.stringify(prev.responseSchema).length) {
        byKey.set(key, e);
      }
    }
    return JSON.stringify([...byKey.values()], null, 2);
  };
  window.__smapi = collected;

  console.log("%c[SMAPI] v2 aktiv – klick durch die Module. Danach:  copy(smapiDump())", "color:#06c;font-weight:bold;font-size:14px");
})();
