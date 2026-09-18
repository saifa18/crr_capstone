# Prompt for GitHub Copilot — connect this backend to our SQL Server

Copy everything below the line into Copilot Chat (in VS Code, or wherever
you're running Copilot) on the computer that has access to the real SQL
Server. Fill in the placeholder values (marked `<LIKE_THIS>`) with your
actual server details before sending it, if you already know them —
otherwise tell Copilot to ask you for them first.

---

I've unzipped a project called `ercot-crr-analytics` into this workspace.
It's a FastAPI backend + React frontend for ERCOT power-market analytics.
Your task: connect its backend to our real SQL Server database so it
serves real data instead of its built-in demo dataset, and verify it
works with zero errors before you say you're done.

**Do not modify** `backend/app/analytics.py`, `backend/app/scoring.py`,
`backend/app/domain.py`, `backend/app/data_generator.py`, or anything
under `frontend/`. This task is entirely about the data connection layer
— those files are already built, tested (93 passing pytest tests), and
intentionally out of scope.

## What to do, in order

1. **Read `backend/app/db.py`'s module docstring first.** It documents
   the exact environment variables this backend reads, the two supported
   auth modes (SQL auth vs. Windows trusted-connection), and the expected
   table schema. Read `backend/.env.example` too — it's the same
   information in a fill-in-the-blanks format.

2. **Install dependencies**, including the SQL-related ones already listed
   in `backend/requirements.txt` (`sqlalchemy`, `pyodbc`, `python-dotenv`):
   ```
   cd backend
   pip install -r requirements.txt
   ```

3. **Confirm the system-level ODBC driver for SQL Server is installed on
   this machine** — this is separate from the pip install above, an OS
   package:
   - Windows: usually already present. If `pyodbc` import fails with a
     driver-related error, install "ODBC Driver 18 for SQL Server" from
     Microsoft's website.
   - macOS: `brew tap microsoft/mssql-release && brew install msodbcsql18`
   - Linux: follow Microsoft's "Install the Microsoft ODBC driver for SQL
     Server on Linux" instructions for the specific distro.

4. **Create the expected table** by running
   `backend/scripts/create_sql_server_schema.sql` against our target
   database (server: `<SQL_SERVER_HOST>`, database: `<SQL_SERVER_DATABASE>`).
   If we already have CRR auction data in a differently-named or
   differently-shaped table, **create a SQL VIEW** named
   `crr_auction_records` with the exact column names/types in that script,
   instead of moving the real table — the backend only ever runs
   `SELECT * FROM crr_auction_records`.

5. **Create `backend/.env`** (copy from `backend/.env.example`) and fill in
   our real connection details. Use EITHER:
   ```
   DATABASE_URL=mssql+pyodbc://<USERNAME>:<PASSWORD>@<SQL_SERVER_HOST>:1433/<SQL_SERVER_DATABASE>?driver=ODBC+Driver+18+for+SQL+Server
   ```
   OR the separate variables (better if the password has special
   characters that would need URL-encoding):
   ```
   SQL_SERVER_HOST=<SQL_SERVER_HOST>
   SQL_SERVER_PORT=1433
   SQL_SERVER_DATABASE=<SQL_SERVER_DATABASE>
   SQL_SERVER_USERNAME=<USERNAME>
   SQL_SERVER_PASSWORD=<PASSWORD>
   ```
   (Or, for Windows trusted-connection auth instead of a username/password,
   set `SQL_SERVER_TRUSTED_CONNECTION=yes` and omit the username/password.)

   **Do not commit `.env` or paste real credentials into chat history or
   version control.** Add `backend/.env` to `.gitignore` if it isn't
   already covered.

6. **Run the existing test suite first**, before touching anything else,
   to confirm you're starting from a working baseline:
   ```
   cd backend
   python -m pytest -q
   ```
   Expect `93 passed`. If it's not 93/93 clean at this point, stop and
   figure out why before proceeding — don't build on top of a broken
   baseline.

7. **Start the backend**:
   ```
   uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

8. **Verify the SQL connection is actually working** — this is the
   definition of "done" for this task, so check every one of these:
   ```
   curl http://localhost:8000/health
   curl http://localhost:8000/api/system/status
   curl http://localhost:8000/api/meta
   curl http://localhost:8000/api/dashboard
   ```
   - `/health` should return `{"status":"ok"}` immediately.
   - `/api/system/status` should show `"sql_configured": true` and
     `"active_data_source": "sql_server_real"`. If `"data_source_warning"`
     is anything other than `null`, the connection failed — the message
     tells you exactly why (unreachable host, missing table, bad
     credentials, missing ODBC driver, etc.). **Fix the underlying cause
     and re-check — do not consider this done while a warning is present**,
     and do not silently let it fall back to demo data.
   - `/api/meta` should show a `record_count` that matches our real data
     volume, not the demo dataset's `8190`.
   - `/api/dashboard` should return real participant names (from our
     database), not placeholder names like "Lone Star Power Trading LLC"
     or "Permian Basin Energy Partners" — if you see those, the backend is
     still serving the synthetic demo, meaning the SQL connection isn't
     actually being used yet.

9. **Run the full test suite again** after connecting, to confirm nothing
   broke:
   ```
   cd backend
   python -m pytest -q
   ```
   Should still be `93 passed` — these tests don't touch the real
   database (they use an in-memory SQLite fixture for the SQL-specific
   ones), so a real SQL connection shouldn't change this count. If it
   does, something about the environment change broke something else —
   investigate before calling this done.

10. **Start the frontend** and confirm it shows real data end-to-end:
    - Open `frontend/src/ErcotCrrDashboard.jsx` as a standalone app (see
      "Running as a standalone app" in the top-level `README.md`), or open
      the connection bar in whatever version of the UI you're running.
    - Type `http://localhost:8000` (or wherever the backend is actually
      reachable from the browser) into the connection bar and click
      Connect.
    - Confirm the Overview tab shows real participant names and a record
      count matching step 8, and that the connection bar shows "Connected
      — live backend at http://localhost:8000", not "Demo dataset."

## If something doesn't work

Read the actual error message from `/api/system/status`'s
`data_source_warning` field first — it's written to be specific and
actionable (e.g. "could not reach host," "table doesn't exist," "ODBC
driver not found," "authentication failed"), not a generic failure. Fix
the specific thing it names. Do not:
- Hardcode credentials into `db.py` or any other source file — they
  belong in `.env` only.
- Modify `analytics.py`, `scoring.py`, `domain.py`, or `data_generator.py`
  to work around a data issue — if the real data doesn't match the
  expected shape (column names, `crr_type` values other than
  `OBLIGATION`/`OPTION`, etc.), fix that in the SQL view/table, not in
  application code.
- Report success while `/api/system/status` still shows a
  `data_source_warning` or `"active_data_source"` other than
  `"sql_server_real"`.

When it's genuinely working — all three checks in step 8 pass, tests are
still 93/93, and the frontend shows real participant names — tell me
what you changed (which `.env` variables you set, and confirm no source
files outside `.env`/`.gitignore` were modified) so I have a clear record
of what's different between this machine and the one it came from.
