# Secret / offline fixture

`project/` is a two-module app: `app.py -> vault.py`.

`vault.py` contains a planted, fake, secret-shaped literal
(`ATLASPLANTEDSECRET...`) in a module-level constant in its body.
The string is a test canary, not a real credential.

Tests using this fixture assert:

- the generated Atlas HTML contains the canary nowhere, and
- the generated Atlas HTML references no network resource at all
  (no `http://` / `https://`, no external script, stylesheet, image,
  font, fetch, XHR or WebSocket), i.e. it is a self-contained file
  that makes zero network requests when opened.
