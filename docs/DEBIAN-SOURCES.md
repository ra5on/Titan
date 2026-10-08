# Sources supplied with Titan Debian images

The Titan license applies to original Titan material. Debian and other third-party components retain their own licenses. Copyright and license notices remain in `/usr/share/doc` in the image; terminal renderer notices are also installed with Titan. See `NOTICE` and `docs/LICENSING.md` in the source repository.

Each new system release supplies the following files beside its image and RAUC bundle:

- `debian-packages.json`: the exact installed binary package versions.
- `debian-sources.json`: the binary-to-source mapping, additional `Built-Using` / `Static-Built-Using` sources, original source filenames, sizes and SHA-256 hashes, the Titan source commit, and any authenticated historical snapshot repositories used.
- `debian-sources.tar.part-000`, `debian-sources.tar.part-001`, etc.: consecutive pieces of one uncompressed tar archive. These contain the unchanged Debian `.dsc`, upstream source and Debian patch archives downloaded from signed official Debian source indexes for the recorded versions.
- `SHA256SUMS` and `SHA256SUMS.sig`: checksums covering these files as well as the image and other release assets. The release signing public key is also available in `packaging/release-public.pem` at the exact Titan source commit. Verify against a trusted copy of that key.

Download **all** source archive pieces from the same release into an empty directory. Verify the signature and the downloaded files before extracting:

```sh
openssl pkeyutl -verify -rawin -pubin -inkey release-public.pem \
  -in SHA256SUMS -sigfile SHA256SUMS.sig
sha256sum --check --ignore-missing SHA256SUMS
cat debian-sources.tar.part-* > debian-sources.tar
mkdir debian-sources
tar -xf debian-sources.tar -C debian-sources
```

`--ignore-missing` allows checking only the files downloaded; it does not confirm that all parts were downloaded. Confirm the numbered sequence is complete by comparing it with the release asset list and `SHA256SUMS`. The extracted `index.json` records the individual source file hashes. Debian source packages can be unpacked with `dpkg-source -x` on the corresponding `.dsc` file. Follow each source package's own build instructions and build dependencies.

Original Titan application sources are available at the exact commit recorded as `titan_source_ref` in `debian-sources.json`, at <https://github.com/ra5on/Titan>. Image build/install scripts are available at the release tag's source commit (`source_commit` in its signed `manifest.json`). These commits match for feature releases; Debian-only maintenance can retain an older application commit. GitHub supplies source archives for both commits. The bundled xterm renderer's separately licensed sources are identified in `titan/web/vendor/terminal/manifest.json`. Optional app containers and ML model caches are downloaded separately when those apps are installed; they are outside this Debian package source archive.

The source collector refuses publication when a recorded Debian source version cannot be obtained. Keeping source downloads available for as long as corresponding binary downloads remain available is a continuing distribution obligation. This technical source collection is not a blanket legal clearance for a future commercial product, non-free firmware, trademarks or the Linux/ZFS license combination.

Older embedded source versions can be absent from current Debian source indexes. For those, the collector uses metadata from the official Debian Snapshot service to select an archive time, then authenticates the historical `InRelease` and source index with the Debian archive keyring through APT. It does not treat HTTPS or Snapshot's SHA-1 file identifiers alone as source authentication. The historical entry disables expiry checking for that frozen index; signature and archive-hash verification stay enabled. Current repositories keep normal expiry checking. Each used historical repository and its exact source versions are recorded in `snapshot_repositories`.
