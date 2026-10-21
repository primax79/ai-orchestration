# N048 Project selector lists ~417 empty projects (submodules, nested repos)

- id: N048
- title: Project selector lists ~417 empty projects (submodules, nested repos)
- kind: bug
- status: processed
- created: 2026-10-21T14:08:04.461207+00:00
- author: porting_liferay
- about: vscode-ai-orchestration src/project-resolver.ts; ai-orchestration-ui backend/projects.py
- produced: T049
- processed-by: ai-coding-tools

In the porting_liferay window the task viewer's project dropdown shows 'All projects (418)': only _workspace has tasks (80); the other ~417 are 0/0/0 (Ansible roles, gCube repos: submodules or nested repos). Discovery should only take folders with tasks/00-INDEX.md, so this is likely a resolver defect (counting repos/submodules) plus traversal into git-ignored folders (liferay62/, source_codes/, conductor/) and a symlink (libs-jdk17 -> gcube_repos). Wanted: (1) per-workspace ignore/include config, versioned in the repo (glob on path or name); (2) default: hide projects with no tasks/ or zero tasks, with a 'show empty' toggle; (3) never descend into git-ignored folders and never follow symlinks.
