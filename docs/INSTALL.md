# Installing deps behind a proxy / offline

The pipeline needs these PyPI packages in your **runtime** (where scripts run):
- gspread, google-auth, pandas, requests, python-dotenv

## Option 1 — System proxy env vars (quickest)
Set before running `pip`:
```powershell
$Env:HTTPS_PROXY = "http://user:pass@proxyhost:port"
$Env:HTTP_PROXY  = "http://user:pass@proxyhost:port"
python -m pip install --upgrade pip
python -m pip install gspread google-auth pandas requests python-dotenv
```

## Option 2 — Offline / air‑gapped install
On a machine with internet access:
```bash
mkdir wheels
pip download gspread google-auth pandas requests python-dotenv -d wheels
```
Copy the `wheels/` folder to the offline machine, then run:
```bash
pip install --no-index --find-links=./wheels gspread google-auth pandas requests python-dotenv
```
