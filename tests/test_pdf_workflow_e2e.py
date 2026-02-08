"""End-to-end tests for PDF -> Google ADK -> PDF workflow."""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from openbench.adapters.google_adk import GoogleADKAdapter
from openbench.core.layers import DataLayer, IntelligenceLayer, OutputLayer
from openbench.data.sources.pdf import PDFSource
from openbench.output.generators import MarkdownGenerator, PDFGenerator


class TestPDFWorkflowE2E(unittest.TestCase):
    """End-to-end tests for PDF workflow."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

        # Create a sample PDF file for testing
        self.sample_pdf_path = os.path.join(self.temp_dir, "sample.pdf")
        self._create_sample_pdf()

    def tearDown(self):
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_pdf(self):
        """Create a sample PDF for testing."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate

            doc = SimpleDocTemplate(self.sample_pdf_path, pagesize=letter)
            styles = getSampleStyleSheet()
            story = [
                Paragraph("Sample PDF Document", styles["Heading1"]),
                Paragraph("This is a sample PDF document for testing.", styles["Normal"]),
                Paragraph("It contains multiple paragraphs of text.", styles["Normal"]),
                Paragraph("The workflow should extract this text.", styles["Normal"]),
            ]
            doc.build(story)
        except ImportError:
            # Create a simple text file if reportlab not available
            with open(self.sample_pdf_path, "w") as f:
                f.write("Sample PDF content for testing")

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_data_layer_extracts_pdf(self, mock_init):
        """Test that DataLayer extracts PDF content."""
        # Skip if pypdf not installed
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("pypdf not installed")

        source = PDFSource(path=self.sample_pdf_path)
        data_layer = DataLayer(sources=source)

        result = data_layer.invoke({})

        self.assertIn("raw_data", result)
        self.assertGreater(len(result["raw_data"]), 0)

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_intelligence_layer_processes_content(self, mock_init):
        """Test that IntelligenceLayer processes content."""
        # Create mock adapter
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._model = MagicMock()
        adapter._model.generate_content.return_value = MagicMock(
            text="This is the AI summary of the document.", usage_metadata=None
        )

        intel_layer = IntelligenceLayer(agents=adapter)

        # Simulate DataLayer output
        mock_raw = MagicMock()
        mock_raw.content = "Sample PDF content"
        input_data = {"raw_data": [mock_raw], "metadata": {}}

        result = intel_layer.invoke(input_data)

        self.assertIn("intelligence_output", result)
        self.assertIn("content", result["intelligence_output"])

    def test_output_layer_generates_pdf(self):
        """Test that OutputLayer generates PDF."""
        generator = PDFGenerator(template="report")
        output_layer = OutputLayer(generators=generator)

        output_path = os.path.join(self.temp_dir, "output.pdf")

        # Simulate IntelligenceLayer output
        input_data = {
            "intelligence_output": {
                "content": "This is the generated content for the PDF.",
                "model": "gemini-1.5-pro",
            },
            "metadata": {},
        }

        # Patch the output path
        with patch.object(generator, "generate") as mock_gen:
            mock_gen.return_value = MagicMock(file_path=output_path, format="pdf", size_bytes=1000)
            result = output_layer.invoke(input_data)

        self.assertIn("generated_outputs", result)

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_full_workflow_composition(self, mock_init):
        """Test full workflow composition with mock."""
        # Skip if pypdf not installed
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("pypdf not installed")

        # Set up components
        pdf_source = PDFSource(path=self.sample_pdf_path)

        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._model = MagicMock()
        adapter._model.generate_content.return_value = MagicMock(
            text="AI-generated summary of the document content.", usage_metadata=None
        )

        output_path = os.path.join(self.temp_dir, "final_output.pdf")
        pdf_gen = PDFGenerator(template="report")

        # Compose workflow
        workflow = (
            DataLayer(sources=pdf_source)
            | IntelligenceLayer(agents=adapter)
            | OutputLayer(generators=pdf_gen)
        )

        # Execute workflow
        result = workflow.invoke({"output_path": output_path})

        # Verify result structure
        self.assertIn("generated_outputs", result)
        self.assertGreater(len(result["generated_outputs"]), 0)

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_workflow_with_markdown_output(self, mock_init):
        """Test workflow with Markdown output."""
        try:
            import pypdf  # noqa: F401
        except ImportError:
            self.skipTest("pypdf not installed")

        pdf_source = PDFSource(path=self.sample_pdf_path)

        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._model = MagicMock()
        adapter._model.generate_content.return_value = MagicMock(
            text="# Summary\n\nThis is the summary.", usage_metadata=None
        )

        output_path = os.path.join(self.temp_dir, "output.md")
        md_gen = MarkdownGenerator(output_path=output_path)

        workflow = (
            DataLayer(sources=pdf_source)
            | IntelligenceLayer(agents=adapter)
            | OutputLayer(generators=md_gen)
        )

        result = workflow.invoke({"output_path": output_path})

        self.assertIn("generated_outputs", result)


class TestWorkflowDataFlow(unittest.TestCase):
    """Test data flow through workflow layers."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up temp files."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_data_layer_output_format(self):
        """Test DataLayer output format."""
        mock_source = MagicMock()
        mock_raw_data = MagicMock()
        mock_raw_data.content = "Test content"
        mock_source.invoke.return_value = mock_raw_data

        data_layer = DataLayer(sources=mock_source)
        result = data_layer.invoke({})

        self.assertIn("raw_data", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["metadata"]["layer"], "data")

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_intelligence_layer_output_format(self, mock_init):
        """Test IntelligenceLayer output format."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._model = MagicMock()
        adapter._model.generate_content.return_value = MagicMock(
            text="Generated content", usage_metadata=None
        )

        intel_layer = IntelligenceLayer(agents=adapter)

        mock_raw = MagicMock()
        mock_raw.content = "Input content"
        result = intel_layer.invoke({"raw_data": [mock_raw]})

        self.assertIn("intelligence_output", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["metadata"]["layer"], "intelligence")

    def test_output_layer_output_format(self):
        """Test OutputLayer output format."""
        generator = PDFGenerator()
        output_layer = OutputLayer(generators=generator)

        output_path = os.path.join(self.temp_dir, "test.pdf")
        result = output_layer.invoke(
            {"intelligence_output": {"content": "Test"}, "output_path": output_path}
        )

        self.assertIn("generated_outputs", result)
        self.assertIn("metadata", result)
        self.assertEqual(result["metadata"]["layer"], "output")


class TestAdapterIntegration(unittest.TestCase):
    """Test GoogleADKAdapter integration with layers."""

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_adapter_handles_data_layer_output(self, mock_init):
        """Test adapter correctly handles DataLayer output."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._model = MagicMock()
        adapter._model.generate_content.return_value = MagicMock(
            text="Processed content", usage_metadata=None
        )

        # DataLayer output format
        mock_raw = MagicMock()
        mock_raw.content = "PDF extracted text"
        data_output = {"raw_data": [mock_raw], "indexed_ids": [], "metadata": {"layer": "data"}}

        result = adapter.invoke(data_output)

        self.assertIn("content", result)
        self.assertEqual(result["content"], "Processed content")

    @patch("openbench.adapters.google_adk.GoogleADKAdapter._init_client")
    def test_adapter_with_goal_parameter(self, mock_init):
        """Test adapter with goal parameter."""
        adapter = GoogleADKAdapter(model="gemini-1.5-pro", api_key="test-key")
        adapter._model = MagicMock()
        adapter._model.generate_content.return_value = MagicMock(
            text="Summarized content", usage_metadata=None
        )

        mock_raw = MagicMock()
        mock_raw.content = "Long document text"
        input_data = {"raw_data": [mock_raw], "goal": "Summarize this document in 3 sentences"}

        adapter.invoke(input_data)

        # Verify the model was called with prompt containing the goal
        call_args = adapter._model.generate_content.call_args
        prompt = call_args[0][0]
        self.assertIn("Summarize this document", prompt)


if __name__ == "__main__":
    unittest.main()
