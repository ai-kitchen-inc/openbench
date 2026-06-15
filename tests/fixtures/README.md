# Test fixtures

Static data files used by the test suite (sample CSV/JSON/PDF inputs, golden
outputs, etc.). Access this directory from a test via the `fixtures_dir`
fixture defined in [`../conftest.py`](../conftest.py):

```python
def test_reads_sample(fixtures_dir):
    data = (fixtures_dir / "sample.csv").read_text()
    ...
```

Keep fixture files small and committed to version control. Do not put secrets
or large binaries here.
