# J_OS Workspace Bootstrap

This workspace uses a separate J_OS vault.

1. Read the fixed local file `.j_os/project-link.local.md`.
2. Validate `type: j_os_workspace_link`, canonical lowercase `project_id` and `j_os_root`; verify the link is a regular local file and the root resolves to the active J_OS vault.
3. Read `<j_os_root>/Core_OS/Runtime/Entry.md` and follow it for the linked project.

Runtime Entry owns orientation, project-binding resolution, task expansion and workflow transitions. Reuse applicable reads. Load detailed project records and operating rules only when the active task requires them.

If the link, root or binding is missing, unreadable, malformed or contradictory, report the exact problem and stop dependent J_OS routing. Request the missing evidence from Anthony; do not guess paths or create an unverified link.

Keep `.j_os/project-link.local.md` local, untracked and ignored by Git. Do not copy J_OS workflows or live task contracts into this file.

Follow applicable repository-local and scoped instructions alongside the selected J_OS workflow.
