# Contributing to SignWarden

Open a bug report with a small synthetic reproduction or discuss a proposed change
before starting a large patch. Keep real customer data, credentials and private
logs out of issues and pull requests. Use [SECURITY.md](SECURITY.md) for vulnerabilities.

Install from the repository root with `python -m pip install .`. Run:

```sh
python -I -m unittest discover -s tests -v
```

Include the expected behavior, actual result and tests for the affected behavior.
Describe limitations and preserve unfavorable comparison results.

## Developer Certificate of Origin

Every commit must include a `Signed-off-by` trailer under the
[Developer Certificate of Origin 1.1](https://developercertificate.org/).
Use `git commit -s` to certify that you have the right to submit the contribution
under this project's Apache-2.0 license. Use a name and email you are authorized
to publish; commit metadata and sign-offs are public. Maintainers check sign-offs
before merging. A sign-off certifies provenance; it is not a cryptographic signature.

By participating, follow the [Code of Conduct](CODE_OF_CONDUCT.md).
