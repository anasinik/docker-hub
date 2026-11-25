"""Registry notifications (webhook) that trigger a tag sync.

See https://distribution.github.io/distribution/about/notifications/

Only two kinds of events start a sync, which keeps a multi-arch push (one
event per platform and attestation manifest, plus the index) to one sync:

* ``push`` of a manifest with a tag: the index or the single-platform image
  that the tag now points to. Untagged platform manifests are skipped.
* ``delete`` of a manifest by digest. The registry also sends one ``delete``
  per tag that pointed to it (without a digest); those are skipped.

Pull events are not sent at all (``ignore.actions`` in the registry config).
"""

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from repositories.services.registry.base import MANIFEST_MEDIA_TYPES


def repositories_to_sync(payload):
    """Return ``{registry path: {tag: push time}}`` for the events that need a sync.

    A manifest delete adds the path with no push times.

    Raises ValueError if the payload is not a notification envelope.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("events"), list):
        raise ValueError("expected an object with an 'events' list")

    paths = {}
    for event in payload["events"]:
        if not isinstance(event, dict):
            continue
        target = event.get("target") or {}
        path = target.get("repository")
        if not path:
            continue

        action = event.get("action")
        is_tag_push = (
            action == "push" and target.get("tag") and target.get("mediaType") in MANIFEST_MEDIA_TYPES
        )
        is_manifest_delete = action == "delete" and target.get("digest") and not target.get("tag")
        if not (is_tag_push or is_manifest_delete):
            continue

        times = paths.setdefault(path, {})
        if is_tag_push:
            # Nanoseconds are cut to microseconds by parse_datetime.
            timestamp = parse_datetime(event.get("timestamp") or "") or timezone.now()
            tag = target["tag"]
            if tag not in times or timestamp > times[tag]:
                times[tag] = timestamp
    return paths
