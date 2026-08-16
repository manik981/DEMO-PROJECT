"""Full E2E tests for the Pipeline Orchestrator."""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock

import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from src.run_pipeline import run_full_pipeline

@pytest.fixture
def mock_pipeline_dependencies():
    async_dict_mock = AsyncMock(return_value={"emitted": 5, "papers_emitted": 5, "startups_emitted": 5, "products_emitted": 5})
    
    # Create mock tracker instance with async persist_telemetry
    mock_tracker_instance = MagicMock()
    mock_tracker_instance.persist_telemetry = AsyncMock()
    mock_tracker_class = MagicMock(return_value=mock_tracker_instance)

    with patch("src.run_pipeline.run_papers_extraction", new=async_dict_mock), \
         patch("src.run_pipeline.run_startups_extraction", new=async_dict_mock), \
         patch("src.run_pipeline.run_products_extraction", new=async_dict_mock), \
         patch("src.run_pipeline.run_news_extraction", new=async_dict_mock), \
         patch("src.run_pipeline.run_jobs_extraction", new=async_dict_mock), \
         patch("src.run_pipeline.process_vertical") as p6, \
         patch("src.run_pipeline.resolve_startups") as p7, \
         patch("src.run_pipeline.resolve_products") as p8, \
         patch("src.run_pipeline.sync_all_tables") as p9, \
         patch("src.run_pipeline.GoogleSheetsExporter") as p10, \
         patch("src.run_pipeline.PipelineTracker", new=mock_tracker_class):
         
        p6.return_value = {"total_records": 5, "final_valid": 5}
        p7.return_value = {"processed": 5, "canonicalized": 5}
        p8.return_value = {"processed": 5, "canonicalized": 5}
        p9.side_effect = AsyncMock(return_value={"total_unique_records": 10})
        
        mock_sheets = MagicMock()
        p10.return_value = mock_sheets
        
        yield {
            "sync": p9,
            "sheets": mock_sheets,
            "process": p6,
            "resolve_startups": p7
        }

@pytest.mark.asyncio
async def test_full_pipeline_success_flow(mock_pipeline_dependencies):
    """Test that all phases execute and call sync correctly."""
    test_user_id = "test-uuid-1234"
    
    # Run the pipeline
    await run_full_pipeline(limit=5, freshness_hours=24.0, user_id=test_user_id)
    
    deps = mock_pipeline_dependencies
    
    # Assert Supabase Sync is called with the exact user_id
    deps["sync"].assert_called_once_with(user_id=test_user_id)
    
    # Assert Google Sheets is exported
    deps["sheets"].export_all_tabs.assert_called_once()
