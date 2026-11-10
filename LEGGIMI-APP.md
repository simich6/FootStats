# Footstats come app Android (.apk)

L'app installata mostra il tuo sito (simich6.github.io/FootStats): i dati si aggiornano da soli,
il pacchetto non va mai rifatto dopo gli aggiornamenti.

## 1. Crea il pacchetto (5 minuti, dal computer)
1. Vai su **https://www.pwabuilder.com**
2. Incolla `https://simich6.github.io/FootStats/` e premi **Start**.
3. Premi **Package for stores** → **Android** → **Generate Package**.
   - Package ID: lascia quello proposto o scrivi `io.github.simich6.footstats`
   - App name: `Footstats`
   - Signing key: **New** (lasciala creare a PWABuilder)
4. Scarica lo zip.

## 2. Conserva questi file dello zip
- `app-release-signed.apk` → è l'app da installare
- `signing.keystore` e `signing-key-info.txt` → la chiave: **conservala** (Drive, email a te stesso).
  Serve solo se un giorno vorrai rifare il pacchetto o pubblicarlo sul Play Store.
- `assetlinks.json` → serve al punto 4 (facoltativo)

## 3. Installa sul telefono
1. Manda l'**.apk** al telefono (Drive, email, WhatsApp a te stesso) e aprilo.
2. Android chiede di consentire l'installazione da questa fonte: **Consenti**.
3. Apri Footstats dall'icona.

## Restare sempre connesso
L'app usa Chrome "dietro le quinte": l'accesso (👤 Accedi) resta salvato come nel browser.
Se eri già connesso su Chrome con lo stesso telefono, lo sei già anche nell'app.
Esci solo se premi Esci, cancelli i dati di Chrome o disinstalli l'app.

## 4. (Facoltativo) Togliere la barra con l'indirizzo in alto
Senza questo passaggio l'app funziona, ma in alto compare una sottile barra con l'indirizzo.
Per toglierla Android deve verificare che il sito è tuo:
1. Su GitHub crea un **nuovo repository pubblico** chiamato esattamente `simich6.github.io`.
2. **Add file → Create new file**, nome: `.nojekyll` (vuoto) → Commit.
3. **Add file → Create new file**, nome: `.well-known/assetlinks.json`, incolla il contenuto di
   `assetlinks.json` dello zip → Commit.
4. **Settings → Pages**: Source **Deploy from a branch**, branch **main**, cartella **/ (root)** → Save.
5. Dopo qualche minuto chiudi e riapri l'app: la barra sparisce.
