# N043 Registry: warn on registered projects whose folder is gone; discover as a diff

- id: N043
- title: Registry: warn on registered projects whose folder is gone; discover as a diff
- kind: feature
- status: processed
- created: 2026-10-21T08:30:36.144415+00:00
- author: d4science-python-library
- about: -
- produced: T039
- processed-by: ai-coding-tools

The workspace registry still lists a deleted project folder with no warning (projects-list, workspace show, /api/workspace show it with total 0) and lacks three new repos. 'projects discover' proposes the right set but prints the whole list, not added/removed. Wanted: a warning for vanished folders, and discover output as a diff.
