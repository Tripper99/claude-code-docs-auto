#!/usr/bin/env python3
"""
Claude Code Documentation Scraper

Automatically scrapes Claude Code documentation from Anthropic's documentation site
and converts it to clean Markdown format for offline access.

Usage:
    python scripts/scrape_docs.py
    python scripts/scrape_docs.py --config config.yaml
    python scripts/scrape_docs.py --section overview
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
import yaml
from bs4 import BeautifulSoup
from markdownify import markdownify as md


class ClaudeCodeDocsScraper:
    """Main scraper class for Claude Code documentation."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """Initialize the scraper with configuration."""
        self.config = self._load_config(config_path)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.config['scraping']['user_agent']
        })
        
        # Set up logging
        self._setup_logging()
        self.logger = logging.getLogger(__name__)
        
        # Create output directory
        self.docs_dir = Path(self.config['output']['docs_folder'])
        self.docs_dir.mkdir(exist_ok=True)
        
        # Statistics
        self.stats = {
            'total_sections': 0,
            'successful_scrapes': 0,
            'failed_scrapes': 0,
            'start_time': datetime.now()
        }
    
    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from YAML file."""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"Error: Configuration file '{config_path}' not found.")
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"Error parsing configuration file: {e}")
            sys.exit(1)
    
    def _setup_logging(self):
        """Set up logging configuration."""
        log_config = self.config['logging']
        
        # Create formatter
        formatter = logging.Formatter(log_config['format'])
        
        # Set up root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_config['level']))
        
        # Console handler
        if log_config.get('console', True):
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)
        
        # File handler
        if log_config.get('file'):
            file_handler = logging.FileHandler(log_config['file'])
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
    
    def _make_request(self, url: str, retries: int = None) -> Optional[requests.Response]:
        """Make HTTP request with retry logic."""
        if retries is None:
            retries = self.config['scraping']['retries']
        
        for attempt in range(retries + 1):
            try:
                self.logger.debug(f"Requesting {url} (attempt {attempt + 1}/{retries + 1})")
                
                response = self.session.get(
                    url,
                    timeout=self.config['scraping']['timeout']
                )
                response.raise_for_status()
                return response
                
            except requests.exceptions.RequestException as e:
                if attempt == retries:
                    self.logger.error(f"Failed to fetch {url} after {retries + 1} attempts: {e}")
                    return None
                else:
                    self.logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                    time.sleep(self.config['scraping']['delay_between_requests'])
        
        return None
    
    def _clean_html(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Remove unwanted elements from HTML."""
        # Remove unwanted elements
        for selector in self.config['scraping']['remove_elements']:
            for element in soup.select(selector):
                element.decompose()
        
        return soup
    
    def _extract_content(self, soup: BeautifulSoup) -> Optional[BeautifulSoup]:
        """Extract main content from HTML using configured selectors."""
        for selector in self.config['scraping']['content_selectors']:
            content = soup.select_one(selector)
            if content:
                self.logger.debug(f"Found content using selector: {selector}")
                return content
        
        self.logger.warning("No content found using any configured selector")
        return None
    
    def _convert_to_markdown(self, html_content: str, section: Dict) -> str:
        """Convert HTML content to Markdown."""
        markdown_config = self.config['output']['markdown']
        
        # Convert to markdown
        markdown = md(html_content)
        
        # Add metadata if configured
        output_config = self.config['output']
        if output_config.get('add_section_headers', True):
            header = f"# {section['description']}\n\n"
            markdown = header + markdown
        
        if output_config.get('add_source_url', True):
            base_url = self.config['base_url']
            source_url = base_url + section['url_suffix']
            source_note = f"\n\n---\n\n*Source: {source_url}*\n"
            markdown = markdown + source_note
        
        if output_config.get('add_timestamp', True):
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
            timestamp_note = f"*Last updated: {timestamp}*\n"
            markdown = markdown + timestamp_note
        
        return markdown
    
    def scrape_section(self, section: Dict) -> bool:
        """Scrape a single documentation section."""
        self.logger.info(f"Scraping section: {section['name']}")
        
        # Build URL
        base_url = self.config['base_url']
        url = base_url + section['url_suffix']
        
        # Make request
        response = self._make_request(url)
        if not response:
            self.stats['failed_scrapes'] += 1
            return False
        
        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        soup = self._clean_html(soup)
        
        # Extract content
        content = self._extract_content(soup)
        if not content:
            self.logger.error(f"No content extracted for section: {section['name']}")
            self.stats['failed_scrapes'] += 1
            return False
        
        # Convert to markdown
        try:
            markdown = self._convert_to_markdown(str(content), section)
        except Exception as e:
            self.logger.error(f"Failed to convert to markdown for section {section['name']}: {e}")
            self.stats['failed_scrapes'] += 1
            return False
        
        # Save to file
        output_file = self.docs_dir / section['filename']
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(markdown)
            
            self.logger.info(f"Successfully saved: {output_file}")
            self.stats['successful_scrapes'] += 1
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to save file {output_file}: {e}")
            self.stats['failed_scrapes'] += 1
            return False
    
    def create_index(self):
        """Create an index file listing all documentation sections."""
        index_content = [
            "# Claude Code Documentation Index",
            "",
            "*Auto-generated documentation index*",
            "",
            f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            "## Available Documentation Sections",
            ""
        ]
        
        for section in self.config['sections']:
            filename = section['filename']
            description = section['description']
            index_content.append(f"- **[{section['name']}]({filename})** - {description}")
        
        index_content.extend([
            "",
            "## Usage",
            "",
            "This documentation is scraped automatically from the official Claude Code documentation.",
            "Use these files for offline reference or with Claude Code's `/DOC` command workflow.",
            "",
            "---",
            "",
            "*Generated by Claude Code Documentation Auto-Updater*"
        ])
        
        index_file = self.docs_dir / self.config['output']['index_file']
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(index_content))
        
        self.logger.info(f"Created index file: {index_file}")
    
    def scrape_all(self, section_filter: Optional[str] = None):
        """Scrape all configured documentation sections."""
        sections = self.config['sections']
        
        # Filter sections if specified
        if section_filter:
            sections = [s for s in sections if s['name'] == section_filter]
            if not sections:
                self.logger.error(f"Section '{section_filter}' not found in configuration")
                return
        
        self.stats['total_sections'] = len(sections)
        self.logger.info(f"Starting scrape of {len(sections)} sections")
        
        # Scrape each section
        for i, section in enumerate(sections, 1):
            self.logger.info(f"Processing section {i}/{len(sections)}: {section['name']}")
            
            success = self.scrape_section(section)
            
            # Delay between requests (except for last one)
            if i < len(sections):
                time.sleep(self.config['scraping']['delay_between_requests'])
        
        # Create index
        if not section_filter:  # Only create index when scraping all sections
            self.create_index()
        
        # Print statistics
        self._print_statistics()
    
    def _print_statistics(self):
        """Print scraping statistics."""
        end_time = datetime.now()
        duration = end_time - self.stats['start_time']
        
        self.logger.info("=== Scraping Statistics ===")
        self.logger.info(f"Total sections: {self.stats['total_sections']}")
        self.logger.info(f"Successful: {self.stats['successful_scrapes']}")
        self.logger.info(f"Failed: {self.stats['failed_scrapes']}")
        self.logger.info(f"Success rate: {self.stats['successful_scrapes']/self.stats['total_sections']*100:.1f}%")
        self.logger.info(f"Duration: {duration}")
        self.logger.info("========================")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Scrape Claude Code documentation")
    parser.add_argument(
        '--config',
        default='config.yaml',
        help='Configuration file path (default: config.yaml)'
    )
    parser.add_argument(
        '--section',
        help='Scrape only specific section'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Change to script directory to ensure relative paths work
    script_dir = Path(__file__).parent.parent
    os.chdir(script_dir)
    
    try:
        scraper = ClaudeCodeDocsScraper(args.config)
        
        # Override log level if verbose
        if args.verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        scraper.scrape_all(args.section)
        
    except KeyboardInterrupt:
        print("\nScraping interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()