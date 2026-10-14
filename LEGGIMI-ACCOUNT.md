# Account e salvataggio online (Firebase, gratis)

Serve una volta sola, da computer, circa 10 minuti.

1. Vai su https://console.firebase.google.com, accedi con un account Google e premi
   **Crea un progetto** (nome: footstats). Google Analytics non serve: puoi disattivarlo.
2. **Accesso con email.** Nel menu a sinistra: Build → **Authentication** → Inizia →
   scheda *Metodo di accesso* → **Email/password** → Attiva → Salva.
3. **Il tuo indirizzo.** Sempre in Authentication → scheda *Impostazioni* → *Domini autorizzati*
   → **Aggiungi dominio** → scrivi `TUONOME.github.io` (es. `simich6.github.io`).
4. **Il database.** Build → **Firestore Database** → Crea database → posizione `europe-west`
   → avvia in *modalità di produzione*. Poi scheda **Regole**, sostituisci tutto con:

   ```
   rules_version = '2';
   service cloud.firestore {
     match /databases/{database}/documents {
       match /utenti/{uid} {
         allow read, write: if request.auth != null && request.auth.uid == uid;
       }
     }
   }
   ```
   e premi **Pubblica**. Così ognuno vede solo i propri dati.
5. **La configurazione.** Icona ingranaggio → Impostazioni progetto → in basso *Le tue app* →
   icona **</>** (Web) → nome footstats → Registra app. Compare un blocco
   `const firebaseConfig = { apiKey: "...", ... };`: copialo.
6. Su GitHub, nel repository: **Add file → Create new file**, nome `firebase.txt`,
   incolla il blocco copiato → **Commit changes**.
7. **Actions → Aggiorna Footstats → Run workflow.** A fine aggiornamento, nell'app premi
   **👤 Accedi → Crea account**.

I dati della configurazione Firebase non sono segreti (servono al sito per collegarsi):
a proteggere il diario sono la password e le regole del punto 4.
