import re
import urllib.parse
import logging
from typing import List
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time
from django.db.models.signals import post_save
from django.dispatch import receiver
from case_matching.models import Case_matching
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

import os
from selenium import webdriver

# Set the path to the Chrome binary
os.environ['CHROME_BIN'] = '/usr/bin/google-chrome-stable'

# Now create a new Chrome WebDriver instance
driver = webdriver.Chrome()

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # You can set to DEBUG for more detailed logs

# Add a console handler to display logs in the console (optional: also log to a file)
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

def extract_case_details(text: str) -> List[str]:
    if not text:
        logger.warning("No text provided for case extraction.")
        return []

    extracted_details = []

    # Defendant patterns
    defendant_patterns = [
        r'defendant[,\s]+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)+)',
        r'accused[,\s]+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)+)',
        r'([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)+)\s+is\s+charged',
        r'([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)+)\s+was\s+charged'
    ]

    logger.info("Extracting defendants...")
    for pattern in defendant_patterns:
        matches = re.finditer(pattern, text)
        for match in matches:
            name = match.group(1)
            if name not in extracted_details:
                extracted_details.append(name)
                logger.debug(f"Found defendant: {name}")

    # Judge patterns
    judge_patterns = [
        r'[Jj]udge\s+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)*)',
        r'[Hh]onorable\s+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)*)',
        r'[Hh]on\.\s+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)*)',
        r'[Pp]residing\s+[Jj]udge\s+([A-Z][a-zA-Z\-]+(?:\s+[A-Z][a-zA-Z\-]+)*)'
    ]

    logger.info("Extracting judges...")
    for pattern in judge_patterns:
        matches = re.finditer(pattern, text)
        for match in matches:
            name = match.group(1)
            if name not in extracted_details:
                extracted_details.append(name)
                logger.debug(f"Found judge: {name}")

    # Case types
    case_types = {
        'murder': r'\b(?:first|second|third|-)?(?:degree\s+)?(?:murder|homicide|killing)\b',
        'assault': r'\b(?:aggravated\s+)?(?:assault|battery)\b',
        'theft': r'\b(?:grand\s+)?(?:theft|robbery|burglary)\b',
        'family': r'\b(?:divorce|custody|child\s+support|domestic\s+violence)\b',
        'drug': r'\b(?:drug|narcotics|controlled\s+substance|possession)\b',
        'fraud': r'\b(?:wire\s+)?(?:fraud|deception|forgery)\b',
        'sexual': r'\b(?:sexual\s+assault|rape|molestation)\b',
        'traffic': r'\b(?:dui|dwi|driving|traffic)\b'
    }

    logger.info("Extracting case types...")
    text_lower = text.lower()
    for case_type, pattern in case_types.items():
        if re.search(pattern, text_lower):
            if case_type not in extracted_details:
                extracted_details.append(case_type)
                logger.debug(f"Found case type: {case_type}")

    return extracted_details


# Scraping (Similar cases generation)


def scrape_case_laws(search_term, limit=10):
    encoded_search_term = urllib.parse.quote(search_term)
    url = f"https://new.kenyalaw.org/search/?q={encoded_search_term}&court=High+Court&doc_type=Judgment"
    logger.info(f"Opening URL: {url}")

    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Run Chrome in headless mode
    chrome_options.add_argument("--no-sandbox")  # Disable sandboxing for non-root users
    chrome_options.add_argument("--disable-dev-shm-usage")  # Overcome limited resource problems
    chrome_options.add_argument("--disable-gpu")  # Disable GPU hardware acceleration
    chrome_options.add_argument("--window-size=1920,1080")  # Set window size
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")  # Disable automation-controlled flag
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    # Automatically download and use the correct chromedriver version
    try:
        # Use the correct chromedriver path via ChromeDriverManager
        driver_path = ChromeDriverManager().install()
        service = Service(driver_path)
        driver = webdriver.Chrome(service=service, options=chrome_options)
    except Exception as e:
        logger.error(f"Failed to start WebDriver: {str(e)}")
        return []
    
    case_laws = []
    try:
        driver.get(url)
        logger.info("Page loaded successfully")

        # Wait for the page to load completely
        time.sleep(10)

        logger.debug(f"Page Title: {driver.title}")
        logger.debug(f"Current URL: {driver.current_url}")

        # Selectors to try
        selectors_to_try = [
            ("CSS", "li.mb-4.hit", "Result items"),
            ("CSS", "a.h5.text-primary", "Primary links"),
            ("CSS", ".card-title a", "Card title links"),
            ("XPATH", "//li[contains(@class, 'mb-4 hit')]//a[contains(@class, 'h5 text-primary')]", "Complex path")
        ]

        for selector_type, selector, desc in selectors_to_try:
            logger.info(f"Trying to find elements with {desc} ({selector})")
            try:
                if selector_type == "CSS":
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                else:
                    elements = driver.find_elements(By.XPATH, selector)

                logger.debug(f"Found {len(elements)} elements with {desc}")

                if elements:
                    for element in elements[:limit]:
                        try:
                            if selector == "li.mb-4.hit":
                                # For list items, find the link within
                                link_element = element.find_element(By.CSS_SELECTOR, "a.h5.text-primary")
                                title = link_element.text.strip()
                                link = link_element.get_attribute('href')
                            else:
                                # For direct link elements
                                title = element.text.strip()
                                link = element.get_attribute('href')

                            if title and link:
                                case_laws.append((title, link))
                                logger.info(f"Added case: {title[:50]}...")

                        except Exception as e:
                            logger.error(f"Error extracting case info: {str(e)}")

                    if case_laws:
                        break
            except Exception as e:
                logger.error(f"Error with selector {desc}: {str(e)}")

        if not case_laws:
            logger.info("Trying fallback method...")
            try:
                list_items = driver.find_elements(By.CSS_SELECTOR, "ul.list-unstyled li")
                logger.debug(f"Found {len(list_items)} list items")
                for item in list_items[:limit]:
                    try:
                        link_element = item.find_element(By.CSS_SELECTOR, "a.h5.text-primary")
                        title = link_element.text.strip()
                        link = link_element.get_attribute('href')
                        if title and link:
                            case_laws.append((title, link))
                            logger.info(f"Added case from fallback: {title[:50]}...")
                    except Exception as e:
                        logger.error(f"Error in fallback extraction: {str(e)}")
            except Exception as e:
                logger.error(f"Fallback method failed: {str(e)}")

        if not case_laws:
            logger.warning("No results found. Saving page source...")
            with open("page_source.html", "w", encoding="utf-8") as f:
                f.write(driver.page_source)

        return case_laws

    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        driver.save_screenshot("error_screenshot.png")
        return []

    finally:
        driver.quit()

# @receiver(post_save, sender=Case_matching)
# def process_case_matching(sender, instance, created, **kwargs):
#     logger.info(f"processing case matching for {instance}::")
#     if created:
#         transcription_text = instance.transcription.transcription_text
#         all_details = []
#         details = extract_case_details(transcription_text)
#         all_details.extend(details)
#         all_details = list(dict.fromkeys(all_details))
#         search_term = " ".join(all_details)

#         # Scrape cases based on extracted search term
#         scraped_cases = scrape_case_laws(search_term)

#         # Save scraped cases to instance
#         instance.case = [{"title": title, "link": link} for title, link in scraped_cases]
#         instance.save()


