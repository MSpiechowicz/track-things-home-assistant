# Repository guidelines

## File size

- Never create or leave a handwritten source, test, or stylesheet file with more
  than **500 physical lines**, including blank lines and comments.
- Apply this limit throughout the repository, including integration code,
  development scripts, and tests.
- When a file approaches the limit, split it by responsibility into focused
  modules. Do not minify, collapse formatting, or combine unrelated statements
  merely to reduce the line count.
- Preserve public imports with re-exports when splitting a public module.
- Split tests only between complete test cases and preserve setup and coverage.
- Generated files, vendored dependencies, and data assets are exempt. Do not
  classify handwritten code as generated or vendored to bypass the limit.
- Run `python scripts/check_file_sizes.py` before finishing. Resolve every
  violation; CI enforces this check.
