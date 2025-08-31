#!/usr/bin/env python3
"""
Driving Theory Questions Scraper for clickclickdrive.de (German Version)
Scrapes all questions and answers from the German driving theory catalog
"""

import json
import csv
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import pandas as pd


class DrivingTheoryScraperDE:
    def __init__(self, base_url: str = "https://www.clickclickdrive.de", delay: float = 0.5):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.delay = delay
        # Share the same images directory with English scraper
        self.images_dir = Path("images")
        self.images_dir.mkdir(exist_ok=True)
        # Share the same videos directory with English scraper
        self.videos_dir = Path("videos")
        self.videos_dir.mkdir(exist_ok=True)
        self.data = []
        
    def fetch_page(self, url: str) -> Optional[BeautifulSoup]:
        """Fetch a page and return BeautifulSoup object"""
        try:
            response = self.session.get(url)
            response.raise_for_status()
            time.sleep(self.delay)
            return BeautifulSoup(response.content, 'lxml')
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            return None
    
    def download_image(self, image_url: str, question_id: str) -> Optional[str]:
        """Download image and return local path"""
        try:
            # Check if image already exists (might have been downloaded by English scraper)
            ext = os.path.splitext(urlparse(image_url).path)[1] or '.png'
            filename = f"{question_id.replace('.', '_')}{ext}"
            filepath = self.images_dir / filename
            
            if filepath.exists():
                print(f"      Image already exists: {filename}")
                return str(filepath)
            
            response = self.session.get(image_url)
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            return str(filepath)
        except Exception as e:
            print(f"Error downloading image {image_url}: {e}")
            return None
    
    def download_video(self, video_url: str, question_id: str) -> Optional[str]:
        """Download video and return local path"""
        try:
            # Check if video already exists (might have been downloaded by English scraper)
            ext = os.path.splitext(urlparse(video_url).path)[1] or '.mp4'
            filename = f"{question_id.replace('.', '_')}{ext}"
            filepath = self.videos_dir / filename
            
            if filepath.exists():
                print(f"      Video already exists: {filename}")
                return str(filepath)
            
            response = self.session.get(video_url, stream=True)
            response.raise_for_status()
            
            # Download in chunks to handle large files
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            return str(filepath)
        except Exception as e:
            print(f"Error downloading video {video_url}: {e}")
            return None
    
    def scrape_themes(self) -> List[Dict[str, str]]:
        """Scrape all themes from the German index page"""
        url = f"{self.base_url}/fragenkatalog"  # German version without /en
        soup = self.fetch_page(url)
        if not soup:
            return []
        
        themes = []
        theme_divs = soup.find_all('div', class_='theoryWorld')
        
        for div in theme_divs:
            link = div.find('a')
            if link:
                theme_url = link.get('href')
                if theme_url:
                    # Extract theme number and name
                    number_span = div.find('span', class_='number')
                    name_span = div.find('span', class_='name')
                    
                    # Extract theme name from URL if not found in spans
                    theme_name = ''
                    if name_span:
                        theme_name = name_span.text.strip()
                    else:
                        # Extract from URL
                        url_name = theme_url.split('/')[-1]
                        # Remove theme number prefix and clean up
                        theme_name = re.sub(r'^[\d\.]+-', '', url_name).replace('-', ' ').title()
                    
                    theme_data = {
                        'url': urljoin(self.base_url, theme_url),
                        'number': number_span.text.strip() if number_span else '',
                        'name': theme_name
                    }
                    themes.append(theme_data)
                    print(f"Found theme: {theme_data['number']} - {theme_data['name']}")
        
        return themes
    
    def scrape_chapters(self, theme_url: str) -> List[Dict[str, str]]:
        """Scrape all chapters from a theme page"""
        soup = self.fetch_page(theme_url)
        if not soup:
            return []
        
        chapters = []
        # Look for all links that match German chapter pattern (without /en/)
        links = soup.find_all('a', href=re.compile(r'/fragenkatalog/[\d\.]+-[^/]+/[\d\.]+-[^/]+$'))
        
        for link in links:
            chapter_url = link.get('href')
            if chapter_url and '/en/' not in chapter_url:  # Ensure we're not getting English links
                # Extract chapter info from parent div
                parent_div = link.find_parent('div', class_='theoryWorld')
                if parent_div:
                    number_span = parent_div.find('span', class_='number')
                    name_span = parent_div.find('span', class_='name')
                else:
                    # Try to extract from link text
                    number_span = link.find('span', class_='number')
                    name_span = link.find('span', class_='name')
                
                # Extract chapter number from URL if not found
                chapter_number = ""
                if number_span:
                    chapter_number = number_span.text.strip()
                    # Remove "Kapitel" prefix if it exists
                    chapter_number = chapter_number.replace('Kapitel ', '')
                else:
                    # Extract from URL pattern
                    match = re.search(r'/([\d\.]+)-', chapter_url.split('/')[-1])
                    if match:
                        chapter_number = match.group(1)
                
                # Extract readable name from URL
                url_name = chapter_url.split('/')[-1]
                # Remove chapter number prefix and clean up
                clean_name = re.sub(r'^[\d\.]+-', '', url_name).replace('-', ' ').title()
                chapter_name = name_span.text.strip() if name_span else clean_name
                
                chapter_data = {
                    'url': urljoin(self.base_url, chapter_url),
                    'number': chapter_number,
                    'name': chapter_name
                }
                chapters.append(chapter_data)
                print(f"  Found chapter: {chapter_data['number']} - {chapter_data['name']}")
        
        return chapters
    
    def scrape_questions(self, chapter_url: str) -> List[Dict[str, str]]:
        """Scrape all question links from a chapter page"""
        soup = self.fetch_page(chapter_url)
        if not soup:
            return []
        
        questions = []
        # Look for all links that match German question pattern (without /en/)
        links = soup.find_all('a', href=re.compile(r'/fragenkatalog/[^/]+/[^/]+/[\d\.]+-\d+(?:-[A-Z])?$'))
        
        for link in links:
            question_url = link.get('href')
            if question_url and '/en/' not in question_url:  # Ensure we're not getting English links
                # Extract question ID from URL
                parts = question_url.split('/')
                if parts:
                    question_id = parts[-1]
                    questions.append({
                        'url': urljoin(self.base_url, question_url),
                        'id': question_id
                    })
                    print(f"    Found question: {question_id}")
        
        return questions
    
    def scrape_question_details(self, question_url: str, theme: Dict, chapter: Dict, question_id: str) -> Optional[Dict]:
        """Scrape details from a specific question page"""
        soup = self.fetch_page(question_url)
        if not soup:
            return None
        
        try:
            # Extract question info
            question_info = soup.find_all('h1', class_='questionInfo')
            question_number = ""
            points = ""
            
            # Parse question info headers
            for info in question_info:
                text = info.text.strip()
                if text.startswith('Frage:'):  # German: "Frage" instead of "Question"
                    question_number = text.replace('Frage:', '').strip()
                elif 'Punkte' in text or 'Punkt' in text:  # German: "Punkte" instead of "Points"
                    points = text
            
            # If question number not found, use the ID from URL
            if not question_number:
                question_number = question_id
            
            # Extract question text
            question_title = soup.find('h2', class_='title')
            question_text = question_title.text.strip() if question_title else ""
            
            # Extract options
            options = []
            options_ul = soup.find('div', class_='options')
            if options_ul:
                for li in options_ul.find_all('li'):
                    option_name = li.find('b', class_='optionName')
                    option_text = li.text.strip() if li else ""
                    if option_name:
                        option_text = option_text.replace(option_name.text, '', 1).strip()
                    options.append({
                        'letter': option_name.text.strip() if option_name else "",
                        'text': option_text
                    })
            
            # Extract correct answers
            correct_answers = []
            correct_section = soup.find('h3', id='correct')
            if correct_section:
                correct_div = correct_section.find_next('div', class_='options')
                if correct_div:
                    for li in correct_div.find_all('li'):
                        option_name = li.find('b', class_='optionName')
                        option_text = li.text.strip() if li else ""
                        if option_name:
                            option_text = option_text.replace(option_name.text, '', 1).strip()
                        correct_answers.append({
                            'letter': option_name.text.strip() if option_name else "",
                            'text': option_text
                        })
            
            # Extract comment/explanation
            comment = ""
            comment_div = soup.find('div', class_='comment')
            if comment_div:
                comment = comment_div.text.strip()
            
            # Check for images and videos
            image_urls = []
            local_image_paths = []
            video_urls = []
            local_video_paths = []
            
            # Look for images and videos in multiple places
            # 1. Check media div and image div (both can contain media)
            media_containers = soup.find_all('div', class_=['media', 'image'])
            for container in media_containers:
                # Check for images
                for img in container.find_all('img'):
                    img_src = img.get('src')
                    if img_src and 'storage.googleapis.com' in img_src:
                        if img_src not in image_urls:
                            image_urls.append(img_src)
                
                # Check for videos
                for video in container.find_all('video'):
                    video_src = video.get('src')
                    if video_src and video_src not in video_urls:
                        video_urls.append(video_src)
                    # Also check source tags inside video
                    for source in video.find_all('source'):
                        source_src = source.get('src')
                        if source_src and source_src not in video_urls:
                            video_urls.append(source_src)
                    # Also capture poster image if available
                    poster = video.get('poster')
                    if poster and 'storage.googleapis.com' in poster and poster not in image_urls:
                        image_urls.append(poster)
            
            # 2. Check all img tags that might contain question images
            for img in soup.find_all('img'):
                img_src = img.get('src')
                if img_src and 'storage.googleapis.com' in img_src and img_src not in image_urls:
                    # Check if it's likely a question image (not a UI element)
                    parent_classes = []
                    for parent in img.parents:
                        if parent.get('class'):
                            parent_classes.extend(parent.get('class'))
                    
                    # Skip navigation/UI images
                    if not any(cls in str(parent_classes) for cls in ['breadcrumb', 'menu', 'nav', 'header', 'footer']):
                        image_urls.append(img_src)
            
            # 3. Check all video tags in the page
            for video in soup.find_all('video'):
                video_src = video.get('src')
                if video_src and video_src not in video_urls:
                    video_urls.append(video_src)
                # Check source tags
                for source in video.find_all('source'):
                    source_src = source.get('src')
                    if source_src and source_src not in video_urls:
                        video_urls.append(source_src)
            
            # 4. Look for video URLs in data attributes or JavaScript
            # Sometimes videos are loaded dynamically
            for elem in soup.find_all(attrs={'data-video-src': True}):
                video_src = elem.get('data-video-src')
                if video_src and video_src not in video_urls:
                    video_urls.append(video_src)
            
            # Check for videos in script tags (common for dynamic loading)
            for script in soup.find_all('script'):
                if script.string:
                    # Look for video URLs in JavaScript
                    video_pattern = r'["\'](https?://[^"\']*\.mp4[^"\']*)["\']'
                    video_matches = re.findall(video_pattern, script.string)
                    for match in video_matches:
                        if match not in video_urls:
                            video_urls.append(match)
            
            # Download all found images (or reuse existing ones)
            for img_url in image_urls:
                local_path = self.download_image(img_url, question_id)
                if local_path:
                    local_image_paths.append(local_path)
            
            # Download all found videos
            for video_url in video_urls:
                # Make sure URL is absolute
                if not video_url.startswith('http'):
                    video_url = urljoin(self.base_url, video_url)
                local_path = self.download_video(video_url, question_id)
                if local_path:
                    local_video_paths.append(local_path)
            
            # Compile all data
            question_data = {
                'theme_number': theme['number'],
                'theme_name': theme['name'],
                'chapter_number': chapter['number'],
                'chapter_name': chapter['name'],
                'question_id': question_id,
                'question_number': question_number.replace('Frage: ', ''),
                'points': points,
                'question_text': question_text,
                'options': options,
                'correct_answers': correct_answers,
                'comment': comment,
                'image_urls': image_urls,
                'local_image_paths': local_image_paths,
                'video_urls': video_urls,
                'local_video_paths': local_video_paths,
                'url': question_url
            }
            
            return question_data
            
        except Exception as e:
            print(f"Error parsing question {question_url}: {e}")
            return None
    
    def scrape_all(self):
        """Main scraping function"""
        print("Starting German scraper...")
        themes = self.scrape_themes()
        
        for theme in themes:
            print(f"\nProcessing theme: {theme['number']} - {theme['name']}")
            chapters = self.scrape_chapters(theme['url'])
            
            for chapter in chapters:
                print(f"\n  Processing chapter: {chapter['number']} - {chapter['name']}")
                questions = self.scrape_questions(chapter['url'])
                
                for question in questions:
                    print(f"    Processing question: {question['id']}")
                    question_data = self.scrape_question_details(
                        question['url'], theme, chapter, question['id']
                    )
                    if question_data:
                        self.data.append(question_data)
        
        print(f"\nScraping complete! Total questions: {len(self.data)}")
    
    def export_json(self, filename: str = "driving_theory_questions_de.json"):
        """Export data to JSON format"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        print(f"Exported to {filename}")
    
    def export_csv(self, filename: str = "driving_theory_questions_de.csv"):
        """Export data to CSV format"""
        if not self.data:
            return
        
        # Flatten the data for CSV
        flattened_data = []
        for item in self.data:
            row = {
                'theme_number': item['theme_number'],
                'theme_name': item['theme_name'],
                'chapter_number': item['chapter_number'],
                'chapter_name': item['chapter_name'],
                'question_id': item['question_id'],
                'question_number': item['question_number'],
                'points': item['points'],
                'question_text': item['question_text'],
                'options': '; '.join([f"{opt['letter']} {opt['text']}" for opt in item['options']]),
                'correct_answers': '; '.join([f"{ans['letter']} {ans['text']}" for ans in item['correct_answers']]),
                'comment': item['comment'],
                'image_paths': '; '.join(item['local_image_paths']),
                'video_paths': '; '.join(item.get('local_video_paths', [])),
                'url': item['url']
            }
            flattened_data.append(row)
        
        df = pd.DataFrame(flattened_data)
        df.to_csv(filename, index=False, encoding='utf-8')
        print(f"Exported to {filename}")
    
    def export_markdown(self, filename: str = "driving_theory_questions_de.md"):
        """Export data to Markdown format"""
        with open(filename, 'w', encoding='utf-8') as f:
            f.write("# Fahrschule Theoriefragen (Deutsch)\n\n")
            
            current_theme = None
            current_chapter = None
            
            for item in self.data:
                # Theme header
                if current_theme != item['theme_number']:
                    current_theme = item['theme_number']
                    f.write(f"\n## {item['theme_number']} {item['theme_name']}\n\n")
                
                # Chapter header
                if current_chapter != item['chapter_number']:
                    current_chapter = item['chapter_number']
                    f.write(f"\n### {item['chapter_number']} {item['chapter_name']}\n\n")
                
                # Question
                f.write(f"\n#### Frage {item['question_number']}\n\n")
                f.write(f"**Punkte:** {item['points']}\n\n")
                f.write(f"**{item['question_text']}**\n\n")
                
                # Images
                if item['local_image_paths']:
                    for img_path in item['local_image_paths']:
                        f.write(f"![Question Image]({img_path})\n\n")
                
                # Videos
                if item.get('local_video_paths'):
                    for video_path in item.get('local_video_paths', []):
                        f.write(f"[Video: {video_path}]({video_path})\n\n")
                
                # Options
                f.write("**Optionen:**\n")
                for option in item['options']:
                    f.write(f"- {option['letter']} {option['text']}\n")
                f.write("\n")
                
                # Correct answers
                f.write("**Richtige Antwort(en):**\n")
                for answer in item['correct_answers']:
                    f.write(f"- {answer['letter']} {answer['text']}\n")
                f.write("\n")
                
                # Comment
                if item['comment']:
                    f.write("**Erklärung:**\n")
                    f.write(f"{item['comment']}\n\n")
                
                f.write("---\n")
        
        print(f"Exported to {filename}")


def main():
    scraper = DrivingTheoryScraperDE()
    
    # Scrape all data
    scraper.scrape_all()
    
    # Export to all formats with _de suffix
    scraper.export_json()
    scraper.export_csv()
    scraper.export_markdown()
    
    print("\nAll done!")


if __name__ == "__main__":
    main()