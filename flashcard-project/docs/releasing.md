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
production runner or production credentials. A published release is not deployed
until you follow the release checklist under "Updates" in that repository's README.

## Release Train

Changes ship in batches, not one release per fix.

1. Merge finished, reviewed changes into `main` whenever they are ready. Before merging, check user-facing
   changes locally, on a real phone when the Mini App or bot messages change
   (`python dev/miniapp_dev.py tunnel`).
2. Cut one release candidate (`vX.Y.Z-rc.N`) per batch, at most once a day, and verify it on the
   stage bot.
3. Publish the final version only after that exact code passes on stage. A fix found on stage goes
   into the next `-rc.N` of the same batch.
4. **Hotfix path:** a production break or security issue does not wait for the batch. It gets its own
   branch from `main`, its own rc and its own release.
