# Security reporting

Report suspected vulnerabilities privately to SignWarden Team at
security@signwarden.com. Include the version, a minimal synthetic reproduction,
expected and observed behavior, and the impact. Do not include credentials,
personal information, or data from systems you are not authorized to test.

The 0.1.x line is the current reporting scope.
We aim to acknowledge a report within 14 days. For a confirmed vulnerability we aim
to release a fix, or publish an advisory with a workaround, within 60 days, and to
credit the reporter if they wish. These are response targets.
This harness runs trusted adapter code and checks controlled-tool effects;
it is not a sandbox or production authorization service. Keep the HTTP service
on its direct loopback interface.
