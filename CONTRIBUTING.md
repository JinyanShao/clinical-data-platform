# Contributing

## Commit Message Format

Use Conventional Commit-style messages:

```text
<type>(<scope>): <short description>
```

Allowed types:

- `feat`
- `fix`
- `test`
- `refactor`
- `docs`
- `chore`
- `build`
- `ci`
- `perf`
- `security`

Examples:

```text
feat(orders): add order creation endpoint
feat(auth): add role-based authorisation policies
fix(inventory): prevent negative stock during confirmation
test(orders): cover duplicate request handling
refactor(api): extract exception handling middleware
docs(readme): add system architecture diagram
ci(api): run tests on pull requests
build(docker): add local PostgreSQL service
security(auth): validate token issuer and audience
```

Avoid vague commit messages such as:

```text
update
changes
fix
final
final version
test stuff
```

