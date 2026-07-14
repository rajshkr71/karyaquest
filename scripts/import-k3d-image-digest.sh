#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: import-k3d-image-digest.sh --image <repository:immutable-tag> --digest <sha256:64-hex> [--cluster <name>]

Import a local image into k3d and create its digest-qualified containerd alias.
EOF
}

fail() {
  printf 'Error: %s\n' "$1" >&2
  exit 1
}

image=''
digest=''
cluster=''

while (($#)); do
  case "$1" in
    --help)
      (($# == 1)) || fail '--help does not accept other arguments'
      usage
      exit 0
      ;;
    --image|--digest|--cluster)
      option=$1
      (($# >= 2)) || fail "missing value for $option"
      [[ $2 != --* ]] || fail "missing value for $option"
      case "$option" in
        --image) [[ -z $image ]] || fail 'duplicate --image'; image=$2 ;;
        --digest) [[ -z $digest ]] || fail 'duplicate --digest'; digest=$2 ;;
        --cluster) [[ -z $cluster ]] || fail 'duplicate --cluster'; cluster=$2 ;;
      esac
      shift 2
      ;;
    *) fail "unknown argument: $1" ;;
  esac
done

[[ -n $image ]] || fail '--image is required'
[[ -n $digest ]] || fail '--digest is required'
[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'digest must be sha256 followed by 64 lowercase hexadecimal characters'

# A repository must contain at least one slash-separated lowercase component.
# The final colon, if any, must be after the final slash and introduce a tag.
[[ $image != *@* ]] || fail 'image must be a tagged reference, not a digest reference'
last_component=${image##*/}
[[ $last_component == *:* ]] || fail 'image must include an explicit immutable tag'
repository=${image%:*}
tag=${image##*:}
[[ -n $repository && -n $tag ]] || fail 'malformed image reference'
[[ $tag != latest ]] || fail 'the latest tag is not immutable'
[[ $tag =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || fail 'malformed image reference'
[[ $repository =~ ^[a-z0-9]+([._-][a-z0-9]+)*(:[0-9]+)?(/[a-z0-9]+([._-][a-z0-9]+)*)+$ ]] || fail 'malformed image reference'

first_component=${repository%%/*}
if [[ $first_component == *.* || $first_component == *:* || $first_component == localhost ]]; then
  normalized_repository=$repository
else
  normalized_repository="docker.io/$repository"
fi
runtime_tag="$normalized_repository:$tag"
runtime_digest="$normalized_repository@$digest"

cluster_output=$(sudo k3d cluster list --no-headers 2>/dev/null) || fail 'could not list k3d clusters'
clusters=()
while read -r name _; do
  [[ -n ${name:-} ]] && clusters+=("$name")
done <<< "$cluster_output"

if [[ -n $cluster ]]; then
  found=false
  for name in "${clusters[@]}"; do
    [[ $name == "$cluster" ]] && found=true
  done
  [[ $found == true ]] || fail "k3d cluster not found: $cluster"
else
  ((${#clusters[@]} == 1)) || {
    ((${#clusters[@]} == 0)) && fail 'no k3d clusters found'
    fail 'multiple k3d clusters found; specify --cluster'
  }
  cluster=${clusters[0]}
fi
printf 'cluster verified\n'

repo_digests=$(sudo docker image inspect --format '{{json .RepoDigests}}' "$image" 2>/dev/null) || fail 'local image not found'
[[ $repo_digests == *"@$digest"* ]] || fail 'local image digest does not match requested digest'
printf 'local image verified\n'

timeout 180 sudo k3d image import -c "$cluster" "$image" >/dev/null 2>&1 || fail 'image import failed'
printf 'image imported\n'

node_output=$(sudo k3d node list --no-headers 2>/dev/null) || fail 'could not list k3d nodes'
nodes=()
while read -r node role node_cluster _; do
  if [[ -n ${node:-} && $node_cluster == "$cluster" && ( $role == server || $role == agent ) ]]; then
    nodes+=("$node")
  fi
done <<< "$node_output"
((${#nodes[@]} > 0)) || fail 'cluster has no server or agent nodes'

for node in "${nodes[@]}"; do
  image_list=$(sudo docker exec "$node" ctr --namespace k8s.io images list 2>/dev/null) || fail "could not list imported images on node: $node"
  resolved_digest=$(awk -v expected="$runtime_tag" '$1 == expected { print $3; exit }' <<< "$image_list")
  [[ -n $resolved_digest ]] || fail "imported image tag missing on node: $node"
  [[ $resolved_digest == "$digest" ]] || fail "imported image digest mismatch on node: $node"
  sudo docker exec "$node" ctr --namespace k8s.io images tag --force "$runtime_tag" "$runtime_digest" >/dev/null 2>&1 || fail "could not create digest alias on node: $node"
done

printf '%d nodes verified\n' "${#nodes[@]}"
printf 'digest alias created\n'
