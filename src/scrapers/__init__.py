"""Scrapers for data intelligence verticals."""

from src.scrapers.jobs import JobsScraper
from src.scrapers.news import NewsScraper
from src.scrapers.papers import PapersScraper
from src.scrapers.products import ProductsScraper
from src.scrapers.startups import StartupsScraper

__all__ = [
    "PapersScraper",
    "StartupsScraper",
    "ProductsScraper",
    "NewsScraper",
    "JobsScraper",
]
