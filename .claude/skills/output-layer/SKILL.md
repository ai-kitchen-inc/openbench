---
name: output-layer
description: Working with OpenBench output generators for PDF, PowerPoint, Dashboard, Audio, and Markdown. Use when creating output generators, generating reports, or working with the OutputLayer.
---

# Output Layer

OpenBench output layer generates artifacts from processed data.

## Key Files

- `src/openbench/output/generators.py` - All generator implementations
- `src/openbench/output/layer.py` - OutputFactory
- `src/openbench/core/abstractions.py` - OutputGenerator base class, GeneratedOutput

## Available Generators

| Generator | Format | Dependency |
|-----------|--------|------------|
| `PDFGenerator` | PDF | `reportlab` |
| `PowerPointGenerator` | PPTX | `python-pptx` |
| `DashboardGenerator` | HTML | `plotly` |
| `AudioGenerator` | Audio | TTS provider |
| `MarkdownGenerator` | MD | None |

## PDFGenerator

```python
from openbench.output.generators import PDFGenerator

generator = PDFGenerator(
    template="report",        # "default", "report", "corporate"
    page_size="letter",       # "letter", "a4", "legal"
    font_name="Helvetica",
    font_size=11,
    title_font_size=18,
    heading_font_size=14,
)

result = generator.generate(
    content="Report content here...",
    output_path="report.pdf",
    title="Q1 Report",
)
# Returns GeneratedOutput(file_path, format, size_bytes, metadata)
```

Content types supported:
- `str` - Rendered as paragraphs
- `dict` - Keys as section headings, values as content
- `list` - Rendered as bullet points

## MarkdownGenerator

```python
from openbench.output.generators import MarkdownGenerator

generator = MarkdownGenerator()
result = generator.generate(content=data, output_path="output.md")
```

## Using in Workflows

```python
from openbench.core import OutputLayer
from openbench.output.generators import PDFGenerator, MarkdownGenerator

# Single output
workflow = data | intelligence | OutputLayer(generators=PDFGenerator())

# Multiple outputs in parallel
workflow = data | intelligence | OutputLayer(
    generators=PDFGenerator() & MarkdownGenerator()
)
```

## OutputGenerator Interface

```python
from openbench.core.abstractions import OutputGenerator, GeneratedOutput

class MyGenerator(OutputGenerator):
    @property
    def output_format(self) -> str:
        return "custom"  # Required

    def generate(self, content, template=None, **options) -> GeneratedOutput:
        file_path = self._create_output(content)
        return GeneratedOutput(
            file_path=file_path,
            format=self.output_format,
            size_bytes=os.path.getsize(file_path),
            metadata={"template": template}
        )

    def validate(self, content) -> bool:
        return content is not None  # Required
```

## Anti-Patterns

**DO NOT:**
- Import heavy dependencies at module level (reportlab, python-pptx) - use lazy imports
- Assume content is always a string - check type and handle dict/list/str
- Forget `validate()` - it's called before `generate()` in the pipeline
- Return raw file paths - always return `GeneratedOutput` dataclass
- Skip `output_format` property - it's required by the abstract class

## Cross-References

- **Composing Workflows**: Generators are `Chainable`, usable with `|` `&` in OutputLayer → see `composing-workflows` skill
- **Creating Abstractions**: `OutputGenerator` base class details → see `creating-abstractions` skill
- **Intelligence Layer**: Agent output feeds into generators → see `intelligence-layer` skill

For examples, see `examples/workflows/reports/sustainability_report.py`
