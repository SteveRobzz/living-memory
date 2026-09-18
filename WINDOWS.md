# Windows / PowerShell setup

PowerShell 5.1 is not bash. Three differences cause every error you'll hit:

| bash | PowerShell |
|---|---|
| `a && b` | put `a` and `b` on separate lines |
| `cmd < file.sql` | `Get-Content file.sql \| cmd` |
| `source .venv/bin/activate` | `.venv\Scripts\Activate.ps1` |

`cp`, `ls` and `cat` do work — they're aliases. `&&` and `<` do not.

---

## Step 1 — Database

### Path A: Docker (preferred)

Docker Desktop must actually be **running** — open it from the Start menu and
wait for the whale icon to stop animating. `docker ps` should return a header
row rather than an error. Then:

```powershell
cd C:\Users\Karan\OneDrive\Desktop\epochesque\living-memory
docker compose up -d
docker compose ps
```

### Path B: no Docker (use this if Docker won't start — takes 3 minutes)

Docker Desktop on Windows depends on WSL2 and fails often. Don't fight it the
night before a review. Get a free hosted Postgres with pgvector instead:

1. Go to **neon.tech**, sign in with GitHub, create a project.
2. Copy the connection string. It looks like:
   `postgresql://user:pass@ep-xxx.aws.neon.tech/neondb?sslmode=require`
3. Change the scheme to `postgresql+psycopg://` — keep everything else.

Supabase works the same way. Both ship pgvector, so `CREATE EXTENSION vector`
succeeds. Railway works too if you already have a project there.

---

## Step 2 — Backend

```powershell
cd C:\Users\Karan\OneDrive\Desktop\epochesque\living-memory\backend

python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.venv\Scripts\Activate.ps1
```

Your prompt should now start with `(.venv)`. If `Activate.ps1` is blocked,
the `Set-ExecutionPolicy` line above clears it for this window only.

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

Now open `.env` in an editor (`notepad .env`) and set `DATABASE_URL`:

- Docker (Path A) — leave the default:
  `postgresql+psycopg://lm:lm@localhost:5433/livingmemory`
- Neon (Path B) — paste your string with the `postgresql+psycopg://` scheme.

Apply the schema. This needs no `psql` on PATH:

```powershell
python apply_schema.py
```

Expected output:

```
OK. 8 tables: answer_traces, conversations, memories, memory_events,
memory_slots, memory_sources, messages, users
Demo users: maya, dev
```

Run the tests:

```powershell
python -m pytest -q
```

Expected: `50 passed`. Use `python -m pytest`, not bare `pytest` — the bare
command only works if the venv's Scripts folder made it onto PATH.

If the database isn't reachable, the 27 resolver tests still pass on their own:

```powershell
python -m pytest tests\test_resolver.py -q
```

Start the server:

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Check `http://localhost:8000/health` in a browser. Leave this window running.

---

## Step 3 — Frontend

New PowerShell window:

```powershell
cd C:\Users\Karan\OneDrive\Desktop\epochesque\living-memory\frontend
npm install
cp .env.local.example .env.local
npm run dev
```

Open `http://localhost:3000`.

---

## If something still fails

**`python` opens the Microsoft Store** — Windows' app-execution alias is
hijacking it. Use `py` instead of `python` everywhere, or turn the alias off
in Settings → Apps → Advanced app settings → App execution aliases.

**`pip install` fails on `psycopg[binary]`** — you're likely on Python 3.13
without wheels yet. `py -3.12 -m venv .venv` and redo Step 2.

**`.venv\Scripts\Activate.ps1 cannot be loaded`** — you skipped the
`Set-ExecutionPolicy` line. It only affects the current window.

**Frontend loads but the chat errors** — the backend isn't up, or CORS is
pointed elsewhere. Confirm `http://localhost:8000/health` responds, and that
`.env.local` contains `NEXT_PUBLIC_API=http://localhost:8000`.

**`npm install` warns about peer deps** — harmless, keep going.

---

## One-shot verification

With the backend running, in a third window:

```powershell
cd C:\Users\Karan\OneDrive\Desktop\epochesque\living-memory\backend
.venv\Scripts\Activate.ps1
python seed_demo.py
```

That drives the whole Unity → Godot sequence through the API and prints each
answer. If you see `You're currently using Godot.`, the entire engine works
and you can rehearse the demo in the browser.
