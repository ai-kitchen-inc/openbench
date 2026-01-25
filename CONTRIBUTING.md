# Contributing to OpenBench

First off, thank you for considering contributing to OpenBench! It's people like you that make OpenBench such a great tool for the agentic AI community.

## 🌟 Why Contribute?

OpenBench is building the future of AI-powered knowledge work, and we need your help. Whether you're:
- A developer who wants to improve the codebase
- A data scientist with ideas for better agent workflows
- A technical writer who can clarify our docs
- A designer who can enhance the UX
- A user with feedback and feature ideas

**There's a place for you here.**

## 📋 Table of Contents

- [Code of Conduct](#-code-of-conduct)
- [Getting Started](#-getting-started)
- [How to Contribute](#-how-to-contribute)
- [Development Workflow](#-development-workflow)
- [Coding Standards](#-coding-standards)
- [Pull Request Process](#-pull-request-process)
- [Community](#-community)

## 📜 Code of Conduct

This project adheres to a Code of Conduct that all contributors are expected to follow. By participating, you are expected to uphold this code.

**Our Standards:**
- Be respectful and inclusive
- Welcome newcomers and help them get started
- Focus on what's best for the community
- Show empathy towards other community members
- Give and receive constructive feedback gracefully

**Not Acceptable:**
- Harassment, trolling, or discriminatory language
- Publishing others' private information
- Other conduct which could reasonably be considered inappropriate

## 🚀 Getting Started

### Prerequisites

Before you begin, ensure you have:
- **Git** installed and configured
- **Node.js** (v18+) or **Python** (3.10+) depending on your contribution area
- **Docker** (optional, for local development)
- A **GitHub account**

### Fork & Clone

1. Fork the OpenBench repository to your GitHub account
2. Clone your fork locally:

```bash
git clone https://github.com/YOUR_USERNAME/openbench.git
cd openbench
```

3. Add the upstream repository:

```bash
git remote add upstream https://github.com/ai-kitchen-inc/openbench.git
```

### Local Development Setup

#### For Python Development (Intelligence Layer, Data Layer):

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install pre-commit hooks
pre-commit install

# Run tests
pytest
```

#### For JavaScript/TypeScript Development (Frontend, API):

```bash
# Install dependencies
npm install

# Run development server
npm run dev

# Run tests
npm test

# Run linter
npm run lint
```

#### Using Docker:

```bash
# Build and run all services
docker-compose up

# Run tests in container
docker-compose run --rm app pytest
```

## 🤝 How to Contribute

### 🐛 Reporting Bugs

Found a bug? Help us fix it!

1. **Check existing issues** to avoid duplicates
2. **Create a new issue** with:
   - Clear, descriptive title
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, versions, etc.)
   - Screenshots/logs if applicable

**Template:**
```markdown
**Description:**
Brief description of the bug

**Steps to Reproduce:**
1. Step one
2. Step two
3. See error

**Expected Behavior:**
What should happen

**Actual Behavior:**
What actually happens

**Environment:**
- OS: macOS 14.2
- OpenBench Version: 0.2.1
- Python/Node Version: 3.11
```

### 💡 Suggesting Features

Have an idea? We want to hear it!

1. **Check discussions/issues** to see if it's already proposed
2. **Open a discussion** in [GitHub Discussions](https://github.com/ai-kitchen-inc/openbench/discussions)
3. Describe:
   - The problem you're trying to solve
   - Your proposed solution
   - Alternative approaches you've considered
   - Impact on existing functionality

### 🔧 Contributing Code

#### Types of Contributions

- **Bug fixes**: Address issues in the issue tracker
- **Features**: Implement new capabilities (discuss first!)
- **Performance**: Optimize existing code
- **Refactoring**: Improve code quality without changing behavior
- **Documentation**: Improve guides, API docs, examples
- **Tests**: Add missing test coverage

#### Before You Code

1. **Discuss major changes** in an issue or discussion first
2. **Check the roadmap** to align with project direction
3. **Look for "good first issue"** labels if you're new
4. **Claim an issue** by commenting before starting work

## 🔄 Development Workflow

### 1. Create a Branch

```bash
# Sync with upstream
git fetch upstream
git checkout main
git merge upstream/main

# Create feature branch
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

**Branch Naming Conventions:**
- `feature/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `test/` - Adding tests
- `perf/` - Performance improvements

### 2. Make Your Changes

- Write clean, readable code
- Follow existing code style
- Add tests for new functionality
- Update documentation as needed
- Keep commits focused and atomic

### 3. Test Your Changes

```bash
# Run all tests
npm test         # JavaScript
pytest           # Python

# Run specific tests
npm test -- path/to/test
pytest tests/test_specific.py

# Check code coverage
npm run test:coverage
pytest --cov=openbench

# Lint your code
npm run lint
flake8 .
black --check .
```

### 4. Commit Your Changes

We follow [Conventional Commits](https://www.conventionalcommits.org/).

**Format:**
```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, no logic change)
- `refactor`: Code refactoring
- `perf`: Performance improvements
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```bash
git commit -m "feat(data-layer): add support for Parquet files"
git commit -m "fix(intelligence): resolve agent timeout issue #123"
git commit -m "docs(api): update REST API examples"
```

### 5. Push to Your Fork

```bash
git push origin feature/your-feature-name
```

## 🎯 Coding Standards

### Python

- **Style Guide**: [PEP 8](https://peps.python.org/pep-0008/)
- **Formatter**: Black (line length: 100)
- **Linter**: Flake8, pylint
- **Type Hints**: Use type annotations (PEP 484)
- **Docstrings**: Google-style docstrings

```python
from typing import List, Optional

def process_documents(
    file_paths: List[str],
    max_size: Optional[int] = None
) -> List[dict]:
    """Process multiple documents and extract metadata.

    Args:
        file_paths: List of paths to document files
        max_size: Maximum file size in bytes (optional)

    Returns:
        List of dictionaries containing document metadata

    Raises:
        FileNotFoundError: If any file path is invalid
        ValueError: If file exceeds max_size
    """
    # Implementation
    pass
```

### JavaScript/TypeScript

- **Style Guide**: [Airbnb JavaScript Style Guide](https://github.com/airbnb/javascript)
- **Formatter**: Prettier
- **Linter**: ESLint
- **TypeScript**: Strict mode enabled

```typescript
interface Document {
  id: string;
  content: string;
  metadata: Record<string, unknown>;
}

/**
 * Process documents and extract metadata
 * @param filePaths - Array of file paths to process
 * @param maxSize - Maximum file size in bytes (optional)
 * @returns Promise resolving to array of processed documents
 */
async function processDocuments(
  filePaths: string[],
  maxSize?: number
): Promise<Document[]> {
  // Implementation
}
```

### General Principles

- **DRY**: Don't Repeat Yourself
- **KISS**: Keep It Simple, Stupid
- **YAGNI**: You Aren't Gonna Need It
- **Write tests** for new functionality
- **Performance matters**, but readability first
- **Document complex logic** with comments
- **Error handling** is not optional

## 🔀 Pull Request Process

### Before Submitting

- [ ] Code follows style guidelines
- [ ] All tests pass
- [ ] New tests added for new features
- [ ] Documentation updated
- [ ] Commits follow conventional commit format
- [ ] Branch is up to date with main

### Submitting Your PR

1. **Push to your fork**
2. **Open a Pull Request** against `main`
3. **Fill out the PR template** completely
4. **Link related issues** (e.g., "Closes #123")

**PR Template:**
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Related Issues
Closes #123

## Testing
Describe testing done:
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed

## Screenshots (if applicable)

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-reviewed code
- [ ] Commented complex areas
- [ ] Updated documentation
- [ ] No new warnings
- [ ] Added tests
- [ ] All tests pass
```

### Review Process

1. **Automated checks** must pass (CI/CD, tests, linting)
2. **Maintainer review** - expect feedback within 48 hours
3. **Address feedback** - make requested changes
4. **Approval** - at least one maintainer approval required
5. **Merge** - maintainer will merge when ready

### After Your PR is Merged

- Delete your feature branch
- Update your local main branch
- Celebrate! 🎉

## 🧪 Testing Guidelines

### Writing Tests

- **Test files**: `test_*.py` or `*.test.ts`
- **Coverage goal**: 80%+ for new code
- **Test structure**: Arrange, Act, Assert

```python
def test_semantic_search_returns_relevant_results():
    # Arrange
    documents = load_test_documents()
    search = SemanticSearch(documents)

    # Act
    results = search.query("artificial intelligence applications")

    # Assert
    assert len(results) > 0
    assert all(r.relevance_score > 0.7 for r in results)
```

### Test Categories

- **Unit tests**: Test individual functions/methods
- **Integration tests**: Test component interactions
- **E2E tests**: Test complete workflows
- **Performance tests**: Benchmark critical paths

## 📚 Documentation

Good documentation is just as important as good code.

### What to Document

- **API changes**: Update OpenAPI/Swagger specs
- **New features**: Add usage examples
- **Configuration**: Document new environment variables
- **Architecture**: Update design docs for structural changes

### Documentation Types

- **Code comments**: Explain "why", not "what"
- **Docstrings**: All public functions, classes, modules
- **README**: Keep usage examples current
- **Wiki**: Detailed guides and tutorials
- **API docs**: Auto-generated from code annotations

## 🎓 Resources for Contributors

- [Architecture Overview](docs/architecture.md)
- [API Documentation](docs/API.md)
- [Getting Started Guide](docs/GETTING_STARTED.md)

## 💬 Community

### Get Help

- **Discord**: [Join our server](https://discord.com/users/openbench.ai)
- **GitHub Discussions**: [Ask questions](https://github.com/ai-kitchen-inc/openbench/discussions)
- **Stack Overflow**: Tag with `openbench`

### Stay Connected

- **Weekly Office Hours**: Thursdays 4pm UTC on Discord
- **Monthly Community Call**: First Wednesday of each month

## 🏆 Recognition

We value our contributors!

- Significant contributions are highlighted in release notes
- Top contributors get special roles in Discord

## ❓ Questions?

Don't hesitate to ask! We're here to help:

- Open a [discussion](https://github.com/ai-kitchen-inc/openbench/discussions)
- Ask in [Discord](https://discord.com/users/openbench.ai)
- Email us at [openbench2026@gmail.com](mailto:openbench2026@gmail.com)

---

<div align="center">

**Thank you for contributing to OpenBench!**

Together, we're building the future of agentic AI.

⭐ [Star the repo](https://github.com/ai-kitchen-inc/openbench) • 💬 [Join Discord](https://discord.com/users/openbench.ai)

</div>
