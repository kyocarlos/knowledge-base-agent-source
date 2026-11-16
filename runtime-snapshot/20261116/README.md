# Runtime snapshot 2026-11-16: code running in the DA40 containers that is in no git commit

The images on DA40 carry a revision label (c7869ce, ba82d79) but were patched afterwards by overlaying files, and those overlays were never committed.
This directory holds a copy of every code file (src, app, config, requirements.txt) whose exact content (git blob hash) exists in no commit of this repository.
Files identical to some commit are not copied; they can be rebuilt from git.

- manifest.json: per container the image, image id, label revision, how many code files it has, and for each copied file its git blob sha1, size and kind
  (modified-from-base = the path exists at the label commit but the content differs; not-in-repo-at-base = the path is not in the label commit at all).
- One directory per container, paths as under /app in the container. Five images: kb-web, kb-celery-search (same image as km-da40-celery_search_worker-1), kb-celery-ingest, km-da40-web-1, km-da40-celery_ingest_worker-1.
- Not copied (may hold credentials, or are backups): config/config.yaml*, config/*.env (the .example files are copied), *.bak, *.pem, *.key, *.db. They are listed under "excluded" in manifest.json.
- Copied from running containers, read-only; no container, image or setting was changed. A pattern scan for credentials found only placeholders and file paths.

This is a record of what runs, not a reviewed change: nothing here has been merged into src/, and several files are older or newer variants of files that exist in src/.
