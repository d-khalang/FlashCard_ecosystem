# Releasing Container Images

Production releases are built on GitHub-hosted runners and published to the
GitHub Container Registry (GHCR). Production servers should pull these images;
they should not build application source locally.

Images are built once, for a release candidate. The final release re-tags that
candidate's images, so production runs the exact bytes that were checked.

## Publish a Release Candidate

1. Open a release PR that sets `project.version` in `flashcard-project/pyproject.toml`
   to the **final** version (`X.Y.Z`, no `-rc` suffix) and turns the changelog's
   `Unreleased` heading into `vX.Y.Z (date)`. Merge it when CI passes.
2. Publish a GitHub **pre-release** with a new tag `vX.Y.Z-rc.N` on that merge commit.
3. Wait for the `Publish Release Images` workflow to pass.

For a candidate, the workflow reruns all CI checks (`ci.yml`, browser tests
included) on the tagged commit, then builds and publishes these images with the
version and full commit SHA tags:

- `ghcr.io/d-khalang/flashcard-bot`
- `ghcr.io/d-khalang/flashcard-miniapp`
- `ghcr.io/d-khalang/it-conjugator`

It deliberately does not publish a mutable `latest` tag. Each release receives
`flashcard-bot-digest.txt`, `flashcard-miniapp-digest.txt` and
`it-conjugator-digest.txt` assets. These contain the immutable image references
that belong in the private deployment repository. The workflow also publishes an
SBOM and signed build provenance for each image.

## Publish the Final Release

Once the candidate is verified in production (English first, see below):

1. Publish a GitHub Release (not a pre-release) with the tag `vX.Y.Z` on the
   **same commit** as the verified candidate.
2. Wait for the `Publish Release Images` workflow to pass.

For a final tag, the workflow builds nothing and runs no tests. It finds the
highest `vX.Y.Z-rc.N` on the same commit, adds the `X.Y.Z` tag to each of its
images, checks that the tag names the very same digest, and attaches the
candidate's digest files to the final release. A final tag on a commit without a
candidate fails, so a fix after the candidate always needs a new `-rc.N`.

If a promotion fails after the release is published, run the workflow by hand
(Actions, `Publish Release Images`, Run workflow) with the final tag; it runs the
same promotion with the workflow from `main`.

The digests in the final release are the candidate's, so the deployment pins do
not change for the language that already runs the candidate.

## After Publishing

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
2. Cut one release candidate (`vX.Y.Z-rc.N`) per batch, at most once a day. It goes to the
   production English bot and Mini App first; Italian stays on the previous release.
3. Publish the final version only after that candidate passes on English. A fix found there goes
   into the next `-rc.N` of the same batch.
4. **Hotfix path:** a production break or security issue does not wait for the batch. It gets its own
   branch from `main`, its own rc and its own release.
