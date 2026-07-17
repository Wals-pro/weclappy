# Security policy

Security reports are appreciated and should be shared privately so users have
time to update before details become public.

## Supported versions

Security fixes are made against the latest released version. Because the
project is still below 1.0, older versions may not receive separate patches.
Users should upgrade to the newest compatible release and pin that version in
production.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting for the
[Wals-pro/weclappy repository](https://github.com/Wals-pro/weclappy/security/advisories/new).
If that option is unavailable, email `markus@wals.pro` with the subject
`weclappy security report`.

Please include, when applicable:

- affected versions and methods;
- impact and realistic attack conditions;
- a minimal reproduction or proof of concept;
- suggested mitigation; and
- whether any details have already been disclosed elsewhere.

Do not include active API keys, customer data, or other third-party secrets.
Use placeholders and the smallest synthetic example that demonstrates the
issue.

The maintainers will acknowledge the report as soon as practical, investigate
it, and coordinate a fix and disclosure with the reporter. This community
project cannot promise a fixed response SLA, but reports that may expose
credentials, cross-tenant boundaries, duplicate writes, or corrupt data are
treated as high priority.

## Scope

Examples of relevant reports include:

- authentication tokens being exposed to logs or another host;
- unsafe redirects or URL construction;
- retry behavior that can duplicate writes;
- sensitive response data leaking through errors; and
- dependency or packaging issues that affect consumers of `weclappy`.

Vulnerabilities in the weclapp service itself should be reported to weclapp
through its official security channels. This repository can only address the
Python client.
