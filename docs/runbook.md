## Local digest-only images in k3d

This helper is for local development only. `sudo k3d image import` imports the
tagged image, but it does not necessarily create the exact digest-qualified
containerd image name used by digest-only GitOps manifests. Create and verify
that alias on every k3d server and agent node with:

```bash
scripts/import-k3d-image-digest.sh \
  --image <repository>:<immutable-tag> \
  --digest sha256:<64-lowercase-hex-characters> \
  --cluster <k3d-cluster-name>
```

`--cluster` may be omitted only when exactly one k3d cluster exists. Rerun the
script after recreating cluster nodes because containerd image aliases are
node-local. Production deployments should pull a real registry-qualified
digest instead of relying on this local import helper.
