# How you will work on this project with other people

The purpose of these rules is to make your changes understandable to a teammate.
They are a team agreement, not settings that Git enforces automatically.

## Before you start

Run `git status`. Finish or commit existing work before switching tasks. When a
shared remote exists, start from an up-to-date, clean `main` branch, then create a
short-lived branch for one task. Follow the sequence in
[the teamwork guide](docs/git/03_teamwork.md).

Agree who is working on each task. Useful branch names describe a change, for
example `feature/json-reader`, `test/empty-selection`, or `docs/input-contract`.
Do not create long-lived copies called `final`, `final2`, and `really-final`.

## While you make the change

Keep the input contract stable unless changing it is the explicit task. For
example, do not silently change temperature units or combine different series.
Preserve raw measurements. Keep calibration and numerical processing separate
from file access and logging. Add a test that demonstrates a behaviour, not just
one that imports the new function. Add comments where a choice needs explaining.

Make one logical change at a time. Stage the files you mean to share and read
`git diff --staged` before committing. Do not include generated results, personal
paths, access tokens, or private measurement data.

## Before asking for review

Run the appropriate checks for the edition you are editing:

```bash
# Starter: check the supplied working example.
python -m unittest discover -s checks -p "test_*.py" -v

# Completed reference, or a fully completed student project: include task checks.
python -m unittest discover -s checks -p "*.py" -v
```

On an unfinished starter, optional exercise checks can skip unimplemented tasks.
Report those skips; they do not prove that a task works. In the supplied complete
reference the full suite has 76 passing tests and no skips.

Also inspect `git diff --check` and `git diff --staged --check`. These spot some
whitespace problems; neither command replaces your tests or a code review.

## Describe your change

Use a meaningful commit message, such as `Reject non-list JSON input with a clear
error`. For a review request, write a short paragraph explaining the problem,
what you changed, how you tested it, and anything still incomplete. Include the
actual test command and result, not only “works for me”.

Ask a teammate to review the change before it enters shared `main`. If a review
suggests a correction, add another small commit. Do not force-push shared history
or rewrite a teammate's commits in this course workflow.

A green test run does not prove every input or failure mode is handled. Review
the data contract, names, comments, and assumptions as well as the result.
