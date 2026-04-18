# Auth setup guide — lci-mini

This guide walks you end-to-end through turning on Firebase sign-in and
the optional Google Drive OAuth flow for a **production** lci-mini
deployment. If you only want localhost development, skip to
[Dev bypass](#dev-bypass) at the bottom — it takes 30 seconds.

The auth design follows Pattern A (Firebase Auth for identity +
separate Drive OAuth flow). High-level:

- **Identity** — Firebase Auth (email/password + Google).
- **Per-user Drive storage** — a separate OAuth 2.0 flow that requests
  `drive.file` scope and stores refresh tokens server-side.
- **Session storage** — Firestore when the backend has a service
  account, or per-user Drive folder when the user connected Drive.

---

## 1. Create a Firebase project

1. Go to <https://console.firebase.google.com/>.
2. **Add project** → pick a name (e.g. `lci-mini-prod`).
3. Disable Google Analytics (unless you need it). Click **Create**.

The project you just created has a **Project ID** (e.g.
`lci-mini-prod-abc123`) — copy it, you'll need it in two places.

## 2. Enable sign-in providers

Firebase Console → **Build → Authentication → Sign-in method**.

Enable:

- **Email/Password** — click "Enable", leave "Email link" off unless
  you want passwordless sign-in.
- **Google** — click "Enable". Set the support email. Firebase creates
  a default Web OAuth client automatically.

Optional: disable user registration later via
**Authentication → Settings → User actions → Enable create account**
if you want invite-only mode.

## 3. Add the web app to Firebase

Firebase Console → **Project settings → General → Your apps →
Web app (`</>`)**.

1. Register app nickname (e.g. `lci-mini-web`).
2. Skip Firebase Hosting (we configure that separately below).
3. Copy the `firebaseConfig` values into `.env`:

```sh
VITE_FIREBASE_API_KEY=AIza...
VITE_FIREBASE_AUTH_DOMAIN=lci-mini-prod.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=lci-mini-prod-abc123
VITE_FIREBASE_APP_ID=1:1234567890:web:abcdef
VITE_FIREBASE_MESSAGING_SENDER_ID=1234567890
VITE_FIREBASE_STORAGE_BUCKET=lci-mini-prod-abc123.appspot.com
```

Only the first three are **required** — the other three are used by
advanced Firebase features (messaging, storage, remote config) that
lci-mini doesn't need today but may in the future.

## 4. Add the authorised domain

Firebase Console → **Authentication → Settings → Authorised domains**.

Add your production domain (e.g. `lci-mini.example.com`). Without this,
`signInWithPopup` and `signInWithRedirect` both throw
`auth/unauthorized-domain`.

## 5. Configure the backend (Firebase Admin SDK)

The backend verifies ID tokens with the Admin SDK.

### Option A — Cloud Run / GKE (recommended)

When running on Google Cloud with a service account that has the
**Service Account Token Creator** role, you don't need a JSON key —
Application Default Credentials (ADC) just work. Only set the project
ID:

```sh
FIREBASE_PROJECT_ID=lci-mini-prod-abc123
```

### Option B — bare-metal / other clouds

Firebase Console → **Project settings → Service accounts →
Generate new private key**. Save the JSON somewhere the container can
read (e.g. a mounted secret).

```sh
FIREBASE_PROJECT_ID=lci-mini-prod-abc123
FIREBASE_ADMIN_CREDENTIALS=/secrets/firebase-admin.json
```

**Never commit the JSON** — add the path to `.gitignore` and mount it
as a secret at runtime.

## 6. Deploy Firestore security rules

The repo ships with [`firestore.rules`](../firestore.rules). It locks
every collection to its owning uid and denies all client writes. Deploy
it every time you push a new build:

```sh
firebase deploy --only firestore:rules --project lci-mini-prod-abc123
```

Enable Firestore first in the console (**Build → Firestore Database →
Create database** → start in production mode, pick a region near your
users).

> **Why this matters** — without rules, any signed-in user can read
> any other user's Drive tokens and chat summaries. The rules are the
> only thing standing between user A's refresh token and user B's
> browser DevTools.

## 7. (Optional) Set up Drive OAuth

Only needed if you want signed-in users to connect their own Drive
folder as storage. Skip if you're using the shared service-account
Drive folder (`LCI_MINI_DRIVE_ROOT` + `LCI_MINI_SERVICE_ACCOUNT`) or
the local filesystem.

### 7a. Create the Web OAuth client

Google Cloud Console → **APIs & Services → Credentials →
Create credentials → OAuth client ID**.

- **Application type** — Web application.
- **Authorised redirect URIs** — add **exactly**:
  - `https://lci-mini.example.com/auth/drive/callback` (prod)
  - `http://localhost:8004/auth/drive/callback` (local dev, optional)

Click **Create**, then **Download JSON**. This file is your
`GOOGLE_OAUTH_CLIENT_SECRETS`.

### 7b. Enable the Drive API

Google Cloud Console → **APIs & Services → Library → Google Drive
API → Enable**. Without this, `exchange_code()` returns
`access_denied`.

### 7c. Configure backend env

```sh
GOOGLE_OAUTH_CLIENT_SECRETS=/secrets/drive-oauth-client.json
DRIVE_OAUTH_REDIRECT_URL=https://lci-mini.example.com/auth/drive/callback
SESSION_SECRET=$(openssl rand -base64 32)
DRIVE_TOKEN_ENCRYPTION_KEY=$(openssl rand -base64 32)
```

- `SESSION_SECRET` signs the state cookie (CSRF protection for the
  OAuth round-trip). Rotating it invalidates in-flight callbacks — no
  user impact after the round-trip completes.
- `DRIVE_TOKEN_ENCRYPTION_KEY` wraps refresh tokens with AES-GCM
  before Firestore persistence. Rotating it invalidates **all** stored
  refresh tokens — users must reconnect Drive. For smooth rotation,
  see [Rotating encryption keys](#rotating-encryption-keys).

### 7d. Publishing / consent screen

Google Cloud Console → **APIs & Services → OAuth consent screen**.

- **User type** — Internal (G Suite) or External.
- **Scopes** — add `https://www.googleapis.com/auth/drive.file`. This
  narrow scope limits the app to files it creates; users see "lci-mini
  will see, edit, create, and delete only the specific Google Drive
  files you use with this app."
- **Test users** — while in "Testing", only listed users can connect.
  Click "Publish app" before opening to the public (requires
  verification for non-`.file` scopes; `drive.file` is exempt).

## 8. Deploy the backend

lci-mini expects a container. The example targets **Cloud Run**:

```sh
# Build + push
gcloud builds submit --tag gcr.io/lci-mini-prod-abc123/lci-mini-backend

# Deploy
gcloud run deploy lci-mini-backend \
  --image gcr.io/lci-mini-prod-abc123/lci-mini-backend \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "FIREBASE_PROJECT_ID=lci-mini-prod-abc123" \
  --set-env-vars "GOOGLE_OAUTH_CLIENT_SECRETS=/secrets/drive-oauth-client.json" \
  --set-env-vars "DRIVE_OAUTH_REDIRECT_URL=https://lci-mini.example.com/auth/drive/callback" \
  --set-secrets "SESSION_SECRET=projects/lci-mini-prod-abc123/secrets/SESSION_SECRET:latest" \
  --set-secrets "DRIVE_TOKEN_ENCRYPTION_KEY=projects/lci-mini-prod-abc123/secrets/DRIVE_TOKEN_ENCRYPTION_KEY:latest"
```

`--allow-unauthenticated` means Cloud Run lets anyone hit the endpoint
— the app-level Firebase middleware is what actually enforces auth.

## 9. Deploy the frontend (Firebase Hosting)

```sh
cd examples/lci-mini/frontend
pnpm build

# From examples/lci-mini/ (where firebase.json lives):
cd ..
firebase deploy --only hosting --project lci-mini-prod-abc123
```

`firebase.json` rewrites `/awp`, `/chat/*`, `/auth/*`, etc. to the
Cloud Run service so the frontend can talk to the backend without
CORS.

## 10. Smoke test

1. Visit `https://lci-mini.example.com/`.
2. Click **Create account** → register with a test email.
3. Check inbox → click verification link.
4. Reload page — banner disappears.
5. Click **Connect Google Drive** in the header menu → grant consent.
6. Send a chat message → confirm a `sessions/` folder appeared in
   your Drive root labelled "OpenBench".
7. Sign out, sign in via Google, confirm Drive reconnect banner
   appears only once.

If any step fails, run `curl https://.../health` first to rule out a
plain deploy problem, then check Cloud Run logs for the specific
Firebase error code.

---

## Dev bypass

For localhost-only development, skip everything above and:

```sh
echo "OPENBENCH_AUTH_DISABLED=1" >> .env
```

Every request now resolves to a synthetic user `dev-local@localhost`.
The frontend also short-circuits (no sign-in gate) because no
`VITE_FIREBASE_*` env vars are set.

**Never ship this env var to staging or production.** The server logs
a warning banner when it starts in this mode.

---

## Rotating encryption keys

To rotate `DRIVE_TOKEN_ENCRYPTION_KEY` without forcing every user to
reconnect Drive, run a one-shot migration script:

1. Deploy with both the old and new keys exposed via
   `DRIVE_TOKEN_ENCRYPTION_KEY_OLD` and `DRIVE_TOKEN_ENCRYPTION_KEY`.
2. Run a script that iterates `drive_tokens/*`, decrypts with
   `_OLD`, re-encrypts with the new key, writes back.
3. Deploy again without `_OLD` set.

There isn't a ready-made helper for this yet — it's tracked as a
future work item in the project's internal docs.

---

## Troubleshooting

| Symptom | Likely cause |
|---------|-------------|
| `auth/unauthorized-domain` on Google sign-in | Add your domain in Firebase Console → Authentication → Settings → Authorised domains |
| `auth/popup-blocked` → silent failure | Expected: the hook falls back to `signInWithRedirect`. Check that `authDomain` matches an authorised domain. |
| `auth/invalid-credential` on every email sign-in | Password wasn't saved at registration. Firebase's "Invalid credentials" error is deliberately ambiguous between "wrong password" and "user doesn't exist". |
| Backend returns 401 for every request | `FIREBASE_PROJECT_ID` doesn't match the ID used in `VITE_FIREBASE_PROJECT_ID`, or ADC isn't wired (verify with `gcloud auth application-default print-access-token`). |
| Drive connect redirects to `/` and nothing persists | Check Cloud Run logs for the callback handler; likely `GOOGLE_OAUTH_CLIENT_SECRETS` path is wrong or the redirect URL doesn't **exactly** match the one registered in Google Cloud Console. |
| 429 "Too many Drive-connect attempts" | The rate limiter is doing its job (10/hour/uid). Wait or reset the instance. |
