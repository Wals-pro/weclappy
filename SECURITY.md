# Security policy

Security reports are appreciated and should be shared privately so users have
time to update before details become public.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.x | yes: security fixes are released as 1.x patch or minor versions |
| 0.7.0 | never released |
| 0.6.x and older | no; 0.6.0 retries writes on 5xx and 429 and can duplicate them, upgrade to 1.x |

Fixes target the latest 1.x release. Pin a compatible range
(`weclappy>=1.0,<2`) so security releases are picked up.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for the
[Wals-pro/weclappy repository](https://github.com/Wals-pro/weclappy/security/advisories/new).
If that option is unavailable, email `markus@wals.pro` with the subject
`weclappy security report`.

Please include, when applicable:

- affected versions and methods;
- impact and realistic attack conditions;
- a minimal reproduction or proof of concept;
- a suggested mitigation; and
- whether details have already been disclosed elsewhere.

Do not include active API keys, customer data or other secrets. Use
placeholders and the smallest synthetic example that shows the issue.

The maintainers acknowledge reports as soon as practical, investigate, and
coordinate a fix and disclosure with the reporter. This community project
cannot promise a fixed response time, but reports that may expose credentials,
cross tenant boundaries, duplicate writes or corrupt data are treated as high
priority.

## Scope

Relevant reports include:

- the API key reaching logs, metrics, another host, or a redirect target;
- unsafe URL construction or path injection through ids or actions;
- retry behaviour that can repeat a write whose outcome is unknown;
- sensitive response data leaking through errors or logs; and
- dependency or packaging issues that affect weclappy users.

Known boundary: exception messages include up to 4000 characters of the error
response body, and `WeclappAPIError.response.request.headers` holds the
`AuthenticationToken`. Applications must not forward raw exception or
`requests` objects to third-party error reporters.

Vulnerabilities in the weclapp service itself should be reported to weclapp
through its official channels. This repository can only address the Python
client.
