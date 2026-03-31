# Prompt -- fix staging job in PR
The error is:

```
Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]: Traceback (most recent call last):
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "<frozen runpy>", line 198, in _run_module_as_main
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "<frozen runpy>", line 88, in _run_code
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/uvicorn/__main__.py", line 4, in <module>
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     uvicorn.main()
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/click/core.py", line 1485, in __call__
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     return self.main(*args, **kwargs)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:            ^^^^^^^^^^^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/click/core.py", line 1406, in main
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     rv = self.invoke(ctx)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:          ^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/click/core.py", line 1269, in invoke
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     return ctx.invoke(self.callback, **ctx.params)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/click/core.py", line 824, in invoke
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     return callback(*args, **kwargs)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:            ^^^^^^^^^^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/uvicorn/main.py", line 433, in main
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     run(
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/uvicorn/main.py", line 606, in run
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     server.run()
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/uvicorn/server.py", line 75, in run
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     return asyncio_run(self.serve(sockets=sockets), loop_factory=self.config.get_loop_factory())
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/usr/lib/python3.12/asyncio/runners.py", line 194, in run
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     return runner.run(main)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:            ^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/usr/lib/python3.12/asyncio/runners.py", line 118, in run
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     return self._loop.run_until_complete(task)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/usr/lib/python3.12/asyncio/base_events.py", line 687, in run_until_complete
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     return future.result()
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:            ^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/uvicorn/server.py", line 79, in serve
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     await self._serve(sockets)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/uvicorn/server.py", line 86, in _serve
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     config.load()
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/uvicorn/config.py", line 441, in load
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     self.loaded_app = import_from_string(self.app)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/uvicorn/importer.py", line 22, in import_from_string
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     raise exc from None
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/venv/lib/python3.12/site-packages/uvicorn/importer.py", line 19, in import_from_string
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     module = importlib.import_module(module_str)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/usr/lib/python3.12/importlib/__init__.py", line 90, in import_module
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     return _bootstrap._gcd_import(name[level:], package, level)
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "<frozen importlib._bootstrap>", line 1387, in _gcd_import
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "<frozen importlib._bootstrap>", line 1360, in _find_and_load
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "<frozen importlib._bootstrap>", line 1331, in _find_and_load_unlocked
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "<frozen importlib._bootstrap>", line 935, in _load_unlocked
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "<frozen importlib._bootstrap_external>", line 995, in exec_module
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "<frozen importlib._bootstrap>", line 488, in _call_with_frames_removed
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/gateway/main.py", line 15, in <module>
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     from gateway.src.app import create_app
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:   File "/opt/a2a-test/gateway/src/app.py", line 7, in <module>
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]:     from fastapi import APIRouter, FastAPI, Request
  Mar 31 23:39:39 ubuntu-2gb-ash-1 python[103953]: ModuleNotFoundError: No module named 'fastapi'
  Mar 31 23:39:39 ubuntu-2gb-ash-1 systemd[1]: a2a-gateway-test.service: Main process exited, code=exited, status=1/FAILURE
```
See https://github.com/mirni/a2a/actions/runs/23824471272/job/69444422242?pr=20 for details.

## Instructions
* Make changes to fix the installation of a2a-test package.
* Update release process so that after successful release.sh invocation (and release pipeline run), the `main` branch gets updated with the latest release branch (otherwise the version of master branch will be behind the release version, which is wrong)

## Completed

**Date:** 2026-03-31

**Summary:** Fixed staging deployment crash caused by missing `fastapi` dependency in deb postinst scripts. Updated all 3 gateway package postinst scripts (`a2a-gateway`, `a2a-gateway-test`, `a2a-gateway-sandbox`) to install `fastapi>=0.115` instead of `starlette>=0.37`, and bumped `cryptography` to `>=46.0`. Also updated `install_deps.sh` for consistency. Added Step 11 to `release.sh` to automatically merge release branch back to main and clean up the release branch after deployment.
