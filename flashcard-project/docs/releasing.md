# Releasing Container Images

Production releases are built on GitHub-hosted runners and published to the
GitHub Container Registry (GHCR). Production servers should pull these images;
they should not build application source locally.

## Publish a Release

1. Merge the release changes into `main` and wait for CI to pass.
2. Ensure `project.version` in `flashcard-project/pyproject.toml` matches the
   intended tag without the `v` prefix.
3. Create and push the version tag, for example `v1.2.0`.
4. Publish a GitHub Release from that tag.
5. Wait for the `Publish Release Images` workflow to pass.

The release workflow reruns the complete test suite before publishing. It then
publishes these images using the release version and full commit SHA tags:

- `ghcr.io/d-khalang/flashcard-bot`
- `ghcr.io/d-khalang/it-conjugator`

It deliberately does not publish a mutable `latest` tag. Each GitHub Release
receives `flashcard-bot-digest.txt` and `it-conjugator-digest.txt` assets. These
contain the immutable image references that belong in the private deployment
repository. The workflow also publishes an SBOM and signed build provenance for
each image.

After the first publication, verify each GHCR package has the intended
visibility. Public packages can be pulled without registry credentials; private
packages require a read-only package token on the production server.

Production rollout and rollback belong exclusively to the private
`kartino-deploy` repository. This public repository does not have access to a
production runner or production credentials.
