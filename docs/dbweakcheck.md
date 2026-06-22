# dbweakcheck

`dbweakcheck` is an authorized database weak-password audit command. It tests
the credentials you provide against one database endpoint at a time, and it
requires `--authorize` so accidental or unauthorized use is harder to trigger.

Supported database types:

- `mysql`
- `mssql`
- `oracle`
- `postgresql`
- `redis`

Install optional database drivers:

```powershell
python -m pip install -e ".[db-audit]"
```

You can also install only the driver you need:

```powershell
python -m pip install pymysql
python -m pip install pymssql
python -m pip install oracledb
python -m pip install "psycopg[binary]"
python -m pip install redis
```

## Basic Usage

Single password test:

```powershell
dbweakcheck --authorize --db mysql --host 127.0.0.1 --user root --password root
```

Dictionary test:

```powershell
dbweakcheck --authorize `
  --db postgresql `
  --host 127.0.0.1 `
  --database postgres `
  --user postgres `
  --password-file .\passwords.txt
```

Multiple users and passwords:

```powershell
dbweakcheck --authorize `
  --db redis `
  --host 127.0.0.1 `
  --user default `
  --user-file .\users.txt `
  --password redis `
  --password-file .\passwords.txt `
  --empty-password
```

Oracle service name:

```powershell
dbweakcheck --authorize `
  --db oracle `
  --host 127.0.0.1 `
  --service-name ORCLPDB1 `
  --user system `
  --password-file .\passwords.txt
```

Oracle SID:

```powershell
dbweakcheck --authorize `
  --db oracle `
  --host 127.0.0.1 `
  --sid ORCLCDB `
  --user system `
  --password manager
```

MSSQL:

```powershell
dbweakcheck --authorize `
  --db mssql `
  --host 127.0.0.1 `
  --database master `
  --user sa `
  --password-file .\passwords.txt
```

## Useful Options

- `--dry-run`: print how many attempts would be made without connecting.
- `--max-workers 4`: set the concurrency limit.
- `--delay 0.5`: wait before each attempt.
- `--continue-after-success`: keep testing after a valid credential is found.
- `--json-output results.json`: write machine-readable JSON results.
- `--csv-output results.csv`: write CSV results.
- `--fail-on-found`: exit with code `3` when a valid credential is found.
- `--reveal-password`: show raw passwords in output. By default passwords are masked.

By default, only findings and errors are printed. Add `--verbose` to print
failed attempts as well.
