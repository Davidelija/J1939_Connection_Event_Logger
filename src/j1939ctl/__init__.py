"""j1939ctl: the maintenance laptop tool (docs/modules.md section 4, v1, frozen for step 7).

Standard library only (LAP-1); talks to the logger with the OpenSSH client
(``ssh`` runs ``j1939cmd``, ``scp`` copies files). It may import only
``j1939logger.config`` and the chain checker in ``tools/verify_chain.py``
(DC-21).
"""

VERSION = "1.0.0"
