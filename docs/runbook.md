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

## OpenAI project-key policy

- Use project-scoped API keys and grant only the access required by the
  `llm-gateway` project.
- Never commit, print, log, or pass a key in a shell argument. Do not put a key
  in shell history, an environment-display command, or diagnostic output.
- After installing and validating a replacement key, manually revoke the old
  key. Do not revoke the old key before validation succeeds.
- Obtain and record human approval before **every** paid OpenAI smoke request.
  Approval for one request does not authorize later requests.

## Safe SOPS rotation

The encrypted secret file is
`platform/secrets/local/llm-gateway-openai.secret.yaml`.

1. From the repository root, open it with the interactive editor:

   ```bash
   sops platform/secrets/local/llm-gateway-openai.secret.yaml
   ```

2. Enter the replacement value only inside that editor and save it. Do not use
   `echo`, command-line values, temporary plaintext files, clipboard logging,
   or any method that makes the secret visible in shell history.
3. Update the non-secret deployment revision annotation in Git so GitOps
   creates a new pod. Do not patch the live workload.
4. Review the staged paths and commit only the encrypted secret content and
   the deployment revision annotation change. Never commit plaintext.

## Safe validation

These checks reveal status and object identity only. Keep placeholders
non-sensitive, run commands from the repository root, and do not add output
options that expose environment variables, Secret data, API keys, headers,
tokens, project IDs, or credentials.

```bash
timeout 30 sops filestatus platform/secrets/local/llm-gateway-openai.secret.yaml
timeout 30 argocd app get <application-name>
timeout 30 kubectl -n <namespace> get secret <secret-name> -o name
timeout 30 kubectl -n <namespace> rollout status deployment/<llm-gateway-deployment>
timeout 30 curl --fail --silent --show-error <llm-gateway-healthz-url>
```

Confirm that SOPS reports the file as encrypted, Argo CD is `Synced` and
`Healthy`, the Secret exists, the `llm-gateway` rollout completes, and
`/healthz` succeeds. None of these checks authorizes an OpenAI request.

## Troubleshooting

- **HTTP 429, ordinary rate limit:** treat it as transient provider throttling;
  follow the approved retry/backoff policy and do not log the upstream body.
- **HTTP 429, `insufficient_quota`:** check the project's approved usage limit
  and billing state through authorized administrative channels. Do not retry
  repeatedly or expose quota details.
- **Missing or wrong project-scoped key:** issue and rotate to the correct
  project key using the SOPS procedure; never print either key for comparison.
- **Secret update did not trigger a rollout:** verify the encrypted change was
  reconciled and increment the Git-managed, non-secret deployment revision
  annotation. Do not patch the live Deployment or Secret.
- **KSOPS or age decryption failure:** verify the controller configuration,
  authorized age identity availability, SOPS metadata, and controller events
  without displaying key material or decrypted values.
- **Client response safety:** rate-limit responses must remain sanitized and
  contain no upstream messages or quota details.
- **Audit safety:** `llm.generate.failed` should preserve the safe
  `error_type` (for example, `RateLimitError`) but never the raw upstream
  exception message.

## Rollback

Prefer issuing a new project key over attempting to restore a revoked key.
Revert encrypted content and the deployment revision through Git, then let
Argo CD reconcile. Never manually patch the live Deployment or Secret.

## Audit safety checklist

- Confirm logs contain no prompts, variables, generated output, credentials,
  headers, cookies, project IDs, or raw provider exceptions.
- Record the human approval and deployment revision for an authorized paid
  smoke request.
- Record only safe request IDs and result metadata, such as sanitized outcome,
  status category, latency, and token counts allowed by policy.

## Official references

- [OpenAI project API keys](https://platform.openai.com/docs/api-reference/project-api-keys)
- [OpenAI rate-limit guidance](https://help.openai.com/en/articles/6891753-best-practices-for-managing-rate-limits-in-the-api)
- [OpenAI usage-limit guidance](https://help.openai.com/en/articles/6643435-how-can-i-increase-my-monthly-usage-limits)
- [SOPS age and key management](https://github.com/getsops/sops#encrypting-using-age)
